"""Vacuum Water Monitor integration entry points."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_extract_entity_ids
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er
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
    VERSION,
    signal_vacuum_water_updated,
)
from .scheduler import EVENT_SAVE_DELAY_SECONDS, EventTicker
from .frontend_resource import async_register_card_resource, card_resource_url
from .robots import (
    ISSUE_SYNC_TICK_DELAY_SECONDS,
    async_clear_issues,
    async_mark_refilled,
    async_schedule_issue_sync,
)
from .storage import VacuumWaterStorage
from .tick import async_tick_water_state
from .websocket_api import _notify_store_updated, async_register_commands

_LOGGER = logging.getLogger(__name__)

_CARD_URL_PATH = f"/{DOMAIN}/ha-vacuum-water-monitor.js"
_PANEL_URL_PATH = "vacuum-water-monitor"
_CARD_FILENAME = "ha-vacuum-water-monitor.js"
_CARD_PACKAGE_DIR = "www"

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON]


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

    await storage.async_reconcile_registry(_vacuum_registry_identities(hass))
    stop_registry, registry_tasks = _listen_vacuum_registry(hass, storage)
    bucket["_registry_listener"] = (stop_registry, registry_tasks)
    entry.async_on_unload(stop_registry)

    await _async_prune_ghost_devices(hass, storage)

    if not bucket.get(DATA_WS_REGISTERED):
        async_register_commands(hass)
        bucket[DATA_WS_REGISTERED] = True

    await _async_register_frontend(hass)
    await _async_register_standalone_panel(hass)
    await _async_notify_first_setup(hass, storage)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_start_tick(hass, storage, entry.entry_id)
    _async_register_services(hass)
    # Repairs wait for Home Assistant to finish starting (robots load late).
    async_schedule_issue_sync(hass)

    # Apply option changes immediately. Without this listener the OptionsFlow
    # wrote the new thresholds to the entry but nothing re-read them, so they
    # only took effect after a Home Assistant restart.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.debug("Vacuum Water Monitor set up (entry_id=%s)", entry.entry_id)
    return True


@callback
def _vacuum_registry_identities(hass: HomeAssistant) -> dict[str, list[str]]:
    """Snapshot authoritative registry identity, never names or model guesses."""
    result = {}
    for entity in er.async_get(hass).entities.values():
        if (entity.entity_id.startswith("vacuum.") and entity.platform and entity.unique_id):
            result[entity.entity_id] = [entity.platform, entity.unique_id, entity.config_entry_id or ""]
    return result


@callback
def _listen_vacuum_registry(hass: HomeAssistant, storage: VacuumWaterStorage):
    tasks = set()
    async def process(event: Event) -> None:
        old = event.data.get("old_entity_id")
        new = event.data.get("entity_id")
        if isinstance(old, str) and isinstance(new, str) and old.startswith("vacuum.") and new.startswith("vacuum."):
            ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
            renamed = (await ticker.run_serialized(lambda: storage.async_rename_vacuum(old, new))
                       if ticker is not None else await storage.async_rename_vacuum(old, new))
            if renamed:
                _notify_store_updated(hass, {"registry_rename": {"old": old, "new": new}})
                if ticker is not None:
                    await ticker.run(None)
        if isinstance(new, str) and new.startswith("vacuum."):
            ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
            async def reconcile() -> None:
                await storage.async_reconcile_registry(_vacuum_registry_identities(hass))
            if ticker is not None:
                await ticker.run_serialized(reconcile)
            else:
                await reconcile()
            if not old:
                _notify_store_updated(hass, {"registry_changed": True})

    def source_entities() -> set[str]:
        registry = er.async_get(hass)
        devices = {item.device_id for item in registry.entities.values()
                   if item.domain == "vacuum" and item.device_id and item.platform != DOMAIN}
        return {item.entity_id for item in registry.entities.values()
                if item.device_id in devices and item.platform != DOMAIN}

    known_sources = source_entities()

    @callback
    def on_registry_update(event: Event) -> None:
        nonlocal known_sources
        entity_id = str(event.data.get("entity_id") or "")
        old_sources = known_sources
        known_sources = source_entities()
        if not entity_id.startswith("vacuum."):
            own = er.async_get(hass).async_get(entity_id)
            if own is not None and own.platform == DOMAIN:
                # Moving our entities fires registry events synchronously. Their
                # managers already perform that move; echoing it back here can
                # recursively reconcile and delete a live fallback mid-move.
                return
            if entity_id not in old_sources and entity_id not in known_sources:
                return
            _notify_store_updated(hass, {"registry_changed": True})
            ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
            if ticker is not None:
                task = hass.async_create_task(ticker.run(None))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            return
        task = hass.async_create_task(process(event))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    unsubscribe = hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, on_registry_update)
    active = True
    @callback
    def stop() -> None:
        nonlocal active
        if active:
            active = False
            unsubscribe()
    return stop, tasks


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
        current = await storage.async_get_settings()
        if all(current.get(key) == value for key, value in option_patch.items()):
            return
        settings = await storage.async_set_settings(option_patch)
        _notify_store_updated(hass, {"settings": settings})
        _LOGGER.debug("Applied updated options: %s", sorted(option_patch))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    bucket = hass.data.get(DOMAIN, {})
    if bucket.pop("_standalone_panel_registered", False):
        from homeassistant.components import frontend
        frontend.async_remove_panel(hass, _PANEL_URL_PATH)
    listener = bucket.pop("_registry_listener", None)
    if listener:
        stop, tasks = listener
        stop()
        if tasks:
            await asyncio.gather(*tasks)
    if unsub := bucket.pop(DATA_TICK_UNSUB, None):
        unsub()
    async_clear_issues(hass)
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


class _LegacyPanelRedirect(HomeAssistantView):
    """Keep prior panel links usable without shadowing existing static files."""

    url = f"/{DOMAIN}"
    name = f"{DOMAIN}:legacy-panel"
    requires_auth = False

    async def get(self, request):
        raise web.HTTPFound(location=str(request.rel_url.with_path(f"/{_PANEL_URL_PATH}", keep_query=True)))


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

    # Register the two shipped files at their existing URLs, not a directory
    # prefix that captures the panel path itself. The old exact panel link can
    # then redirect without colliding with a static route.
    if not bucket.get("_legacy_panel_redirect_registered"):
        hass.http.register_view(_LegacyPanelRedirect)
        bucket["_legacy_panel_redirect_registered"] = True
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(_CARD_URL_PATH, str(card_path), cache_headers=False),
            StaticPathConfig(f"/{DOMAIN}/vwm-panel.js", str(card_dir / "vwm-panel.js"), cache_headers=False),
        ]
    )
    card_bytes = await hass.async_add_executor_job(card_path.read_bytes)
    card_url = card_resource_url(_CARD_URL_PATH, VERSION, card_bytes)
    registration = await async_register_card_resource(hass, card_url, _CARD_FILENAME)
    if registration == "extra_js_url":
        add_extra_js_url(hass, card_url)
    bucket[DATA_FRONTEND_REGISTERED] = True
    _LOGGER.debug("Registered Lovelace card at %s via %s", _CARD_URL_PATH, registration)


async def _async_register_standalone_panel(hass: HomeAssistant) -> None:
    """Register our own on-demand panel independently of other HA Tools."""
    from homeassistant.components import panel_custom
    from homeassistant.setup import async_setup_component

    bucket = hass.data.setdefault(DOMAIN, {})
    if bucket.get("_standalone_panel_registered"):
        return
    if not await async_setup_component(hass, "panel_custom", {}):
        _LOGGER.error("Could not set up the standalone panel")
        return
    await panel_custom.async_register_panel(
        hass, frontend_url_path=_PANEL_URL_PATH, webcomponent_name="vwm-standalone-panel",
        sidebar_title="Vacuum Water Monitor", sidebar_icon="mdi:water-percent",
        module_url=f"/{DOMAIN}/vwm-panel.js", require_admin=False,
    )
    bucket["_standalone_panel_registered"] = True


async def _async_notify_first_setup(hass: HomeAssistant, storage: VacuumWaterStorage) -> None:
    """Offer the panel once; an explicit dismissal is not undone by reload."""
    from homeassistant.components import persistent_notification
    from homeassistant.setup import async_setup_component

    state = await storage.async_get_state()
    if state.get("settings", {}).get("standalone_intro_shown"):
        return
    if not await async_setup_component(hass, "persistent_notification", {}):
        _LOGGER.warning("Could not start the introduction notification")
        return
    persistent_notification.async_create(
        hass,
        "Open [Vacuum Water Monitor](/vacuum-water-monitor) to see your robots and add a card. "
        "Otwórz [Vacuum Water Monitor](/vacuum-water-monitor), aby zobaczyć roboty i dodać kartę.",
        title="Vacuum Water Monitor", notification_id="ha_vacuum_water_monitor_intro",
    )
    try:
        await storage.async_set_settings({"standalone_intro_shown": True})
    except OSError:
        _LOGGER.warning("Could not remember the standalone introduction")


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
            hass.bus.async_fire(EVENT_STATE_CHANGED, {"state_changed": True})
            async_schedule_issue_sync(hass, ISSUE_SYNC_TICK_DELAY_SECONDS)

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

    async def _run(vacuums: set[str] | None) -> bool:
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
            return False
        _publish(changed)
        return True

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
        try:  # Home Assistant 2025.10+: (call); 2025.1-2025.9: (hass, call)
            extracted = await async_extract_entity_ids(call)
        except TypeError:
            extracted = await async_extract_entity_ids(hass, call)
        entity_ids = sorted(entity_id for entity_id in extracted if entity_id.startswith("vacuum."))
        if not entity_ids:
            raise ServiceValidationError("Select at least one vacuum entity")
        # Check both requested copies and resolved owners before any side effect.
        from homeassistant.exceptions import Unauthorized
        from .feature_access import check_access, reset_write_guard, set_write_guard
        from .robots import resolve_balance_owner
        stored = await storage.async_get_state()
        owners = {resolve_balance_owner(hass, stored, entity_id) for entity_id in entity_ids}
        resources = set(entity_ids) | owners
        user_id = call.context.user_id
        if not await check_access(hass, user_id, "water", "execute", resources):
            raise Unauthorized()
        token = set_write_guard(user_id, "water", resources, route_sources=entity_ids)
        try:
            for entity_id in sorted(owners):
                await async_mark_refilled(hass, entity_id, "service")
        finally:
            reset_write_guard(token)

    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_REFILLED,
        _mark_refilled,
        schema=cv.make_entity_service_schema({}),
    )
