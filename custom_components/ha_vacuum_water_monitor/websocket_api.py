"""WebSocket API for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN, EVENT_STATE_CHANGED
from .storage import VacuumWaterStorage
from .tick import list_vacuums


def _storage(hass: HomeAssistant) -> VacuumWaterStorage:
    return hass.data[DOMAIN]["storage"]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_vacuums"})
@websocket_api.require_admin
@websocket_api.async_response
async def _ws_list_vacuums(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return HA-known vacuum entities."""
    connection.send_result(msg["id"], {"vacuums": list_vacuums(hass)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
@websocket_api.require_admin
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
@websocket_api.require_admin
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
    hass.bus.async_fire(EVENT_STATE_CHANGED, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reset_tank",
        vol.Required("vacuum_entity"): str,
    }
)
@websocket_api.require_admin
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
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {"tank_states": {msg["vacuum_entity"]: state}},
    )
    connection.send_result(msg["id"], {"state": state})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dismiss_intro",
        vol.Required("tag"): str,
    }
)
@websocket_api.require_admin
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
    hass.bus.async_fire(EVENT_STATE_CHANGED, {"settings": settings})
    connection.send_result(msg["id"], {"ok": True})


def async_register_commands(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for handler in (
        _ws_list_vacuums,
        _ws_get_state,
        _ws_set_settings,
        _ws_reset_tank,
        _ws_dismiss_intro,
    ):
        websocket_api.async_register_command(hass, handler)
