"""Vacuum Water Monitor integration entry points."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_entity_ids
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_CRITICAL_THRESHOLD,
    CONF_WARNING_THRESHOLD,
    DATA_FRONTEND_REGISTERED,
    DATA_STORAGE,
    DATA_TICK_UNSUB,
    DATA_TICKER,
    DATA_WS_REGISTERED,
    DEFAULT_TICK_INTERVAL_SECONDS,
    SERVICE_MARK_REFILLED,
    DOMAIN,
    EVENT_STATE_CHANGED,
    event_tank_states,
    VERSION,
    signal_vacuum_water_updated,
)
from .scheduler import EVENT_SAVE_DELAY_SECONDS, EventTicker
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

    await _async_prune_ghost_devices(hass, storage)

    if not bucket.get(DATA_WS_REGISTERED):
        async_register_commands(hass)
        bucket[DATA_WS_REGISTERED] = True

    await _async_register_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_start_tick(hass, storage, entry.entry_id)
    _async_register_services(hass)

    # Apply option changes immediately. Without this listener the OptionsFlow
    # wrote the new thresholds to the entry but nothing re-read them, so they
    # only took effect after a Home Assistant restart.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.debug("Vacuum Water Monitor set up (entry_id=%s)", entry.entry_id)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-apply changed options immediately (no restart required)."""
    bucket = hass.data.get(DOMAIN, {})
    storage = bucket.get(DATA_STORAGE)
    if storage is None:
        return
    option_patch = {
        key: entry.options[key]
        for key in (CONF_WARNING_THRESHOLD, CONF_CRITICAL_THRESHOLD)
        if key in entry.options
    }
    if option_patch:
        await storage.async_set_settings(option_patch)
        _LOGGER.debug("Applied updated options: %s", sorted(option_patch))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    bucket = hass.data.get(DOMAIN, {})
    if unsub := bucket.pop(DATA_TICK_UNSUB, None):
        unsub()
    bucket.pop(DATA_STORAGE, None)
    if hass.services.has_service(DOMAIN, SERVICE_MARK_REFILLED):
        hass.services.async_remove(DOMAIN, SERVICE_MARK_REFILLED)
    _LOGGER.debug("Vacuum Water Monitor unloaded (entry_id=%s)", entry.entry_id)
    return True


async def _async_prune_ghost_devices(
    hass: HomeAssistant, storage: VacuumWaterStorage
) -> None:
    """One-time cleanup of ghost vacuums (pre-5.1.6 card stub configs).

    Older card versions could persist a configured_device pointing at a brand
    profile's default entity id that never existed in this HA instance. Drop
    such entries — no matching entity AND no tank history — and remove their
    leftover device registry entries so users stop seeing a phantom "Vacuum"
    device (issue #1).
    """
    from homeassistant.helpers import device_registry as dr

    from .sensor_calculations import vacuum_slug
    from .tick import list_vacuums

    state = await storage.async_get_state()
    settings = state.get("settings") or {}
    tank_states = state.get("tank_states") or {}
    known = {vacuum["entity_id"] for vacuum in list_vacuums(hass)}

    def _is_ghost(item: object) -> bool:
        if not isinstance(item, dict):
            return True
        entity = str(item.get("vacuum_entity") or "")
        return bool(entity) and entity not in known and entity not in tank_states

    configured = settings.get("configured_devices") or []
    ghosts = [item for item in configured if _is_ghost(item)]
    if not ghosts:
        return

    kept = [item for item in configured if not _is_ghost(item)]
    ghost_entities = [
        str(item.get("vacuum_entity"))
        for item in ghosts
        if isinstance(item, dict) and item.get("vacuum_entity")
    ]
    _LOGGER.info(
        "Pruning ghost configured_devices with no HA entity: %s", ghost_entities
    )
    await storage.async_replace_settings_key("configured_devices", kept)

    registry = dr.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        # async_get_device(identifiers=...) is deprecated since HA 2026.9.
        ours = {identifier: device
                for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
                for identifier in device.identifiers}
        for entity in ghost_entities:
            device = ours.get((DOMAIN, f"{entry.entry_id}_{vacuum_slug(entity)}"))
            if device:
                registry.async_remove_device(device.id)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the bundled Lovelace card."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get(DATA_FRONTEND_REGISTERED):
        return

    card_dir = Path(__file__).parent / _CARD_PACKAGE_DIR
    card_path = card_dir / _CARD_FILENAME
    if not await hass.async_add_executor_job(card_path.is_file):
        _LOGGER.error("Bundled card file missing at %s", card_path)
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}", str(card_dir), cache_headers=False
            )
        ]
    )
    add_extra_js_url(hass, f"{_CARD_URL_PATH}?v={VERSION}")
    bucket[DATA_FRONTEND_REGISTERED] = True
    _LOGGER.debug("Registered Lovelace card at %s", _CARD_URL_PATH)


