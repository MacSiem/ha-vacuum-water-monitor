"""Sensor entities for Vacuum Water Monitor."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.event import async_track_time_change

from .const import (
    DATA_STORAGE,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    signal_vacuum_water_updated,
)
from .sensor_calculations import (
    build_vacuum_devices,
    estimate_water_state,
    next_maintenance_due,
    parse_refill_datetime,
    vacuum_slug,
)
from .storage import VacuumWaterStorage
from .tick import list_vacuums

_LOGGER = logging.getLogger(__name__)

WATER_VOLUME_UNIT = "mL"
DAYS_UNIT = "d"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Store-backed vacuum sensors."""
    manager = VacuumSensorManager(hass, entry, async_add_entities)
    await manager.async_setup()


class VacuumSensorManager:
    """Create sensors for vacuums discovered from Store-backed state."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, async_add_entities
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.async_add_entities = async_add_entities
        self._known: set[tuple[str, str]] = set()

    async def async_setup(self) -> None:
        """Subscribe to Store updates and add initial entities."""
        self.entry.async_on_unload(
            async_dispatcher_connect(
                self.hass,
                signal_vacuum_water_updated(self.entry.entry_id),
                self._handle_store_update,
            )
        )
        await self.async_sync_devices()

    @callback
    def _handle_store_update(self, _payload: dict[str, Any] | None = None) -> None:
        self.hass.async_create_task(self.async_sync_devices())

    async def async_sync_devices(self) -> None:
        """Add sensor entities for any newly known vacuum."""
        storage = _storage(self.hass)
        stored = await storage.async_get_state()
        settings = stored.get("settings") or {}
        tank_states = stored.get("tank_states") or {}
        try:
            discovered = list_vacuums(self.hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Unable to list vacuum entities for sensors: %s", err)
            discovered = []

        entities: list[VacuumStoreSensor] = []
        for device in build_vacuum_devices(settings, tank_states, discovered):
            vacuum_entity = device.get("vacuum_entity")
            if not vacuum_entity:
                continue
            for sensor_cls in (
                WaterRemainingSensor,
                WaterUsedSensor,
                LastRefillSensor,
                NextMaintenanceDueSensor,
            ):
                sensor_id = (str(vacuum_entity), sensor_cls.sensor_key)
                if sensor_id in self._known:
                    continue
                self._known.add(sensor_id)
                entities.append(sensor_cls(self.hass, self.entry, device))

        if entities:
            self.async_add_entities(entities, True)


class VacuumStoreSensor(SensorEntity):
    """Base class for a vacuum-bound Store-backed sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    sensor_key = ""
    sensor_name = ""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.vacuum_entity = str(device["vacuum_entity"])
        self.vacuum_slug = vacuum_slug(self.vacuum_entity)
        self._device = dict(device)
        self._fallback_device = dict(device)
        self._attr_unique_id = f"{entry.entry_id}_{self.vacuum_slug}_{self.sensor_key}"
        self._attr_name = self.sensor_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return a per-vacuum device."""
        name = (
            self._device.get("name")
            or self._device.get("device_name")
            or self._device.get("label")
            or self.vacuum_entity
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{self.vacuum_slug}")},
            manufacturer=str(self._device.get("manufacturer") or MANUFACTURER),
            model=str(self._device.get("brand_profile") or MODEL),
            name=str(name),
        )

    @property
    def _storage(self) -> VacuumWaterStorage:
        return _storage(self.hass)

    async def async_added_to_hass(self) -> None:
        """Subscribe to Store writes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_vacuum_water_updated(self.entry.entry_id),
                self._handle_store_update,
            )
        )
        await self.async_refresh()

    @callback
    def _handle_store_update(self, _payload: dict[str, Any] | None = None) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def async_refresh(self) -> None:
        """Refresh from Store and write state."""
        await self.async_update()
        self.async_write_ha_state()

    async def _store_context(self) -> tuple[dict[str, Any], dict[str, Any]]:
        stored = await self._storage.async_get_state()
        settings = stored.get("settings") or {}
        tank_states = stored.get("tank_states") or {}
        for device in build_vacuum_devices(settings, tank_states):
            if device.get("vacuum_entity") == self.vacuum_entity:
                self._device = {**self._fallback_device, **device}
                break
        else:
            self._device = dict(self._fallback_device)

        tank_state = VacuumWaterStorage.default_tank_state()
        stored_tank = tank_states.get(self.vacuum_entity)
        if isinstance(stored_tank, dict):
            tank_state.update(stored_tank)
        return settings, tank_state


class WaterRemainingSensor(VacuumStoreSensor):
    """Estimated water remaining percentage."""

    sensor_key = "water_remaining"
    sensor_name = "Water remaining"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    async def async_update(self) -> None:
        """Update water remaining from Store."""
        settings, tank_state = await self._store_context()
        estimate = estimate_water_state(self._device, tank_state, settings)
        self._attr_native_value = estimate["remaining_percent"]
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "source": estimate["source"],
            "total_ml": estimate["total_ml"],
            "used_ml": estimate["used_ml"],
            "remaining_ml": estimate["remaining_ml"],
            "last_refill": tank_state.get("last_reset_iso"),
            "warning_threshold": settings.get("warning_threshold"),
            "critical_threshold": settings.get("critical_threshold"),
        }


class WaterUsedSensor(VacuumStoreSensor):
    """Water used since the last refill."""

    sensor_key = "water_used_since_refill"
    sensor_name = "Water used since refill"
    _attr_native_unit_of_measurement = WATER_VOLUME_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT

    async def async_update(self) -> None:
        """Update used water from Store."""
        settings, tank_state = await self._store_context()
        estimate = estimate_water_state(self._device, tank_state, settings)
        self._attr_native_value = estimate["used_ml"]
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "source": estimate["source"],
            "total_ml": estimate["total_ml"],
            "remaining_ml": estimate["remaining_ml"],
            "remaining_percent": estimate["remaining_percent"],
            "last_refill": tank_state.get("last_reset_iso"),
        }


class LastRefillSensor(VacuumStoreSensor):
    """Timestamp of the last water refill reset."""

    sensor_key = "last_refill"
    sensor_name = "Last refill"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_update(self) -> None:
        """Update last refill timestamp from Store."""
        _settings, tank_state = await self._store_context()
        self._attr_native_value = parse_refill_datetime(tank_state)
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "last_reset_iso": tank_state.get("last_reset_iso"),
            "last_reset_ts": tank_state.get("last_reset_ts"),
        }


class NextMaintenanceDueSensor(VacuumStoreSensor):
    """Days until the next custom maintenance item is due."""

    sensor_key = "next_maintenance_due"
    sensor_name = "Next maintenance due"
    _attr_native_unit_of_measurement = DAYS_UNIT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        """Subscribe to Store writes and midnight rollover."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def async_update(self) -> None:
        """Update next maintenance due from Store."""
        settings, _tank_state = await self._store_context()
        due = next_maintenance_due(settings.get("maintenance_items"))
        if due is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {
                "vacuum_entity": self.vacuum_entity,
                "next_item": None,
                "scheduled_items": 0,
            }
            return

        self._attr_native_value = due["days_left"]
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "next_item": due["name"],
            "icon": due.get("icon"),
            "overdue": due["overdue"],
            "days_overdue": due["days_overdue"],
            "days_since": due["days_since"],
            "interval_days": due["interval_days"],
            "last_done_at": due["last_done_at"],
            "due_at": due["due_at"],
        }


def _storage(hass: HomeAssistant) -> VacuumWaterStorage:
    return hass.data[DOMAIN][DATA_STORAGE]
