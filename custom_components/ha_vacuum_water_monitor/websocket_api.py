"""WebSocket API for Vacuum Water Monitor."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .const import DOMAIN, EVENT_STATE_CHANGED, signal_vacuum_water_updated
from .storage import VacuumWaterStorage
from .tick import list_vacuums


_MAX_DEVICES = 100
_MAX_MAINTENANCE_ITEMS = 200
_MAX_SESSIONS_PER_DEVICE = 50
_MAX_CALIBRATIONS = 100
_MAX_CALIBRATION_MODES = 32
_MAX_PATCH_DEPTH = 12
_MAX_PATCH_NODES = 50_000
_MAX_PATCH_TEXT_BYTES = 256_000
_MAX_PATCH_STRING_BYTES = 65_536


def _validate_patch_budget(value: Any) -> None:
    """Reject pathological JSON trees before they reach persistent storage."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    text_bytes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_PATCH_NODES or depth > _MAX_PATCH_DEPTH:
            raise ValueError("settings patch is too large or deeply nested")
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError("settings object keys must be text")
                encoded = len(key.encode("utf-8"))
                if encoded > _MAX_PATCH_STRING_BYTES:
                    raise ValueError("settings patch contains an oversized key")
                text_bytes += encoded
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            encoded = len(current.encode("utf-8"))
            if encoded > _MAX_PATCH_STRING_BYTES:
                raise ValueError("settings patch contains an oversized string")
            text_bytes += encoded
        elif current is not None:
            if not isinstance(current, (bool, int, float)):
                raise ValueError("settings patch contains a non-JSON value")
            if isinstance(current, float) and not math.isfinite(current):
                raise ValueError("settings patch contains a non-finite number")
            if isinstance(current, int) and not isinstance(current, bool):
                # Approximate decimal digits from bit length without allocating
                # another potentially huge string.
                text_bytes += (abs(current).bit_length() * 30_103) // 100_000 + 2
            elif isinstance(current, float):
                text_bytes += 32
        if text_bytes > _MAX_PATCH_TEXT_BYTES:
            raise ValueError("settings patch exceeds the storage budget")


def _safe_icon(value: Any) -> str | None:
    """Return a bounded text icon, rejecting markup for older card builds."""
    if not isinstance(value, str):
        return None
    value = value[:64]
    return value if "<" not in value and ">" not in value else None


def _bounded_text(value: Any, limit: int) -> str | None:
    """Return bounded text without changing its user-visible contents."""
    if not isinstance(value, str):
        return None
    return value[:limit]


def _safe_legacy_text(value: Any, limit: int) -> str | None:
    """Bound text used by older card builds in an unescaped HTML sink."""
    value = _bounded_text(value, limit)
    if value is None:
        return None
    return value if "<" not in value and ">" not in value else None


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number_in_range(value: Any, minimum: float, maximum: float) -> bool:
    if not _finite_number(value):
        return False
    number = float(value)
    return minimum <= number <= maximum


def _valid_vacuum_entity(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"vacuum\.[a-z0-9_]+", value
    ) is not None


