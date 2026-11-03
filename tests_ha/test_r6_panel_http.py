"""The panel deep-link and the original static card URL both work in HA."""
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant

from .test_ha_runtime import DOMAIN, _setup


async def test_direct_panel_link_and_existing_resource_url(hass: HomeAssistant, hass_client) -> None:
    await _setup(hass)
    client = await hass_client()
    panel = next(p for p in hass.data[frontend.DATA_PANELS].values()
                 if (p.config or {}).get("_panel_custom", {}).get("name") == "vwm-standalone-panel")
    response = await client.get(f"/{panel.frontend_url_path}?vacuum=vacuum.robot")
    assert response.status == 200
    assert "text/html" in response.headers.get("Content-Type", "")
    response = await client.get(f"/{DOMAIN}/ha-vacuum-water-monitor.js")
    assert response.status == 200
    assert "ha-vacuum-water-monitor" in await response.text()
