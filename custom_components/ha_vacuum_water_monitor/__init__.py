"""Vacuum Water Monitor integration entry points."""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_CRITICAL_THRESHOLD,
    CONF_WARNING_THRESHOLD,
    DATA_FRONTEND_REGISTERED,
    DATA_STORAGE,
    DATA_TICK_UNSUB,
    DATA_WS_REGISTERED,
    DEFAULT_TICK_INTERVAL_SECONDS,
    DOMAIN,
    EVENT_STATE_CHANGED,
    VERSION,
    signal_vacuum_water_updated,
)
from .storage import VacuumWaterStorage
from .tick import async_tick_water_state
from .websocket_api import async_register_commands

_LOGGER = logging.getLogger(__name__)

_CARD_URL_PATH = f"/{DOMAIN}/ha-vacuum-water-monitor.js"
_CARD_FILENAME = "ha-vacuum-water-monitor.js"
_CARD_PACKAGE_DIR = "www"

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vacuum Water Monitor from a config entry."""
    bucket = hass.data.setdefault(DOMAIN, {})
    storage = VacuumWaterStorage(hass)
    await storage.async_load()
    option_patch = {
        key: entry.options[key]
        for key in (CONF_WARNING_THRESHOLD, CONF_CRITICAL_THRESHOLD)
        if key in entry.options
    }
    if option_patch:
        await storage.async_set_settings(option_patch)
    bucket[DATA_STORAGE] = storage

    if not bucket.get(DATA_WS_REGISTERED):
        async_register_commands(hass)
        bucket[DATA_WS_REGISTERED] = True

    await _async_register_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_start_tick(hass, storage, entry.entry_id)

    _LOGGER.debug("Vacuum Water Monitor set up (entry_id=%s)", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    bucket = hass.data.get(DOMAIN, {})
    if unsub := bucket.pop(DATA_TICK_UNSUB, None):
        unsub()
    bucket.pop(DATA_STORAGE, None)
    _LOGGER.debug("Vacuum Water Monitor unloaded (entry_id=%s)", entry.entry_id)
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the bundled Lovelace card."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get(DATA_FRONTEND_REGISTERED):
        return

    card_path = os.path.join(
        os.path.dirname(__file__), _CARD_PACKAGE_DIR, _CARD_FILENAME
    )
    if not os.path.isfile(card_path):
        _LOGGER.error("Bundled card file missing at %s", card_path)
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}", os.path.dirname(card_path), cache_headers=False
            )
        ]
    )
    add_extra_js_url(hass, f"{_CARD_URL_PATH}?v={VERSION}")
    bucket[DATA_FRONTEND_REGISTERED] = True
    _LOGGER.debug("Registered Lovelace card at %s", _CARD_URL_PATH)


def _async_start_tick(
    hass: HomeAssistant, storage: VacuumWaterStorage, entry_id: str
) -> None:
    """Start the 60s server-side accounting task."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get(DATA_TICK_UNSUB):
        return

    async def _tick(now=None) -> None:
        try:
            changed = await async_tick_water_state(hass, storage)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Water state tick failed: %s", err)
            return
        if changed:
            async_dispatcher_send(
                hass,
                signal_vacuum_water_updated(entry_id),
                {"tank_states": changed},
            )
            hass.bus.async_fire(EVENT_STATE_CHANGED, {"tank_states": changed})

    bucket[DATA_TICK_UNSUB] = async_track_time_interval(
        hass, _tick, timedelta(seconds=DEFAULT_TICK_INTERVAL_SECONDS)
    )
    hass.async_create_task(_tick())