def _normalize_device_list(key: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    normalized: list[dict[str, Any]] = []
    for item in value[:_MAX_DEVICES]:
        if not isinstance(item, dict):
            raise ValueError(f"{key} entries must be objects")
        clean = dict(item)
        vacuum_entity = clean.get("vacuum_entity")
        if not _valid_vacuum_entity(vacuum_entity):
            raise ValueError(f"{key} entries require a valid vacuum entity id")
        if "icon" in clean:
            icon = _safe_icon(clean.get("icon"))
            if icon is None:
                clean.pop("icon", None)
            else:
                clean["icon"] = icon
        for field in ("name", "device_name", "label", "brand_profile"):
            if field not in clean:
                continue
            text = _bounded_text(clean.get(field), 255)
            if text is None:
                clean.pop(field, None)
            else:
                clean[field] = text
        for field, minimum, maximum in (
            ("water_total_ml", 0.000001, 1_000_000_000),
            ("wash_volume_ml", 0, 1_000_000_000),
        ):
            if field in clean and not _number_in_range(clean[field], minimum, maximum):
                clean.pop(field, None)
        for field, maximum in (
            ("usage_ml_per_m2", 1_000_000),
            ("intensity_factor", 1_000),
        ):
            if field not in clean:
                continue
            raw_mapping = clean[field]
            if not isinstance(raw_mapping, dict):
                clean.pop(field, None)
                continue
            mapping: dict[str, Any] = {}
            for raw_name, raw_amount in list(raw_mapping.items())[:_MAX_CALIBRATION_MODES]:
                name = _bounded_text(raw_name, 64)
                if name and _number_in_range(raw_amount, 0.000001, maximum):
                    mapping[name] = raw_amount
            if mapping:
                clean[field] = mapping
            else:
                clean.pop(field, None)
        normalized.append(clean)
    return normalized


def _normalize_maintenance_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("maintenance_items must be a list")
    normalized: list[dict[str, Any]] = []
    for item in value[:_MAX_MAINTENANCE_ITEMS]:
        if not isinstance(item, dict):
            raise ValueError("maintenance_items entries must be objects")
        clean = dict(item)
        name = _bounded_text(clean.get("name"), 200)
        if name is None:
            raise ValueError("maintenance item name must be plain text")
        clean["name"] = name
        icon = _safe_icon(clean.get("icon"))
        if icon is None:
            clean.pop("icon", None)
        else:
            clean["icon"] = icon
        if "intervalDays" in clean and clean["intervalDays"] is not None:
            if not _number_in_range(clean["intervalDays"], 1, 365):
                clean.pop("intervalDays", None)
        if "lastDone" in clean and clean["lastDone"] is not None:
            if not _number_in_range(clean["lastDone"], 0, 4_102_444_800_000):
                clean.pop("lastDone", None)
        normalized.append(clean)
    return normalized


def _normalize_sessions(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise ValueError("sessions must be an object")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for raw_key, entries in list(value.items())[:_MAX_DEVICES]:
        if not isinstance(raw_key, str) or not isinstance(entries, list):
            raise ValueError("sessions must map text device keys to lists")
        clean_entries: list[dict[str, Any]] = []
        for item in entries[:_MAX_SESSIONS_PER_DEVICE]:
            if not isinstance(item, dict):
                raise ValueError("session entries must be objects")
            clean = dict(item)
            if "ts" in clean and clean["ts"] not in (None, ""):
                if not _number_in_range(clean["ts"], 0, 4_102_444_800_000):
                    clean.pop("ts", None)
            for field in ("area", "water"):
                if field in clean and clean[field] not in (None, ""):
                    if not _number_in_range(clean[field], 0, 1_000_000_000):
                        clean.pop(field, None)
            if "duration" in clean:
                duration = _safe_legacy_text(clean.get("duration"), 64)
                if duration is None:
                    clean.pop("duration", None)
                else:
                    clean["duration"] = duration
            clean_entries.append(clean)
        normalized[raw_key[:255]] = clean_entries
    return normalized


def _normalize_custom_calibration(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("custom_calibration must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    numeric_fields = (
        "tank_ml",
        "robot_tank_ml",
        "mop_wash_ml",
        "avg_area_per_charge",
    )
    for raw_key, raw_calibration in list(value.items())[:_MAX_CALIBRATIONS]:
        if not isinstance(raw_key, str) or len(raw_key) > 255:
            raise ValueError("custom calibration keys must be bounded text")
        if not isinstance(raw_calibration, dict):
            raise ValueError("custom calibration entries must be objects")
        clean: dict[str, Any] = {}
        for field in numeric_fields:
            raw = raw_calibration.get(field)
            if raw is not None and _number_in_range(raw, 0.000001, 1_000_000_000):
                clean[field] = raw
        for field in ("water_per_m2", "mop_modes"):
            if field not in raw_calibration:
                continue
            raw_modes = raw_calibration[field]
            if not isinstance(raw_modes, dict):
                raise ValueError(f"custom calibration {field} must be an object")
            modes: dict[str, Any] = {}
            for raw_name, raw_amount in list(raw_modes.items())[:_MAX_CALIBRATION_MODES]:
                name = _bounded_text(raw_name, 64)
                if name and _number_in_range(raw_amount, 0.000001, 1_000_000):
                    modes[name] = raw_amount
            if modes:
                clean[field] = modes
        # Preserve bounded scalar extension fields for forwards compatibility.
        for field, raw in raw_calibration.items():
            if field in numeric_fields or field in ("water_per_m2", "mop_modes"):
                continue
            if raw is None or isinstance(raw, (bool, int, float)):
                clean[str(field)[:128]] = raw
            elif isinstance(raw, str):
                text = _bounded_text(raw, 1024)
                if text is not None:
                    clean[str(field)[:128]] = text
        normalized[raw_key] = clean
    return normalized


def _normalize_settings_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Normalize structures rendered by the card without dropping extensions."""
    _validate_patch_budget(patch)
    normalized = dict(patch)
    for key in ("user_devices", "configured_devices"):
        if key in normalized:
            normalized[key] = _normalize_device_list(key, normalized[key])
    if "maintenance_items" in normalized:
        normalized["maintenance_items"] = _normalize_maintenance_items(
            normalized["maintenance_items"]
        )
    if "sessions" in normalized:
        normalized["sessions"] = _normalize_sessions(normalized["sessions"])
    if "custom_calibration" in normalized:
        normalized["custom_calibration"] = _normalize_custom_calibration(
            normalized["custom_calibration"]
        )
    return normalized


def _storage(hass: HomeAssistant) -> VacuumWaterStorage:
    return hass.data[DOMAIN]["storage"]


def _entry_id(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        return entries[0].entry_id
    return DOMAIN


def _notify_store_updated(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    async_dispatcher_send(
        hass, signal_vacuum_water_updated(_entry_id(hass)), payload
    )
    hass.bus.async_fire(EVENT_STATE_CHANGED, payload)


@callback
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/subscribe_state"}
)
def _ws_subscribe_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe authenticated card users to integration-owned updates.

    Core rejects arbitrary event-bus subscriptions for non-admin users. This
    command forwards only this integration's dispatcher payloads and therefore
    works for ordinary household accounts without broad event-bus access.
    """

    @callback
    def _forward(payload: dict[str, Any]) -> None:
        connection.send_event(msg["id"], payload)

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, signal_vacuum_water_updated(_entry_id(hass)), _forward
    )
    connection.send_result(msg["id"])


# NOTE: no require_admin on any command. The card must work for every
# logged-in HA user (household members are rarely admins); WS already
# enforces authentication, and none of these commands expose secrets or
# perform privileged operations (issue #1 follow-up, v5.1.6).
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_vacuums"})
@websocket_api.async_response
async def _ws_list_vacuums(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return HA-known vacuum entities."""
    connection.send_result(msg["id"], {"vacuums": list_vacuums(hass)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
@websocket_api.async_response
async def _ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return persisted settings and tank states."""
    connection.send_result(msg["id"], await _storage(hass).async_get_state())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_settings",
        vol.Required("patch"): dict,
    }
)
@websocket_api.async_response
async def _ws_set_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Patch persisted settings."""
    try:
        settings = await _storage(hass).async_set_settings(
            _normalize_settings_patch(msg["patch"])
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_user_device",
        vol.Required("vacuum_entity"): str,
    }
)
@websocket_api.async_response
async def _ws_remove_user_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Explicitly remove one manually-added device.

    Uses async_replace_settings_key so removing the last device (an empty
    list) is honored — the generic set_settings guard refuses empty-list
    patches to protect against accidental frontend init writes, but an
    explicit user delete is intentional.
    """
    storage = _storage(hass)
    current = await storage.async_get_settings()
    remaining = [
        d
        for d in (current.get("user_devices") or [])
        if not (
            isinstance(d, dict)
            and d.get("vacuum_entity") == msg["vacuum_entity"]
        )
    ]
    await storage.async_replace_settings_key("user_devices", remaining)
    settings = await storage.async_get_settings()
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(
        msg["id"], {"settings": settings, "removed": msg["vacuum_entity"]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reset_tank",
        vol.Required("vacuum_entity"): str,
    }
)
@websocket_api.async_response
async def _ws_reset_tank(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reset a vacuum tank counter."""
    vacuum_entity = msg["vacuum_entity"]
    if not _valid_vacuum_entity(vacuum_entity):
        connection.send_error(msg["id"], "invalid_payload", "invalid vacuum entity id")
        return
    if hass.states.get(vacuum_entity) is None:
        connection.send_error(msg["id"], "not_found", "vacuum entity not found")
        return
    now = datetime.now(timezone.utc)
    try:
        state = await _storage(hass).async_reset_tank(
            vacuum_entity, now.isoformat(), int(now.timestamp() * 1000)
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    _notify_store_updated(
        hass, {"tank_states": {vacuum_entity: state}}
    )
    connection.send_result(msg["id"], {"state": state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dismiss_intro",
        vol.Required("tag"): str,
    }
)
@websocket_api.async_response
async def _ws_dismiss_intro(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist dismissed intro banner state."""
    tag = msg["tag"]
    if len(tag) > 128 or re.fullmatch(r"[A-Za-z0-9_.:-]+", tag) is None:
        connection.send_error(msg["id"], "invalid_payload", "invalid intro tag")
        return
    current = await _storage(hass).async_get_settings()
    dismissed = dict(current.get("intro_dismissed") or {})
    dismissed[tag] = True
    try:
        settings = await _storage(hass).async_set_settings(
            {"intro_dismissed": dismissed}
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"ok": True})


def async_register_commands(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for handler in (
        _ws_subscribe_state,
        _ws_list_vacuums,
        _ws_get_state,
        _ws_set_settings,
        _ws_remove_user_device,
        _ws_reset_tank,
        _ws_dismiss_intro,
    ):
        websocket_api.async_register_command(hass, handler)
