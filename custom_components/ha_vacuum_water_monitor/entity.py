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


def robot_device_info(hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> DeviceInfo:
    """The one Home Assistant device that groups a robot's water entities."""
    vacuum_entity = str(device["vacuum_entity"])
    name = (device.get("name") or device.get("device_name") or device.get("label")
            or vacuum_display_name(hass, vacuum_entity))
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{vacuum_slug(vacuum_entity)}")},
        manufacturer=str(device.get("manufacturer") or MANUFACTURER),
        model=str(device.get("brand_profile") or MODEL),
        name=str(name),
    )


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
    return settings, [device for device in devices if device.get("vacuum_entity")]


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
        self._seen: set[str] = set()

    async def async_setup(self) -> None:
        self.entry.async_on_unload(async_dispatcher_connect(
            self.hass, signal_vacuum_water_updated(self.entry.entry_id), self._handle_update))
        await self.async_sync()

    @callback
    def _handle_update(self, payload: dict[str, Any] | None = None) -> None:
        # Ticks of robots that already have entities change nothing here.
        if isinstance(payload, dict) and "settings" not in payload:
            if all(vacuum in self._seen for vacuum in payload.get("tank_states") or {}):
                return
        self.hass.async_create_task(self.async_sync())

    async def async_sync(self) -> None:
        settings, devices = await async_tracked_devices(self.hass)
        present = {str(device["vacuum_entity"]) for device in devices}
        self._seen = present
        # A robot that left (linked as a duplicate, removed) may come back later.
        self._known = {uid: vacuum for uid, vacuum in self._known.items() if vacuum in present}
        new: list[Entity] = []
        for device in devices:
            for entity in self.factory(device, settings):
                if entity.unique_id in self._known:
                    continue
                self._known[str(entity.unique_id)] = str(device["vacuum_entity"])
                new.append(entity)
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
        self._attr_unique_id = f"{entry.entry_id}_{vacuum_slug(self.vacuum_entity)}_{key}"
        self._attr_translation_key = key

    @property
    def device_info(self) -> DeviceInfo:
        return robot_device_info(self.hass, self.entry, self._device)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, signal_vacuum_water_updated(self.entry.entry_id), self._handle_store_update))
        await self.async_refresh_state()

    @callback
    def _handle_store_update(self, payload: dict[str, Any] | None = None) -> None:
        # Settings entities depend on settings and discovery, not on every tick.
        if isinstance(payload, dict) and "settings" not in payload:
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
