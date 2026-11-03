"""Shared device identity and per-robot entity creation for all platforms."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DATA_STORAGE, DOMAIN, MANUFACTURER, MODEL, signal_vacuum_water_updated
from .sensor_calculations import build_vacuum_devices, filter_active_devices, vacuum_slug

_LOGGER = logging.getLogger(__name__)


def vacuum_display_name(hass: HomeAssistant, vacuum_entity: str) -> str:
    """The name users know the robot by, never a raw entity id when avoidable."""
    state = hass.states.get(vacuum_entity)
    friendly = state.attributes.get("friendly_name") if state is not None else None
    if friendly:
        return str(friendly)
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        entry = er.async_get(hass).async_get(vacuum_entity)
        if entry is not None:
            if entry.name or entry.original_name:
                return str(entry.name or entry.original_name)
            device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
            if device is not None and (device.name_by_user or device.name):
                return str(device.name_by_user or device.name)
    except Exception:  # noqa: BLE001 - naming must never break entity setup
        pass
    return vacuum_entity


def source_device(hass: HomeAssistant, device: dict[str, Any]):
    """Return the robot's authoritative real device, never a guessed identity."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    vacuum_entity = str(device["vacuum_entity"])
    registry_entity = er.async_get(hass).async_get(vacuum_entity)
    if registry_entity is None or registry_entity.platform == DOMAIN or not registry_entity.device_id:
        return None
    devices = dr.async_get(hass)
    try:
        return devices.async_get(registry_entity.device_id, include_composite_devices=False)
    except TypeError:  # HA 2025.1 has only real device entries.
        return devices.async_get(registry_entity.device_id)


def robot_device_info(hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> DeviceInfo | None:
    """Fallback device only; never register an upstream identity as our own."""
    if source_device(hass, device) is not None:
        return None
    vacuum_entity = str(device["vacuum_entity"])
    name = (device.get("name") or device.get("device_name") or device.get("label")
            or vacuum_display_name(hass, vacuum_entity))
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{vacuum_slug(device.get('_entity_origin') or vacuum_entity)}")},
        manufacturer=str(device.get("manufacturer") or MANUFACTURER),
        model=str(device.get("brand_profile") or MODEL),
        name=str(name),
    )


