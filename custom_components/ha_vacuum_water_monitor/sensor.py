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
    signal_vacuum_water_updated,
)
from .sensor_calculations import (
    PLACEHOLDER_ROBOT_NAMES,
    build_vacuum_devices,
    estimate_water_state,
    filter_active_devices,
    next_maintenance_due,
    parse_refill_datetime,
    setup_guidance,
    vacuum_slug,
)
from .entity import robot_device_info, vacuum_display_name
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

        known_entities = {
            str(item.get("entity_id"))
            for item in discovered
            if isinstance(item, dict) and item.get("entity_id")
        }
        devices = filter_active_devices(
            build_vacuum_devices(settings, tank_states, discovered),
            known_entities,
            tank_states,
        )

        entities: list[VacuumStoreSensor] = []
        for device in devices:
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
        self._rename_raw_id_devices(devices)
        self._remove_linked_duplicates(settings, devices)

    def _remove_linked_duplicates(self, settings: dict[str, Any], devices: list[dict[str, Any]]) -> None:
        """Drop the device (and its sensors) of an entity the user linked to another robot."""
        links = settings.get("robot_links") if isinstance(settings.get("robot_links"), dict) else {}
        tracked = {str(device.get("vacuum_entity")) for device in devices}
        # The robot the engine tracks keeps its device even when a link points
        # away from it (a stale or circular link must never remove live sensors).
        linked = {str(entity) for entity, target in links.items()
                  if target and target != "distinct" and str(entity) not in tracked}
        if not linked:
            return
        try:
            from homeassistant.helpers import device_registry as dr

            registry = dr.async_get(self.hass)
        except Exception:  # noqa: BLE001
            return
        wanted = {(DOMAIN, f"{self.entry.entry_id}_{vacuum_slug(entity)}"): entity for entity in linked}
        for device_entry in list(dr.async_entries_for_config_entry(registry, self.entry.entry_id)):
            match = next((wanted[i] for i in device_entry.identifiers if i in wanted), None)
            if match is None:
                continue
            registry.async_remove_device(device_entry.id)
            for sensor_cls in (WaterRemainingSensor, WaterUsedSensor, LastRefillSensor, NextMaintenanceDueSensor):
                self._known.discard((match, sensor_cls.sensor_key))

    def _rename_raw_id_devices(self, devices: list[dict[str, Any]]) -> None:
        """Replace a device name that is only the vacuum's entity id.

        Before 5.7.0-beta.4 a vacuum whose state was not loaded at start-up got a
        device named after its entity id, so its sensors read "vacuum.x Water
        remaining". A name the user set is never touched.
        """
        try:
            from homeassistant.helpers import device_registry as dr

            registry = dr.async_get(self.hass)
        except Exception:  # noqa: BLE001 - naming must never break sensor setup
            return
        # async_get_device(identifiers=...) is deprecated (HA 2026.9); the
        # entries of this config entry are the only candidates anyway.
        ours = {identifier: device_entry
                for device_entry in dr.async_entries_for_config_entry(registry, self.entry.entry_id)
                for identifier in device_entry.identifiers}
        for device in devices:
            vacuum_entity = str(device.get("vacuum_entity") or "")
            if not vacuum_entity:
                continue
            entry = ours.get((DOMAIN, f"{self.entry.entry_id}_{vacuum_slug(vacuum_entity)}"))
            if entry is None or entry.name_by_user or (entry.name != vacuum_entity
                                                          and entry.name not in PLACEHOLDER_ROBOT_NAMES):
                continue
            name = (device.get("name") if device.get("name") not in {vacuum_entity, *PLACEHOLDER_ROBOT_NAMES}
                    else None) or _vacuum_display_name(
                self.hass, vacuum_entity)
            if name and name != vacuum_entity:
                registry.async_update_device(entry.id, name=name)


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
        """Return a per-vacuum device (shared with the settings entities)."""
        return robot_device_info(self.hass, self.entry, self._device)

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
            **_water_state_attributes(estimate, tank_state),
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
            **_water_state_attributes(estimate, tank_state),
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
        refill_at = parse_refill_datetime(tank_state)
        self._attr_native_value = refill_at
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "last_reset_iso": tank_state.get("last_reset_iso"),
            "last_reset_ts": tank_state.get("last_reset_ts"),
            "refill_source": tank_state.get("last_reset_source"),
            "recent_refills": list(tank_state.get("refill_history") or [])[:5],
            **setup_guidance(None if refill_at else "awaiting_refill"),
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
                **setup_guidance("maintenance_not_configured"),
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


_vacuum_display_name = vacuum_display_name


def _water_state_attributes(
    estimate: dict[str, Any], tank_state: dict[str, Any]
) -> dict[str, Any]:
    """Expose initialization, profile and last-accounting diagnostics."""
    return {
        "initialized": estimate["initialized"],
        "state_reason": estimate["state_reason"],
        "capability": estimate["capability"],
        "profile_key": estimate["profile_key"],
        "profile_source": estimate["profile_source"],
        "profile_confidence": estimate["profile_confidence"],
        "integration_adapter": estimate.get("integration_adapter"),
        "signal_contract_version": estimate.get("signal_contract_version"),
        "mop_evidence_required": estimate.get("mop_evidence_required", False),
        "accounting_evidence": estimate["accounting_evidence"],
        "uncertainty_percent": estimate.get("uncertainty_percent"),
        "calibration_factor": estimate.get("calibration_factor"),
        "calibration_samples": estimate.get("calibration_samples"),
        "water_empty_active": bool(tank_state.get("water_empty_active")),
        "water_empty_acknowledged": bool(tank_state.get("water_empty_acknowledged")),
        "calibration_pending": tank_state.get("calibration_pending_log_factor") is not None,
        "intensity_unmapped": tank_state.get("intensity_unmapped"),
        "bridged_gaps": tank_state.get("bridged_gaps") or 0,
        **setup_guidance(estimate.get("state_reason")),
        "water_anchor_source": tank_state.get("water_anchor_source"),
        "water_anchor_kind": tank_state.get("water_anchor_kind"),
        "water_anchor_confidence": tank_state.get("water_anchor_confidence"),
        "last_low_water_ts": tank_state.get("last_low_water_ts"),
        "last_calibration_predicted_ml": tank_state.get(
            "last_calibration_predicted_ml"
        ),
        "last_calibration_target_ml": tank_state.get(
            "last_calibration_target_ml"
        ),
        "consumption_resolution": tank_state.get("consumption_resolution"),
        "reservoir_levels": tank_state.get("reservoir_levels"),
        "accounting_v2": {k: v for k, v in (tank_state.get("accounting_v2") or {}).items() if k not in {"journal", "events", "device_identity"}},
        "accounting_incomplete": bool(tank_state.get("accounting_incomplete")),
        "last_accounting_source": tank_state.get("last_accounting_source"),
        "last_accounting_rate_ml": tank_state.get("last_accounting_rate_ml"),
        "last_accounting_reason": tank_state.get("last_accounting_reason"),
    }
