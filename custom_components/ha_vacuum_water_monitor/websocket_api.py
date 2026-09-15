"""WebSocket API for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DATA_TICKER, DOMAIN, EVENT_STATE_CHANGED, signal_vacuum_water_updated
from .storage import VacuumWaterStorage
from .tick import list_vacuums
from .calibration import build_contribution_draft, select_recorded_cycle


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
    """Return enriched HA vacuum descriptors."""
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
        settings = await _storage(hass).async_set_settings(msg["patch"])
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


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/reprofile", vol.Required("vacuum_entity"): str})
@websocket_api.async_response
async def _ws_reprofile(hass, connection, msg):
    """Explicitly refresh local profile settings; never call a vacuum service."""
    try:
        settings = await _storage(hass).async_reprofile(msg["vacuum_entity"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings, "vacuums": list_vacuums(hass)})


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
    if not msg["vacuum_entity"].startswith("vacuum.") or hass.states.get(msg["vacuum_entity"]) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    now = datetime.now(timezone.utc)
    state = await _storage(hass).async_reset_tank(
        msg["vacuum_entity"], now.isoformat(), int(now.timestamp() * 1000), source="card"
    )
    _notify_store_updated(
        hass, {"tank_states": {msg["vacuum_entity"]: state}}
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
    current = await _storage(hass).async_get_settings()
    dismissed = dict(current.get("intro_dismissed") or {})
    dismissed[msg["tag"]] = True
    settings = await _storage(hass).async_set_settings(
        {"intro_dismissed": dismissed}
    )
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/calibration_preview",
    vol.Required("vacuum_entity"): str,
    vol.Optional("session_index", default=0): vol.All(int, vol.Range(min=0, max=49)),
    vol.Required("session_ts"): int,
    vol.Optional("observed_ml"): vol.Any(int, float),
    vol.Optional("resolution_ml"): vol.Any(int, float),
})
@websocket_api.async_response
async def _ws_calibration_preview(hass, connection, msg):
    """Read one stored cycle and return an allowlisted draft without saving it."""
    vacuum = msg["vacuum_entity"]
    if not vacuum.startswith("vacuum.") or hass.states.get(vacuum) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    current = await _storage(hass).async_get_state()
    sessions = current.get("tank_states", {}).get(vacuum, {}).get("automatic_sessions", [])
    index = msg.get("session_index", 0)
    try:
        record = select_recorded_cycle(sessions, index, msg["session_ts"])
        draft = build_contribution_draft(record, msg.get("observed_ml"), msg.get("resolution_ml"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    connection.send_result(msg["id"], draft)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/save_measurement",
    vol.Required("vacuum_entity"): str,
    vol.Required("session_index"): vol.All(int, vol.Range(min=0, max=49)),
    vol.Required("session_ts"): int,
    vol.Required("measurement"): dict,
})
@websocket_api.async_response
async def _ws_save_measurement(hass, connection, msg):
    """Save an explicitly confirmed local measurement, without uploading data."""
    vacuum = msg["vacuum_entity"]
    if not vacuum.startswith("vacuum.") or hass.states.get(vacuum) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    try:
        result = await _storage(hass).async_save_measurement(
            vacuum, msg["session_index"], msg["session_ts"], msg["measurement"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    _notify_store_updated(hass, {"settings": await _storage(hass).async_get_settings()})
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_refill_settings",
        vol.Required("vacuum_entity"): str,
        vol.Optional("auto_refill"): vol.Any(None, bool),
        vol.Optional("button_entity"): vol.Any(None, str),
        vol.Optional("lid_entity"): vol.Any(None, str),
    }
)
@websocket_api.async_response
async def _ws_set_refill_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Replace one vacuum's refill choices and bind them immediately."""
    try:
        settings = await _storage(hass).async_set_refill_settings(
            msg["vacuum_entity"],
            auto_refill=msg.get("auto_refill"),
            button_entity=msg.get("button_entity") or None,
            lid_entity=msg.get("lid_entity") or None,
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
    if ticker is not None:
        # Rebinding subscribes to the new button/lid entities right away.
        hass.async_create_task(ticker.run(None))
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings})


def async_register_commands(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for handler in (
        _ws_list_vacuums,
        _ws_get_state,
        _ws_set_settings,
        _ws_remove_user_device,
        _ws_reprofile,
        _ws_reset_tank,
        _ws_set_refill_settings,
        _ws_dismiss_intro,
        _ws_calibration_preview,
        _ws_save_measurement,
    ):
        websocket_api.async_register_command(hass, handler)
