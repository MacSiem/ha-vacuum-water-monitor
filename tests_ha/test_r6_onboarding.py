"""R6 setup uses known defaults without asking the user to re-enter them."""
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_vacuum_water_monitor.const import (
    CONF_CRITICAL_THRESHOLD, CONF_WARNING_THRESHOLD,
    DEFAULT_CRITICAL_THRESHOLD, DEFAULT_WARNING_THRESHOLD, DOMAIN,
)


async def test_user_setup_creates_entry_with_known_defaults(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options[CONF_WARNING_THRESHOLD] == DEFAULT_WARNING_THRESHOLD
    assert entry.options[CONF_CRITICAL_THRESHOLD] == DEFAULT_CRITICAL_THRESHOLD
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert duplicate["type"] == FlowResultType.ABORT
