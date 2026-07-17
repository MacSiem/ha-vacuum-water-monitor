"""WebSocket API for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, EVENT_STATE_CHANGED, signal_vacuum_water_updated
from .storage import VacuumWaterStorage
from .tick import list_vacuums


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
    now = datetime.now(timezone.utc)
    state = await _storage(hass).async_reset_tank(
        msg["vacuum_entity"], now.isoformat(), int(now.timestamp() * 1000)
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


def async_register_commands(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for handler in (
        _ws_list_vacuums,
        _ws_get_state,
        _ws_set_settings,
        _ws_remove_user_device,
        _ws_reset_tank,
        _ws_dismiss_intro,
    ):
        websocket_api.async_register_command(hass, handler)