def _async_start_tick(
    hass: HomeAssistant, storage: VacuumWaterStorage, entry_id: str
) -> None:
    """Tick on bound entity changes, with a 60 s heartbeat as the fallback."""
    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get(DATA_TICK_UNSUB):
        return
    subscription: dict[str, Any] = {"unsub": None}

    def _publish(changed: dict[str, Any]) -> None:
        if changed:
            async_dispatcher_send(
                hass,
                signal_vacuum_water_updated(entry_id),
                {"tank_states": changed},
            )
            hass.bus.async_fire(EVENT_STATE_CHANGED, {"tank_states": event_tank_states(changed), "partial": True})

    @callback
    def _on_state_change(event: Event) -> None:
        data = event.data
        ticker.handle_change(data.get("entity_id"), data.get("old_state"), data.get("new_state"))

    def _rebind(devices: list[dict[str, Any]]) -> None:
        if not ticker.update_bindings(devices) and subscription["unsub"] is not None:
            return
        if subscription["unsub"] is not None:
            subscription["unsub"]()
            subscription["unsub"] = None
        if ticker.entities:
            subscription["unsub"] = async_track_state_change_event(
                hass, sorted(ticker.entities), _on_state_change
            )

    async def _run(vacuums: set[str] | None) -> None:
        try:
            changed = await async_tick_water_state(
                hass,
                storage,
                vacuum_entities=vacuums,
                delay_save_seconds=EVENT_SAVE_DELAY_SECONDS if vacuums is not None else None,
                on_devices=_rebind if vacuums is None else None,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Water state tick failed: %s", err)
            return
        _publish(changed)

    def _schedule(delay: float, action: Any) -> Any:
        # A plain function would run in the executor; the ticker must stay on the loop.
        @callback
        def _fire(now: Any) -> None:
            action(now)

        return async_call_later(hass, delay, _fire)

    ticker = EventTicker(
        run_tick=_run,
        schedule=_schedule,
        create_task=hass.async_create_task,
    )
    bucket[DATA_TICKER] = ticker

    async def _heartbeat(now=None) -> None:
        await ticker.run(None)

    cancel_interval = async_track_time_interval(
        hass, _heartbeat, timedelta(seconds=DEFAULT_TICK_INTERVAL_SECONDS)
    )

    def _unsubscribe() -> None:
        cancel_interval()
        ticker.cancel()
        if subscription["unsub"] is not None:
            subscription["unsub"]()
            subscription["unsub"] = None

    bucket[DATA_TICK_UNSUB] = _unsubscribe
    hass.async_create_task(_heartbeat())


def _async_register_services(hass: HomeAssistant) -> None:
    """Register ``mark_refilled`` for automations, scripts and dashboards."""
    if hass.services.has_service(DOMAIN, SERVICE_MARK_REFILLED):
        return

    async def _mark_refilled(call: ServiceCall) -> None:
        bucket = hass.data.get(DOMAIN, {})
        storage: VacuumWaterStorage | None = bucket.get(DATA_STORAGE)
        if storage is None:
            raise HomeAssistantError("Vacuum Water Monitor is not loaded")
        try:  # Home Assistant 2025+: (call); older releases: (hass, call)
            extracted = await async_extract_entity_ids(call)
        except TypeError:
            extracted = await async_extract_entity_ids(hass, call)
        entity_ids = sorted(entity_id for entity_id in extracted if entity_id.startswith("vacuum."))
        if not entity_ids:
            raise ServiceValidationError("Select at least one vacuum entity")
        # A robot the user linked as a duplicate (Matter copy) refills its owner.
        settings = (await storage.async_get_state()).get("settings") or {}
        links = settings.get("robot_links") if isinstance(settings.get("robot_links"), dict) else {}
        entity_ids = sorted({
            links[entity_id] if links.get(entity_id) and links[entity_id] != "distinct" else entity_id
            for entity_id in entity_ids
        })
        now = datetime.now(timezone.utc)
        changed = {}
        for entity_id in entity_ids:
            changed[entity_id] = await storage.async_reset_tank(
                entity_id, now.isoformat(), int(now.timestamp() * 1000), source="service"
            )
        for entry in hass.config_entries.async_entries(DOMAIN):
            async_dispatcher_send(hass, signal_vacuum_water_updated(entry.entry_id), {"tank_states": changed})
        hass.bus.async_fire(EVENT_STATE_CHANGED, {"tank_states": event_tank_states(changed), "partial": True})

    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_REFILLED,
        _mark_refilled,
        schema=cv.make_entity_service_schema({}),
    )