def sync_entity_device(hass: HomeAssistant, entry: ConfigEntry, entity: Entity, device: dict[str, Any]) -> None:
    """Move our registry entry to the actual source, preserving all user fields."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    entities = er.async_get(hass)
    matches = [item for item in er.async_entries_for_config_entry(entities, entry.entry_id)
               if item.platform == DOMAIN and item.unique_id == entity.unique_id]
    if len(matches) != 1:
        return
    current = matches[0]
    target = source_device(hass, device)
    if target is None:
        info = robot_device_info(hass, entry, device)
        target = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **info)
    elif not hasattr(target, "config_entry_id") and entry.entry_id not in target.config_entries:
        # HA 2025.1 uses shared config-entry ownership and removes foreign
        # entity entries on device updates unless the entry is registered.
        # Newer single-owner registries must not be asked to move the source.
        target = dr.async_get(hass).async_update_device(target.id, add_config_entry_id=entry.entry_id)
    if current.device_id != target.id:
        registry = dr.async_get(hass)
        previous = registry.async_get(current.device_id) if current.device_id else None
        entities.async_update_entity(current.entity_id, device_id=target.id)
        # Remove only an empty, uncustomized VWM fallback. Never delete a
        # source device, another integration's entry or user area/name/labels.
        if previous is not None and previous.identifiers and all(domain == DOMAIN for domain, _ in previous.identifiers):
            owner = getattr(previous, "config_entry_id", None)
            if owner is None and not hasattr(previous, "config_entry_id"):
                owners = getattr(previous, "config_entries", set())  # HA 2025.1
                owned = owners == {entry.entry_id}
            else:
                owned = owner == entry.entry_id
            if (owned and not previous.connections and not previous.name_by_user and not previous.area_id
                    and not getattr(previous, "labels", None) and not previous.disabled_by
                    and not er.async_entries_for_device(entities, previous.id, include_disabled_entities=True)):
                registry.async_remove_device(previous.id)


async def async_tracked_devices(hass: HomeAssistant) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Settings and the robots that get entities (no ghosts, no linked copies)."""
    from .tick import list_vacuums

    stored = await hass.data[DOMAIN][DATA_STORAGE].async_get_state()
    settings = stored.get("settings") or {}
    tank_states = stored.get("tank_states") or {}
    try:
        discovered = list_vacuums(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Unable to list vacuum entities: %s", err)
        discovered = []
    known = {str(item.get("entity_id")) for item in discovered if isinstance(item, dict) and item.get("entity_id")}
    devices = filter_active_devices(build_vacuum_devices(settings, tank_states, discovered), known, tank_states)
    origins = stored.get("entity_origins") or {}
    unavailable = set(stored.get("identity_unavailable_origins") or [])
    for device in devices:
        device["_entity_origin"] = origins.get(device.get("vacuum_entity"), device.get("vacuum_entity"))
    return settings, [device for device in devices if device.get("vacuum_entity") and device["_entity_origin"] not in unavailable]


def robot_tracks_water(hass: HomeAssistant, device: dict[str, Any], settings: dict[str, Any]) -> bool:
    """Whether a robot gets water settings entities (it mops, or has a tank size set)."""
    from .health import MOP_ATTRIBUTE_KEYS, tracks_water
    from .sensor_calculations import apply_custom_calibration, estimate_water_state
    from .storage import VacuumWaterStorage

    effective = apply_custom_calibration(device, settings)
    estimate = estimate_water_state(device, VacuumWaterStorage.default_tank_state(), settings)
    state = hass.states.get(str(device.get("vacuum_entity")))
    attributes = getattr(state, "attributes", None) or {}
    attribute = any(isinstance(effective.get(key), str) and effective.get(key) in attributes
                    for key in MOP_ATTRIBUTE_KEYS)
    return tracks_water(device, effective, estimate, attribute)


class RobotEntityManager:
    """Add a platform's entities for every robot, now and when robots appear."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: Callable,
        factory: Callable[[dict[str, Any], dict[str, Any]], list[Entity]],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.async_add_entities = async_add_entities
        self.factory = factory
        self._known: dict[str, str] = {}
        self._instances: dict[str, RobotEntity] = {}
        self._seen: set[str] = set()

    async def async_setup(self) -> None:
        self.entry.async_on_unload(async_dispatcher_connect(
            self.hass, signal_vacuum_water_updated(self.entry.entry_id), self._handle_update))
        await self.async_sync()

    @callback
    def _handle_update(self, payload: dict[str, Any] | None = None) -> None:
        # Ticks of robots that already have entities change nothing here.
        if isinstance(payload, dict) and not ({"settings", "registry_rename", "registry_changed"} & payload.keys()):
            if all(vacuum in self._seen for vacuum in payload.get("tank_states") or {}):
                return
        self.hass.async_create_task(self.async_sync())

    async def async_sync(self) -> None:
        settings, devices = await async_tracked_devices(self.hass)
        stored = await self.hass.data[DOMAIN][DATA_STORAGE].async_get_state()
        held = {item.get("entity_origin") for item in stored.get("registry_identity_conflicts") or []}
        held.update(stored.get("identity_unavailable_origins") or [])
        present = {str(device["vacuum_entity"]) for device in devices}
        self._seen = present
        # A robot that left (linked as a duplicate, removed) may come back later.
        by_origin = {str(device.get("_entity_origin") or device["vacuum_entity"]): str(device["vacuum_entity"])
                     for device in devices}
        for uid, entity in self._instances.items():
            origin = str(entity._device.get("_entity_origin") or entity.vacuum_entity)
            if origin in by_origin:
                self._known[uid] = by_origin[origin]
            active = origin in by_origin
            if entity._identity_active != active:
                entity._identity_active = active
                if entity.entity_id is not None:
                    entity.async_write_ha_state()
        self._known = {uid: vacuum for uid, vacuum in self._known.items() if vacuum in present
                       or str(self._instances[uid]._device.get("_entity_origin") or vacuum) in held}
        self._instances = {uid: entity for uid, entity in self._instances.items() if uid in self._known}
        new: list[Entity] = []
        desired: set[str] = set()
        for device in devices:
            for entity in self.factory(device, settings):
                desired.add(str(entity.unique_id))
                if entity.unique_id in self._known:
                    existing = self._instances.get(str(entity.unique_id))
                    if existing is not None:
                        existing.vacuum_entity = str(device["vacuum_entity"])
                        existing._device = dict(device)
                        sync_entity_device(self.hass, self.entry, existing, device)
                        existing._identity_active = True
                        existing._capability_active = True
                        self._known[str(entity.unique_id)] = existing.vacuum_entity
                        if existing.entity_id is not None:
                            self.hass.async_create_task(existing._async_refresh_and_write())
                    continue
                sync_entity_device(self.hass, self.entry, entity, device)
                self._known[str(entity.unique_id)] = str(device["vacuum_entity"])
                self._instances[str(entity.unique_id)] = entity
                new.append(entity)
        for uid, entity in self._instances.items():
            active = uid in desired
            if entity._capability_active != active:
                entity._capability_active = active
                if entity.entity_id is not None:
                    entity.async_write_ha_state()
        if new:
            self.async_add_entities(new)


class RobotEntity(Entity):
    """Base for a robot-bound entity that follows Store updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any], key: str) -> None:
        self.hass = hass
        self.entry = entry
        self.vacuum_entity = str(device["vacuum_entity"])
        self._device = dict(device)
        self._identity_active = True
        self._capability_active = True
        self._attr_unique_id = f"{entry.entry_id}_{vacuum_slug(device.get('_entity_origin') or self.vacuum_entity)}_{key}"
        self._attr_translation_key = key

    @property
    def device_info(self) -> DeviceInfo | None:
        return robot_device_info(self.hass, self.entry, self._device)

    @property
    def available(self) -> bool:
        return self._identity_active and self._capability_active and super().available

    def _require_active(self) -> None:
        if not self.available:
            from homeassistant.exceptions import ServiceValidationError
            raise ServiceValidationError("Robot capability is unavailable")

    async def _authorized_action(self, feature: str, action, *args):
        """Preserve HA's caller context and fence authorization at Store write."""
        from homeassistant.exceptions import Unauthorized
        from .feature_access import check_access, reset_write_guard, set_write_guard
        from .robots import resolve_balance_owner
        self._require_active()
        context = getattr(self, "_context", None)
        user_id = getattr(context, "user_id", None)
        stored = await self.hass.data[DOMAIN][DATA_STORAGE].async_get_state()
        owner = resolve_balance_owner(self.hass, stored, self.vacuum_entity)
        entities = {self.vacuum_entity, owner}
        if not await check_access(self.hass, user_id, feature, "execute", entities):
            raise Unauthorized()
        token = set_write_guard(user_id, feature, entities)
        try:
            return await action(*args)
        finally:
            reset_write_guard(token)

    async def async_added_to_hass(self) -> None:
        sync_entity_device(self.hass, self.entry, self, self._device)
        self.async_on_remove(async_dispatcher_connect(
            self.hass, signal_vacuum_water_updated(self.entry.entry_id), self._handle_store_update))
        await self.async_refresh_state()

    @callback
    def _handle_store_update(self, payload: dict[str, Any] | None = None) -> None:
        # Settings entities depend on settings and discovery, not on every tick.
        if isinstance(payload, dict) and not ({"settings", "registry_rename", "registry_changed"} & payload.keys()):
            return
        self.hass.async_create_task(self._async_refresh_and_write())

    async def _async_refresh_and_write(self) -> None:
        await self.async_refresh_state()
        self.async_write_ha_state()

    async def async_refresh_state(self) -> None:
        """Read the Store; subclasses set their attributes."""

    async def _report(self) -> dict[str, Any] | None:
        from .robots import async_reports

        for report in await async_reports(self.hass):
            if report.get("vacuum_entity") == self.vacuum_entity:
                return report
        return None
