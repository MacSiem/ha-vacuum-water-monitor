"""The integration inside a real Home Assistant core (5.7.0-beta.2).

Covers what the pure-python suite cannot: config entry setup, the
``mark_refilled`` service, entity-change driven ticks, the refill settings
websocket command, and a Roborock-shaped registry discovered like on a real
install.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "ha_vacuum_water_monitor"
VACUUM = "vacuum.robot"
SIGNALS = (
    ("sensor", "status", "robot_status"),
    ("sensor", "cleaning_area", "robot_cleaning_area"),
    ("select", "mop_mode", "robot_mop_mode"),
    ("select", "mop_intensity", "robot_mop_intensity"),
    ("sensor", "dock_error", "robot_dock_error"),
    ("binary_sensor", "mop_attached", "robot_mop_attached"),
)


def _robot_states(hass: HomeAssistant, *, status="charging", vacuum="docked", area="0", dock_error="ok") -> None:
    hass.states.async_set(VACUUM, vacuum, {"status": status, "friendly_name": "Robot"})
    hass.states.async_set("sensor.robot_status", status)
    hass.states.async_set("sensor.robot_cleaning_area", area, {"unit_of_measurement": "m²"})
    hass.states.async_set("select.robot_mop_mode", "standard")
    hass.states.async_set("select.robot_mop_intensity", "standard")
    hass.states.async_set("sensor.robot_dock_error", dock_error)
    hass.states.async_set("binary_sensor.robot_mop_attached", "on")


async def _setup(hass: HomeAssistant):
    roborock = MockConfigEntry(domain="roborock", title="Roborock")
    roborock.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=roborock.entry_id,
        identifiers={("roborock", "robot-1")},
        manufacturer="Roborock",
        model="roborock.vacuum.a97",
        model_id="a97",
        name="Robot",
    )
    entities = er.async_get(hass)
    entities.async_get_or_create("vacuum", "roborock", "robot-1", device_id=device.id,
                                 suggested_object_id="robot", config_entry=roborock)
    for domain, key, object_id in SIGNALS:
        entities.async_get_or_create(domain, "roborock", object_id, device_id=device.id,
                                     suggested_object_id=object_id, translation_key=key, config_entry=roborock)
    _robot_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Vacuum Water Monitor", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN]["storage"]


async def _settle(hass: HomeAssistant, seconds: float = 3) -> None:
    await hass.async_block_till_done()  # state_changed listeners schedule the debounce timer
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _tank(storage):
    return (await storage.async_get_state())["tank_states"].get(VACUUM, {})


async def test_setup_discovers_the_roborock_and_registers_the_service(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert hass.services.has_service(DOMAIN, "mark_refilled")
    ticker = hass.data[DOMAIN]["ticker"]
    assert {"sensor.robot_status", "sensor.robot_cleaning_area", "sensor.robot_dock_error", VACUUM} <= ticker.entities


async def test_mark_refilled_service_resets_the_tank(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 2500, "initialized": True})
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True)
    tank = await _tank(storage)
    assert tank["used_ml"] == 0
    assert tank["last_reset_source"] == "service"
    assert tank["refill_history"][0]["used_before_ml"] == 2500


async def test_service_rejects_non_vacuum_targets(hass: HomeAssistant) -> None:
    await _setup(hass)
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": "sensor.robot_status"}, blocking=True)


async def test_a_state_change_ticks_without_waiting_for_the_heartbeat(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True)
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="0")
    await _settle(hass)
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="5")
    await _settle(hass)
    tank = await _tank(storage)
    assert tank["used_ml"] == pytest.approx(30.0)  # 5 m² standard route, standard level, S8 owner estimate
    _robot_states(hass, status="going_to_wash_the_mop", vacuum="returning", area="7")
    await _settle(hass)
    tank = await _tank(storage)
    assert tank["used_ml"] == pytest.approx(30.0 + 12.0 + 150.0)


async def test_refill_settings_bind_a_button_immediately(hass: HomeAssistant, hass_ws_client) -> None:
    storage = await _setup(hass)
    hass.states.async_set("input_button.dock_refilled", "2026-09-01T10:00:00+00:00")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_refill_settings", "vacuum_entity": VACUUM,
                                    "auto_refill": False, "button_entity": "input_button.dock_refilled"})
    response = await client.receive_json()
    assert response["success"], response
    assert response["result"]["settings"]["refill_settings"][VACUUM] == {
        "auto_refill": False, "button_entity": "input_button.dock_refilled"}
    await hass.async_block_till_done()
    assert "input_button.dock_refilled" in hass.data[DOMAIN]["ticker"].entities
    await storage.async_set_tank_state(VACUUM, {"used_ml": 1800, "initialized": True,
                                                "last_refill_button_state": "2026-09-01T10:00:00+00:00",
                                                "last_refill_button_entity": "input_button.dock_refilled"})
    hass.states.async_set("input_button.dock_refilled", "2026-09-16T07:30:00+00:00")
    await _settle(hass)
    tank = await _tank(storage)
    assert tank["used_ml"] == 0
    assert tank["last_reset_source"] == "button"


async def test_a_button_refill_is_written_to_disk_at_once(hass: HomeAssistant, hass_ws_client, hass_storage) -> None:
    storage = await _setup(hass)
    hass.states.async_set("input_button.dock_refilled", "2026-09-01T10:00:00+00:00")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_refill_settings", "vacuum_entity": VACUUM,
                                    "button_entity": "input_button.dock_refilled"})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    await storage.async_set_tank_state(VACUUM, {"used_ml": 1800, "initialized": True,
                                                "last_refill_button_state": "2026-09-01T10:00:00+00:00",
                                                "last_refill_button_entity": "input_button.dock_refilled"})
    hass.states.async_set("input_button.dock_refilled", "2026-09-16T07:30:00+00:00")
    await _settle(hass)
    stored = hass_storage[DOMAIN]["data"]["tank_states"][VACUUM]
    assert stored["used_ml"] == 0
    assert stored["last_reset_source"] == "button"


async def test_invalid_refill_binding_is_rejected(hass: HomeAssistant, hass_ws_client) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_refill_settings", "vacuum_entity": VACUUM,
                                    "lid_entity": "light.kitchen"})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "invalid_payload"


async def test_event_ticks_coalesce_writes_and_flush_on_shutdown(hass: HomeAssistant, hass_storage) -> None:
    from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE

    await _setup(hass)
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True)
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="0")
    await _settle(hass)
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="10")
    await _settle(hass)
    assert hass_storage[DOMAIN]["data"]["tank_states"][VACUUM]["used_ml"] == 0, "event ticks do not write every change"
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    assert hass_storage[DOMAIN]["data"]["tank_states"][VACUUM]["used_ml"] == pytest.approx(60.0)


async def test_unload_removes_the_service_and_listeners(hass: HomeAssistant) -> None:
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "mark_refilled")


async def test_state_changed_event_carries_the_balance_not_the_history(hass: HomeAssistant) -> None:
    """5.7.0-beta.4: events over 32 KB are dropped by the recorder and bloat the database."""
    storage = await _setup(hass)
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True)
    sessions = [{"ts": i, "started_ts": i, "water": 10, "context": {"pad": "x" * 400}} for i in range(50)]
    await storage.async_set_tank_state(VACUUM, {**(await _tank(storage)), "automatic_sessions": sessions})
    events = []
    hass.bus.async_listen(f"{DOMAIN}_state_changed", lambda event: events.append(event))
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="0")
    await _settle(hass)
    _robot_states(hass, status="cleaning", vacuum="cleaning", area="5")
    await _settle(hass)
    assert events
    import json

    for event in events:
        tank = event.data["tank_states"][VACUUM]
        assert "automatic_sessions" not in tank and "used_ml" in tank
        assert event.data.get("partial") is True
        assert len(json.dumps(event.data, default=str)) < 16_384
    assert len((await _tank(storage))["automatic_sessions"]) >= 50


async def test_a_device_named_after_the_entity_id_is_renamed(hass: HomeAssistant) -> None:
    await _setup(hass)
    registry = dr.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = next(d for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
                  if (DOMAIN, f"{entry.entry_id}_vacuum_robot") in d.identifiers)
    assert device is not None
    registry.async_update_device(device.id, name=VACUUM)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(device.id).name == "Robot"
    registry.async_update_device(device.id, name_by_user="Kitchen robot", name=VACUUM)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    # The user's own name is never overwritten (Home Assistant shows name_by_user
    # first; since 5.8.0 the settings entities also refresh the default name).
    assert registry.async_get(device.id).name_by_user == "Kitchen robot"
    assert registry.async_get(device.id).name in {VACUUM, "Robot"}


async def test_matter_duplicate_is_suggested_and_hidden_only_after_confirmation(hass: HomeAssistant, hass_ws_client) -> None:
    """5.7.0-beta.7: a robot shared over Matter and added natively."""
    matter = MockConfigEntry(domain="matter", title="Matter")
    matter.add_to_hass(hass)
    bridged = dr.async_get(hass).async_get_or_create(
        config_entry_id=matter.entry_id, identifiers={("matter", "node-7")},
        manufacturer="Roborock", model="Robotic Vacuum Cleaner", name="Robotic Vacuum Cleaner")
    er.async_get(hass).async_get_or_create("vacuum", "matter", "node-7", device_id=bridged.id,
                                           suggested_object_id="robotic_vacuum_cleaner", config_entry=matter)
    hass.states.async_set("vacuum.robotic_vacuum_cleaner", "docked", {"friendly_name": "Robotic Vacuum Cleaner"})
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    registry = dr.async_get(hass)

    def ours():
        return {i[1] for d in dr.async_entries_for_config_entry(registry, entry.entry_id) for i in d.identifiers}

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/list_vacuums"})
    listed = {v["entity_id"]: v for v in (await client.receive_json())["result"]["vacuums"]}
    assert listed["vacuum.robotic_vacuum_cleaner"]["possible_duplicate_of"] == VACUUM
    assert f"{entry.entry_id}_vacuum_robotic_vacuum_cleaner" in ours()  # nothing hidden without the user

    await client.send_json({"id": 2, "type": f"{DOMAIN}/set_settings",
                            "patch": {"robot_links": {"vacuum.robotic_vacuum_cleaner": VACUUM}}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert f"{entry.entry_id}_vacuum_robotic_vacuum_cleaner" not in ours()
    assert f"{entry.entry_id}_vacuum_robot" in ours()
    storage = hass.data[DOMAIN]["storage"]
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": "vacuum.robotic_vacuum_cleaner"}, blocking=True)
    tanks = (await storage.async_get_state())["tank_states"]
    assert tanks[VACUUM]["last_reset_source"] == "service"  # the owner is refilled, not the hidden copy
    assert tanks.get("vacuum.robotic_vacuum_cleaner", {}).get("last_reset_source") != "service"

    await client.send_json({"id": 3, "type": f"{DOMAIN}/set_settings",
                            "patch": {"robot_links": {"vacuum.robotic_vacuum_cleaner": "distinct"}}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert f"{entry.entry_id}_vacuum_robotic_vacuum_cleaner" in ours()
