"""Automatic refill from the dock as a Home Assistant switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .entity import RobotEntity, RobotEntityManager
from .health import supports_auto_refill
from .robots import async_set_auto_refill
from .sensor_calculations import apply_custom_calibration


def _entities(hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any], settings: dict[str, Any]) -> list:
    # Only a dock that reports its clean tank empty and refilled can refill automatically.
    if not supports_auto_refill(apply_custom_calibration(device, settings)):
        return []
    return [AutoRefillSwitch(hass, entry, device)]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    await RobotEntityManager(
        hass, entry, async_add_entities,
        lambda device, settings: _entities(hass, entry, device, settings),
    ).async_setup()


class AutoRefillSwitch(RobotEntity, SwitchEntity):
    """On: the tank counts as full when the dock's empty-water error clears."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:water-sync"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> None:
        super().__init__(hass, entry, device, "auto_refill")

    async def async_refresh_state(self) -> None:
        report = await self._report() or {}
        self._attr_is_on = bool(report.get("auto_refill"))
        self._attr_available = bool(report.get("auto_refill_supported", True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_set_auto_refill(self.hass, self.vacuum_entity, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_set_auto_refill(self.hass, self.vacuum_entity, False)
