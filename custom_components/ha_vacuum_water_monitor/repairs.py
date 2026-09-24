"""Repairs fix flows: each actionable health check is solved in one step."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .device_options import CAPACITY_MAX_ML, CAPACITY_MIN_ML, CAPACITY_STEP_ML
from .robots import async_mark_refilled, async_reports, async_set_link, async_set_options

DEFAULT_CAPACITY_ML = 3000


class _RobotFlow(RepairsFlow):
    """Base: the issue's data names the robot and the check."""

    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = dict(data or {})
        self._vacuum = str(self._data.get("vacuum_entity") or "")

    async def _report(self) -> dict[str, Any] | None:
        for report in await async_reports(self.hass):
            if report.get("vacuum_entity") == self._vacuum:
                return report
        return None

    async def _placeholders(self) -> dict[str, str]:
        report = await self._report() or {}
        return {
            "name": str(report.get("name") or self._vacuum),
            "target_name": str(self._data.get("target") or ""),
            "model_capacity": str(int(report["model_capacity_ml"])) if report.get("model_capacity_ml") else "",
        }


class ConfirmFullFlow(_RobotFlow):
    """The user confirms the clean-water tank is full now."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            try:
                await async_mark_refilled(self.hass, self._vacuum, "repair")
            except ValueError:
                return self.async_abort(reason="robot_missing")
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}),
                                    description_placeholders=await self._placeholders())


class CapacityFlow(_RobotFlow):
    """The user enters the tank size for a model the database does not know."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await async_set_options(self.hass, self._vacuum, {"capacity_ml": user_input["capacity_ml"]})
            except ValueError:
                errors["capacity_ml"] = "invalid_capacity"
            else:
                return self.async_create_entry(data={})
        report = await self._report() or {}
        default = report.get("capacity_ml") or report.get("model_capacity_ml") or DEFAULT_CAPACITY_ML
        schema = vol.Schema({vol.Required("capacity_ml", default=int(default)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=CAPACITY_MIN_ML, max=CAPACITY_MAX_ML, step=CAPACITY_STEP_ML,
                                          unit_of_measurement="mL", mode=selector.NumberSelectorMode.BOX))})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors,
                                    description_placeholders=await self._placeholders())


class DuplicateFlow(_RobotFlow):
    """The user says whether a bridged robot is the same as a native one."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        placeholders = await self._placeholders()
        target = str(self._data.get("target") or "")
        for report in await async_reports(self.hass):
            if report.get("vacuum_entity") == target:
                placeholders["target_name"] = str(report.get("name") or target)
        return self.async_show_menu(step_id="init", menu_options=["hide", "distinct"],
                                    description_placeholders=placeholders)

    async def async_step_hide(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        target = str(self._data.get("target") or "")
        try:
            await async_set_link(self.hass, self._vacuum, target)
        except ValueError:
            return self.async_abort(reason="robot_missing")
        return self.async_create_entry(data={})

    async def async_step_distinct(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        try:
            await async_set_link(self.hass, self._vacuum, "distinct")
        except ValueError:
            return self.async_abort(reason="robot_missing")
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    check = str((data or {}).get("check") or "")
    if check == "unknown_capacity":
        return CapacityFlow(data)
    if check == "possible_duplicate":
        return DuplicateFlow(data)
    return ConfirmFullFlow(data)
