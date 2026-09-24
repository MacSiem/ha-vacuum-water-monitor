"""The Refilled action as a Home Assistant button (dashboards, NFC tags, automations)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .entity import RobotEntity, RobotEntityManager, robot_tracks_water
from .robots import async_mark_empty, async_mark_refilled


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    await RobotEntityManager(
        hass, entry, async_add_entities,
        lambda device, settings: [RefilledButton(hass, entry, device), TankEmptyButton(hass, entry, device)]
        if robot_tracks_water(hass, device, settings) else [],
    ).async_setup()


class RefilledButton(RobotEntity, ButtonEntity):
    """Press after filling the clean-water tank (a second press within 10 minutes is ignored)."""

    _attr_icon = "mdi:water-plus"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> None:
        super().__init__(hass, entry, device, "refilled")

    async def async_press(self) -> None:
        try:
            await async_mark_refilled(self.hass, self.vacuum_entity, "entity")
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err


class TankEmptyButton(RobotEntity, ButtonEntity):
    """Press when the robot ran out of water: the estimate learns from it like from a dock signal."""

    _attr_icon = "mdi:water-off"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: dict[str, Any]) -> None:
        super().__init__(hass, entry, device, "tank_empty")

    async def async_press(self) -> None:
        try:
            await async_mark_empty(self.hass, self.vacuum_entity)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
