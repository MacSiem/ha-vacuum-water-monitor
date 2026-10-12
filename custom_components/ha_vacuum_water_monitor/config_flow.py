"""Config flow for Vacuum Water Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    CONF_CRITICAL_THRESHOLD,
    CONF_WARNING_THRESHOLD,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
)

from .storage import validate_threshold_settings


class HAVacuumWaterMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Single-instance setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle initial setup."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = {}
        if user_input is not None:
            try:
                validate_threshold_settings(user_input)
            except (ValueError, KeyError):
                errors["base"] = "invalid_input"
            else:
                return self.async_create_entry(
                    title="Vacuum Water Monitor",
                    data={},
                    options={key: user_input[key] for key in (CONF_WARNING_THRESHOLD, CONF_CRITICAL_THRESHOLD)},
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=_threshold_schema(
                DEFAULT_WARNING_THRESHOLD,
                DEFAULT_CRITICAL_THRESHOLD,
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return HAVacuumWaterMonitorOptionsFlow(config_entry)


class HAVacuumWaterMonitorOptionsFlow(config_entries.OptionsFlow):
    """Options flow for refill threshold defaults."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        errors = {}
        if user_input is not None:
            try:
                validate_threshold_settings(user_input)
            except (ValueError, KeyError):
                errors["base"] = "invalid_input"
            else:
                return self.async_create_entry(title="", data={**self._config_entry.options, **user_input})

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=_threshold_schema(
                options.get(CONF_WARNING_THRESHOLD, DEFAULT_WARNING_THRESHOLD),
                options.get(CONF_CRITICAL_THRESHOLD, DEFAULT_CRITICAL_THRESHOLD),
            ),
        )


def _threshold_schema(warning: int, critical: int) -> vol.Schema:
    """Build threshold schema."""
    return vol.Schema(
        {
            vol.Required(CONF_WARNING_THRESHOLD, default=warning): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=99)
            ),
            vol.Required(CONF_CRITICAL_THRESHOLD, default=critical): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=99)
            ),
        }
    )
