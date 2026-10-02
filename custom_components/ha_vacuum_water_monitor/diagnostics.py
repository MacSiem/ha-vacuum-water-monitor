"""Diagnostics download (Settings > Devices & services > Vacuum Water Monitor)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from .const import DATA_STORAGE, DOMAIN, EVENT_HEAVY_TANK_FIELDS, VERSION

# Names people gave their robots, rooms and helpers are not needed to debug accounting.
TO_REDACT = {"name", "device_name", "label", "friendly_name", "name_by_user", "target_name", "title"}
_HISTORY_KEEP = {"automatic_sessions": 10, "refill_history": 10, "calibration_history": 12}


def _trim_tank(state: dict[str, Any]) -> dict[str, Any]:
    trimmed = {}
    for key, value in state.items():
        if key in _HISTORY_KEEP and isinstance(value, list):
            trimmed[key] = value[: _HISTORY_KEEP[key]]
        elif key in EVENT_HEAVY_TANK_FIELDS and key not in _HISTORY_KEEP:
            trimmed[key] = value if not isinstance(value, (list, dict)) or len(str(value)) < 4000 else "<trimmed>"
        else:
            trimmed[key] = value
    return trimmed


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    from .robots import async_reports
    from .tick import list_vacuums

    stored = await hass.data[DOMAIN][DATA_STORAGE].async_get_state()
    return async_redact_data({
        "version": VERSION,
        "ha_version": HA_VERSION,
        "robots": await async_reports(hass),
        "discovered": list_vacuums(hass),
        "settings": stored.get("settings") or {},
        "tank_states": {vacuum: _trim_tank(state or {}) for vacuum, state in (stored.get("tank_states") or {}).items()},
    }, TO_REDACT)
