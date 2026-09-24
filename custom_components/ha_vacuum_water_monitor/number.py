"""Tank size of each robot as a Home Assistant number entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .device_options import CAPACITY_MAX_ML, CAPACITY_MIN_ML, CAPACITY_STEP_ML
from .entity import RobotEntity, RobotEntityManager
from .robots import async_set_options


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    await RobotEntityManager(
        hass, entry, async_add_entities,
        lambda device, _settings: [TankCapacityNumber(hass, entry, device)],
    ).async_setup()


class TankCapacityNumber(RobotEntity, NumberEntity):
    """The usable clean-water tank size; setting it overrides the model database."""

    _attr_device_class = NumberDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS
    _attr_native_min_value = CAPACITY_MIN_ML
    _attr_native_max_value = CAPACITY_MAX_ML
    _attr_native_step = CAPACITY_STEP_ML
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cup-water"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> None:
        super().__init__(hass, entry, device, "tank_capacity")

    async def async_refresh_state(self) -> None:
        report = await self._report() or {}
        self._attr_native_value = report.get("capacity_ml")
        self._attr_extra_state_attributes = {
            "vacuum_entity": self.vacuum_entity,
            "source": report.get("capacity_source"),
            "model_capacity_ml": report.get("model_capacity_ml"),
        }

    async def async_set_native_value(self, value: float) -> None:
        try:
            await async_set_options(self.hass, self.vacuum_entity, {"capacity_ml": value})
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
