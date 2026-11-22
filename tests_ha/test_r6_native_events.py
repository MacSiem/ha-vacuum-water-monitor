"""R6 event projection matches the readable retained tank state."""
import asyncio

from homeassistant.core import HomeAssistant

from .test_ha_runtime import DOMAIN, VACUUM, _setup


async def test_settings_event_authorizes_readable_retained_tank(hass: HomeAssistant, hass_ws_client) -> None:
    storage = await _setup(hass)
    retained = "vacuum.retired_but_readable"
    await storage.async_set_tank_state(retained, {"initialized": True, "used_ml": 123})
    listener = await hass_ws_client(hass)
    sender = await hass_ws_client(hass)
    await listener.send_json({"id": 11, "type": f"{DOMAIN}/subscribe"})
    assert (await listener.receive_json())["success"]
    await sender.send_json({"id": 12, "type": f"{DOMAIN}/get_state"})
    state = await sender.receive_json()
    assert state["success"] and retained in state["result"]["tank_states"]
    await sender.send_json({"id": 13, "type": f"{DOMAIN}/list_vacuums"})
    listed = await sender.receive_json()
    assert listed["success"] and retained not in {item["entity_id"] for item in listed["result"]["vacuums"]}
    await sender.send_json({"id": 14, "type": f"{DOMAIN}/set_settings", "patch": {"sharing_intro_choice": "not_now"}})
    result = await sender.receive_json()
    assert result["success"]
    async with asyncio.timeout(3):
        while True:
            event = await listener.receive_json()
            if event.get("event", {}).get("data", {}).get("settings_changed"):
                break
    assert event["event"]["data"]["settings_changed"] is True
    assert {VACUUM, retained} <= set(event["event"]["data"]["authorized_vacuums"])
    assert "tank_states" not in event["event"]["data"]
