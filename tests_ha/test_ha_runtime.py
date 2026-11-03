"""The integration inside a real Home Assistant core (5.7.0-beta.2).

Covers what the pure-python suite cannot: config entry setup, the
``mark_refilled`` service, entity-change driven ticks, the refill settings
websocket command, and a Roborock-shaped registry discovered like on a real
install.
"""

from __future__ import annotations

from datetime import timedelta
import time

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
    assert tank["used_ml"] == pytest.approx(30.0 + 12.0)
    _robot_states(hass, status="washing_the_mop", vacuum="docked", area="7")
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


@pytest.mark.parametrize("target,incomplete", [("linked", False), ("linked", True), ("primary", True), ("distinct", False)])
async def test_card_refill_uses_confirmed_balance_owner(hass: HomeAssistant, hass_ws_client, target, incomplete):
    """Card WS must refill the same owner as mark_refilled without merging banks."""
    matter = MockConfigEntry(domain="matter", title="Synthetic duplicate")
    matter.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(config_entry_id=matter.entry_id,
        identifiers={("matter", "r2-copy")}, manufacturer="Roborock", model="Robot")
    copy = er.async_get(hass).async_get_or_create("vacuum", "matter", "r2-copy",
        device_id=bridge.id, config_entry=matter, suggested_object_id="r2_copy").entity_id
    assert copy == "vacuum.r2_copy"
    hass.states.async_set(copy, "docked")
    storage = await _setup(hass)
    client = await hass_ws_client(hass)
    link = "distinct" if target == "distinct" else VACUUM
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"robot_links": {copy: link}}})
    assert (await client.receive_json())["success"]
    await _settle(hass)
    now = int(time.time() * 1000)
    original = {"used_ml": 432, "initialized": True, "last_reset_ts": now if incomplete else 0,
        "accounting_incomplete": incomplete, "calibration_history": [{"sample": "owner"}],
        "refill_history": [{"source": "earlier", "used_before_ml": 123}],
        "last_accounting_interruption": {"reason": "gap"} if incomplete else None}
    other = {"used_ml": 999, "initialized": True, "last_reset_ts": 0,
        "calibration_history": [{"sample": "copy"}], "refill_history": [{"source": "copy"}]}
    await storage.async_set_tank_state(VACUUM, original)
    await storage.async_set_tank_state(copy, other)
    target_id = VACUUM if target == "primary" else copy
    owner = copy if target == "distinct" else VACUUM
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    listing = (await client.receive_json())["result"]
    assert listing["balance_links"][copy] == link
    assert next(v for v in listing["vacuums"] if v["entity_id"] == copy)["balance_owner"] == owner
    expected_other = VACUUM if owner == copy else copy
    before_other = (await storage.async_get_state())["tank_states"][expected_other]
    events = []
    unsub = hass.bus.async_listen(f"{DOMAIN}_state_changed", lambda event: events.append(event.data))
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": target_id})
    result = await client.receive_json()
    assert result["success"]
    await _settle(hass)
    tanks = (await storage.async_get_state())["tank_states"]
    assert result["result"]["vacuum_entity"] == owner
    assert result["result"]["state"]["used_ml"] == 0
    assert tanks[owner]["used_ml"] == 0
    assert tanks[owner]["last_reset_source"] == "card"
    assert tanks[owner]["calibration_history"] == (other if owner == copy else original)["calibration_history"]
    assert tanks[owner]["refill_history"][0]["source"] == "card"
    assert tanks[expected_other]["used_ml"] == before_other["used_ml"]
    assert tanks[expected_other]["refill_history"] == before_other["refill_history"]
    assert any(owner in event.get("tank_states", {}) for event in events)
    if incomplete:
        assert not tanks[owner]["accounting_incomplete"]
        assert tanks[owner]["last_accounting_interruption"]["reason"] == "gap"
    if owner == VACUUM:
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        sensor = next(item.entity_id for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
                      if item.unique_id.endswith("_vacuum_robot_water_used_since_refill"))
        assert float(hass.states.get(sensor).state) == 0
    history = list(tanks[owner]["refill_history"])
    reset_ts = tanks[owner]["last_reset_ts"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": target_id})
    assert (await client.receive_json())["success"]
    await _settle(hass)
    repeated = (await storage.async_get_state())["tank_states"]
    assert repeated[owner]["refill_history"] == history
    assert repeated[owner]["last_reset_ts"] == reset_ts
    assert repeated[expected_other]["refill_history"] == before_other["refill_history"]
    unsub()


@pytest.mark.parametrize("route", ["card", "service", "empty", "empty_supported"])
async def test_registry_duplicate_action_uses_balance_owner(hass: HomeAssistant, hass_ws_client, route):
    """A registry-proven duplicate shares the displayed owner's tank."""
    storage = await _setup(hass)
    registry = er.async_get(hass)
    primary = registry.async_get(VACUUM)
    roborock = next(e for e in hass.config_entries.async_entries("roborock"))
    copy = registry.async_get_or_create("vacuum", "roborock", "r2-registry-copy",
        device_id=primary.device_id, config_entry=roborock, suggested_object_id="zzz_r2_registry_copy").entity_id
    assert copy == "vacuum.zzz_r2_registry_copy"
    hass.states.async_set(copy, "docked")
    if route == "empty":
        registry.async_remove("sensor.robot_dock_error")
        hass.states.async_remove("sensor.robot_dock_error")
    await _settle(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True,
        "calibration_history": [{"sample": "owner"}], "refill_history": [{"source": "earlier"}]})
    await storage.async_set_tank_state(copy, {"used_ml": 999, "initialized": True,
        "calibration_history": [{"sample": "copy"}], "refill_history": [{"source": "copy"}]})
    from custom_components.ha_vacuum_water_monitor.robots import async_reports
    reports = await async_reports(hass)
    assert any(r["vacuum_entity"] == VACUUM for r in reports)
    assert not any(r["vacuum_entity"] == copy for r in reports)
    if route.startswith("empty"):
        assert next(r for r in reports if r["vacuum_entity"] == VACUUM)["can_calibrate"] == (route == "empty_supported")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    listing = (await client.receive_json())["result"]
    assert listing["balance_links"].get(copy) is None
    assert next(v for v in listing["vacuums"] if v["entity_id"] == copy)["balance_owner"] == VACUUM
    if route == "service":
        await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": copy}, blocking=True)
    else:
        await client.send_json_auto_id({"type": f"{DOMAIN}/" + ("reset_tank" if route == "card" else "mark_empty"),
                                        "vacuum_entity": copy})
        result = await client.receive_json()
        if route == "empty_supported":
            assert not result["success"]
            assert "reports an empty tank itself" in result["error"]["message"]
        else:
            assert result["success"]
            assert result["result"]["vacuum_entity"] == VACUUM
    await _settle(hass)
    tanks = (await storage.async_get_state())["tank_states"]
    assert tanks[copy]["used_ml"] == 999
    assert tanks[copy]["refill_history"] == [{"source": "copy"}]
    assert tanks[VACUUM]["calibration_history"] == [{"sample": "owner"}]
    if route == "empty_supported":
        assert not tanks[VACUUM].get("user_empty_active")
        assert not tanks[copy].get("user_empty_active")
        assert tanks[VACUUM]["used_ml"] == 432
    elif route == "empty":
        assert tanks[VACUUM]["user_empty_active"]
        assert not tanks[copy].get("user_empty_active")
    else:
        assert tanks[VACUUM]["used_ml"] == 0
        assert tanks[VACUUM]["last_reset_source"] == route


async def test_a_device_with_the_old_placeholder_name_gets_the_robots_name(hass: HomeAssistant) -> None:
    """5.8.0: single-device cards saved "Vacuum" as the robot's name."""
    storage = await _setup(hass)
    await storage.async_set_settings({"configured_devices": [{"vacuum_entity": VACUUM, "name": "Vacuum"}]})
    registry = dr.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = next(d for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
                  if (DOMAIN, f"{entry.entry_id}_vacuum_robot") in d.identifiers)
    registry.async_update_device(device.id, name="Vacuum")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(device.id).name == "Robot"


async def test_household_can_subscribe_to_water_balance_updates(hass: HomeAssistant, hass_ws_client, hass_admin_user) -> None:
    """A normal authenticated account receives compact domain events immediately."""
    await _setup(hass)
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/subscribe"})
    response = await client.receive_json()
    assert response["success"], response
    payload = {"partial": True, "tank_states": {VACUUM: {"used_ml": 175}}}
    hass.bus.async_fire(f"{DOMAIN}_state_changed", payload)
    await hass.async_block_till_done()
    event = await client.receive_json()
    assert event["event"] == {"data": payload}
    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": response["id"]})
    assert (await client.receive_json())["success"]


# V8: thresholds share one atomic validation path and round-trip through HA options.
@pytest.mark.parametrize("patch", [
    {"warning_threshold": 0}, {"warning_threshold": 100},
    {"critical_threshold": 0}, {"critical_threshold": 100},
    {"warning_threshold": 10, "critical_threshold": 10},
    {"warning_threshold": 9, "critical_threshold": 10},
    {"warning_threshold": 9}, {"critical_threshold": 25},
    {"warning_threshold": True}, {"critical_threshold": "5"},
    {"warning_threshold": float("nan")},
])
async def test_v8_storage_rejects_invalid_threshold_patch_atomically(hass, patch):
    storage = await _setup(hass)
    before = await storage.async_get_state()
    with pytest.raises(ValueError):
        await storage.async_set_settings({"intro_dismissed": {"vacuum.robot": True}, **patch})
    assert await storage.async_get_state() == before
    from custom_components.ha_vacuum_water_monitor.storage import VacuumWaterStorage
    reloaded = VacuumWaterStorage(hass)
    assert await reloaded.async_get_state() == before


async def test_v8_admin_websocket_thresholds_persist_through_options_and_reload(hass, hass_ws_client):
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options={"unrelated_option": "kept"})
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/set_settings", "patch": {
        "warning_threshold": 99, "critical_threshold": 1, "intro_dismissed": {VACUUM: True}}})
    response = await client.receive_json()
    assert response["success"]
    await hass.async_block_till_done()
    assert entry.options == {"unrelated_option": "kept", "warning_threshold": 99, "critical_threshold": 1}
    assert (await storage.async_get_settings())["intro_dismissed"] == {VACUUM: True}
    assert response["result"]["settings"]["warning_threshold"] == 99
    # This is a real entry reload: stale options must not undo the card's write.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    current = await hass.data[DOMAIN]["storage"].async_get_settings()
    assert (current["warning_threshold"], current["critical_threshold"]) == (99, 1)
    assert current["intro_dismissed"] == {VACUUM: True}


async def test_v8_household_settings_remain_allowed_but_threshold_patch_is_atomic_unauthorized(
    hass, hass_ws_client, hass_admin_user,
):
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    # Fixture user remains authenticated but lacks administrator privileges.
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/set_settings", "patch": {
        "intro_dismissed": {VACUUM: True}}})
    assert (await client.receive_json())["success"]
    before = await storage.async_get_state()
    options_before = dict(entry.options)
    await client.send_json({"id": 2, "type": f"{DOMAIN}/set_settings", "patch": {
        "warning_threshold": 90, "critical_threshold": 5, "intro_dismissed": {VACUUM: False}}})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "unauthorized"
    assert await storage.async_get_state() == before
    assert dict(entry.options) == options_before


@pytest.mark.parametrize("patch", [
    {"warning_threshold": 0}, {"critical_threshold": 100},
    {"warning_threshold": 10, "critical_threshold": 10},
])
async def test_v8_admin_websocket_invalid_thresholds_do_not_save_other_settings(hass, hass_ws_client, patch):
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    before = await storage.async_get_state()
    options_before = dict(entry.options)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/set_settings", "patch": {
        "intro_dismissed": {VACUUM: True}, **patch}})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "invalid_payload"
    assert await storage.async_get_state() == before
    assert dict(entry.options) == options_before


async def test_v8_options_flow_validation_and_immediate_storage_roundtrip(hass, hass_ws_client):
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/set_settings", "patch": {
        "warning_threshold": 80, "critical_threshold": 20}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    before = await storage.async_get_state()
    invalid = await hass.config_entries.options.async_configure(flow["flow_id"], user_input={
        "warning_threshold": 20, "critical_threshold": 20})
    assert invalid["type"] == "form"
    assert invalid["errors"]
    assert entry.options["warning_threshold"] == 80
    assert await storage.async_get_state() == before
    valid = await hass.config_entries.options.async_configure(flow["flow_id"], user_input={
        "warning_threshold": 70, "critical_threshold": 15})
    assert valid["type"] == "create_entry"
    await hass.async_block_till_done()
    current = await storage.async_get_settings()
    assert (current["warning_threshold"], current["critical_threshold"]) == (70, 15)
    assert hass.data[DOMAIN]["storage"] is storage  # no integration restart
    from custom_components.ha_vacuum_water_monitor.storage import VacuumWaterStorage
    persisted = await VacuumWaterStorage(hass).async_get_settings()
    assert (persisted["warning_threshold"], persisted["critical_threshold"]) == (70, 15)


async def test_v8_partial_threshold_write_preserves_the_other_option(hass, hass_ws_client):
    storage = await _setup(hass)
    before = await storage.async_get_settings()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/set_settings", "patch": {"warning_threshold": 90}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options["warning_threshold"] == 90
    assert entry.options["critical_threshold"] == before["critical_threshold"]
    assert (await storage.async_get_settings())["critical_threshold"] == before["critical_threshold"]


@pytest.mark.parametrize("warning,critical", [(0, 1), (100, 1), (99, 0), (99, 100), (20, 21)])
async def test_v8_options_flow_rejects_invalid_pair_without_persistence(hass, warning, critical):
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    before = await storage.async_get_state()
    before_options = dict(entry.options)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    from homeassistant.data_entry_flow import InvalidData
    if not (1 <= warning <= 99 and 1 <= critical <= 99):
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(flow["flow_id"], user_input={
                "warning_threshold": warning, "critical_threshold": critical})
    else:
        result = await hass.config_entries.options.async_configure(flow["flow_id"], user_input={
            "warning_threshold": warning, "critical_threshold": critical})
        assert result["type"] == "form"
        assert result["errors"]
    await hass.async_block_till_done()
    assert dict(entry.options) == before_options
    assert await storage.async_get_state() == before


async def test_v8_failed_save_does_not_publish_part_of_threshold_patch(hass, monkeypatch):
    from unittest.mock import AsyncMock
    storage = await _setup(hass)
    before = await storage.async_get_state()
    monkeypatch.setattr(storage._store, "async_save", AsyncMock(side_effect=OSError("save failed")))
    with pytest.raises(OSError):
        await storage.async_set_settings({"warning_threshold": 90, "intro_dismissed": {VACUUM: True}})
    assert await storage.async_get_state() == before


async def test_repair_keeps_interruption_reason_on_disk(hass: HomeAssistant, hass_storage) -> None:
    from custom_components.ha_vacuum_water_monitor.repairs import ConfirmFullFlow
    storage = await _setup(hass)
    incident = {"ts": 1791800000000, "reasons": ["accounting_context_changed"]}
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 240,
        "accounting_incomplete": True, "last_accounting_reason": "not_mopping",
        "last_accounting_interruption": incident, "calibration_factor": 1.1,
        "last_reset_ts": int((dt_util.utcnow() - timedelta(seconds=30)).timestamp() * 1000)})
    flow = ConfirmFullFlow({"vacuum_entity": VACUUM, "check": "accounting_paused"})
    flow.hass = hass
    form = await flow.async_step_confirm()
    assert form["description_placeholders"]["reason"] == "accounting_context_changed"
    result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    stored = hass_storage[DOMAIN]["data"]["tank_states"][VACUUM]
    assert stored["last_accounting_interruption"]["reasons"] == incident["reasons"]
    assert stored["last_accounting_interruption"]["refill_source"] == "repair"
    assert stored["last_accounting_interruption"]["resolved_ts"] > incident["ts"]
    assert stored["calibration_factor"] == 1.1


async def test_completed_wash_survives_storage_reload_and_startup_unknown(hass: HomeAssistant, hass_storage) -> None:
    """The real HA Store restores the completed cycle without a false Repair."""
    import copy
    from custom_components.ha_vacuum_water_monitor.storage import VacuumWaterStorage
    from custom_components.ha_vacuum_water_monitor.tick import tick_device
    from custom_components.ha_vacuum_water_monitor.sensor_calculations import build_vacuum_devices, apply_custom_calibration
    from custom_components.ha_vacuum_water_monitor.discovery import descriptors_from_hass

    storage = await _setup(hass)
    settings = await storage.async_get_settings()
    device = apply_custom_calibration(build_vacuum_devices(settings, {}, descriptors_from_hass(hass))[0], settings)
    state = {"initialized": True, "used_ml": 0, "last_status": "charging", "last_area": 0,
             "last_tick_ts": 9_940_000, "last_reset_ts": 0, "calibration_factor": 1,
             "calibration_samples": 0}
    for ts, status, vacuum, area in (
        (10_060_000, "cleaning", "cleaning", "0"),
        (10_120_000, "cleaning", "cleaning", "4"),
        (10_180_000, "washing_the_mop", "docked", "4"),
        (10_240_000, "charging", "docked", "4"),
    ):
        _robot_states(hass, status=status, vacuum=vacuum, area=area)
        state, _ = tick_device(hass, device, state, now_ts=ts)
    assert state["used_ml"] == 174
    assert state["wash_sequence_active"] and not state.get("session_start_ts")
    assert not state.get("accounting_incomplete")
    before = copy.deepcopy(state)
    await storage.async_set_tank_state(VACUUM, state)
    restored = VacuumWaterStorage(hass)
    state = (await restored.async_get_state())["tank_states"][VACUUM]
    assert state == before
    for ts in (10_840_000, 10_850_000):
        _robot_states(hass, status="unknown", vacuum="unknown", area="4")
        state, _ = tick_device(hass, device, state, now_ts=ts)
        assert state["gap_started_ts"] == 10_240_000
    _robot_states(hass, area="4")
    state, _ = tick_device(hass, device, state, now_ts=10_860_000)
    await restored.async_set_tank_state(VACUUM, state)
    on_disk = hass_storage[DOMAIN]["data"]["tank_states"][VACUUM]
    assert not on_disk.get("accounting_incomplete")
    assert on_disk["used_ml"] == 174
    assert on_disk["automatic_sessions"] == before["automatic_sessions"]
    assert on_disk.get("last_accounting_interruption") is None


async def test_actual_registry_separate_dock_discovery_has_no_deprecated_entry_warning(hass, hass_ws_client, caplog):
    upstream = MockConfigEntry(domain="roborock", title="Synthetic Roborock")
    other = MockConfigEntry(domain="roborock", title="Other Roborock")
    upstream.add_to_hass(hass)
    other.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    robot = devices.async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("roborock", "r1-registry-robot")}, manufacturer="Roborock", model="r1_model")
    dock = devices.async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("roborock", "r1-registry-dock")}, manufacturer="Roborock", model="r1_model Dock")
    foreign = devices.async_get_or_create(config_entry_id=other.entry_id,
        identifiers={("roborock", "r1-registry-foreign")}, manufacturer="Roborock", model="r1_model Dock")
    entities.async_get_or_create("vacuum", "roborock", "r1-registry-vacuum", device_id=robot.id,
        config_entry=upstream, suggested_object_id="r1_registry_robot")
    for dev, owner, name in ((dock, upstream, "r1_clean"), (foreign, other, "r1_foreign")):
        entities.async_get_or_create("binary_sensor", "roborock", name, device_id=dev.id,
            config_entry=owner, suggested_object_id=name, translation_key="clean_box_empty")
        hass.states.async_set(f"binary_sensor.{name}", "off")
    hass.states.async_set("vacuum.r1_registry_robot", "docked")
    entry = MockConfigEntry(domain=DOMAIN, title="VWM", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    listed = (await client.receive_json())["result"]["vacuums"]
    result = next(d for d in listed if d["entity_id"] == "vacuum.r1_registry_robot")
    assert result["signals"]["dock_clean_water_sensor"] == "binary_sensor.r1_clean"
    assert "binary_sensor.r1_foreign" not in result["signals"].values()
    assert not any("config_entries" in rec.message and "deprecated" in rec.message.lower() for rec in caplog.records)


async def test_reprofile_rebinds_discovered_area_for_ordinary_events(hass, hass_ws_client):
    storage = await _setup(hass)
    registry = er.async_get(hass)
    old = registry.async_get("sensor.robot_cleaning_area")
    registry.async_update_entity(old.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    upstream = hass.config_entries.async_entries("roborock")[0]
    registry.async_get_or_create("sensor", "roborock", "r1-replacement-area", device_id=old.device_id,
        config_entry=upstream, suggested_object_id="r1_new_area", translation_key="cleaning_area")
    hass.states.async_set("sensor.r1_new_area", "1", {"unit_of_measurement": "m²"})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/reprofile", "vacuum_entity": VACUUM})
    assert (await client.receive_json())["success"]
    await _settle(hass)
    hass.states.async_set("sensor.r1_new_area", "7", {"unit_of_measurement": "m²"})
    await _settle(hass)
    assert (await _tank(storage))["last_area"] == 7
    hass.states.async_set("sensor.robot_cleaning_area", "20", {"unit_of_measurement": "m²"})
    await _settle(hass)
    assert (await _tank(storage))["last_area"] == 7


async def test_settings_reports_saved_even_if_refresh_fails(hass, hass_ws_client, monkeypatch):
    import custom_components.ha_vacuum_water_monitor as integration
    storage = await _setup(hass)
    client = await hass_ws_client(hass)

    async def fail_refresh(*args, **kwargs):
        raise RuntimeError("synthetic refresh failure")

    original_tick = integration.async_tick_water_state
    hass.states.async_set("sensor.r1_recovery", "1", {"unit_of_measurement": "m²"})
    monkeypatch.setattr(integration, "async_tick_water_state", fail_refresh)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "robot_links": {"vacuum.example": "distinct"},
        "configured_devices": [{"vacuum_entity": VACUUM, "area_sensor": "sensor.r1_recovery"}]}})
    response = await client.receive_json()
    assert response["success"]
    assert response["result"]["bindings_refreshed"] is False
    assert (await storage.async_get_state())["settings"]["robot_links"]["vacuum.example"] == "distinct"
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert (await client.receive_json())["result"]["settings"]["robot_links"]["vacuum.example"] == "distinct"
    monkeypatch.setattr(integration, "async_tick_water_state", original_tick)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=65))
    await hass.async_block_till_done()
    hass.states.async_set("sensor.r1_recovery", "7", {"unit_of_measurement": "m²"})
    await _settle(hass)
    assert (await _tank(storage))["last_area"] == 7


async def test_registry_vacuum_rename_keeps_its_water_history(hass, hass_ws_client):
    storage = await _setup(hass)
    vwm_entry = hass.config_entries.async_entries(DOMAIN)[0]
    registry = er.async_get(hass)
    before_entities = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, vwm_entry.entry_id)}
    sensor = next(item for item in er.async_entries_for_config_entry(registry, vwm_entry.entry_id)
                  if item.unique_id.endswith("_vacuum_robot_water_remaining"))
    registry.async_update_entity(sensor.entity_id, name="Custom water name")
    number = next(item.entity_id for item in er.async_entries_for_config_entry(registry, vwm_entry.entry_id)
                  if item.unique_id.endswith("_vacuum_robot_tank_capacity"))
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True,
        "refill_history": [{"used_before_ml": 876}]})
    registry.async_update_entity(VACUUM, new_entity_id="vacuum.r1_renamed")
    hass.states.async_remove(VACUUM)
    hass.states.async_set("vacuum.r1_renamed", "docked")
    await _settle(hass)
    state = await storage.async_get_state()
    assert "registry_identities" not in state
    assert state["tank_states"]["vacuum.r1_renamed"]["used_ml"] == 432
    assert state["tank_states"]["vacuum.r1_renamed"]["refill_history"] == [{"used_before_ml": 876}]
    after_entities = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, vwm_entry.entry_id)}
    assert after_entities == before_entities
    assert registry.async_get(sensor.entity_id).name == "Custom water name"
    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 3000}, blocking=True)
    await hass.async_block_till_done()
    assert (await storage.async_get_settings())["device_options"]["vacuum.r1_renamed"]["capacity_ml"] == 3000
    # A stale authored card save must address the renamed registry entity.
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "configured_devices": [{"vacuum_entity": VACUUM, "water_total_ml": 1234}]}})
    assert (await client.receive_json())["success"]
    settings = (await storage.async_get_state())["settings"]
    assert settings["configured_devices"][0] == {"vacuum_entity": "vacuum.r1_renamed", "water_total_ml": 1234}
    # If the old id is reused, it now identifies a different registry entity.
    upstream = MockConfigEntry(domain="matter", title="Independent")
    upstream.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("vacuum", "matter", "r1-new-independent", config_entry=upstream,
        suggested_object_id="robot")
    hass.states.async_set(VACUUM, "docked")
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "configured_devices": [{"vacuum_entity": VACUUM, "water_total_ml": 1234}]}})
    assert not (await client.receive_json())["success"]
    state = await storage.async_get_state()
    assert state["settings"]["configured_devices"][0]["vacuum_entity"] == "vacuum.r1_renamed"
    assert state["tank_states"]["vacuum.r1_renamed"]["used_ml"] == 432


@pytest.mark.parametrize("operation", ["preview", "holdout"])
async def test_measurements_follow_registry_identity_after_rename_and_reuse(hass, hass_ws_client, operation):
    """Old provenance remains historical, but the same robot can still use its measurements."""
    from custom_components.ha_vacuum_water_monitor.contribution import SETTINGS

    storage = await _setup(hass)
    context = {"model_id": "roborock_s8_maxv_ultra", "sku": "EU", "dock_variant": "tank",
        "firmware": "1.0", "integration_id": "roborock", "integration_version": "1.0",
        "reservoir": "dock_clean", "action": "floor_mopping",
        "settings": dict.fromkeys(SETTINGS, "not_applicable")}
    sessions = [{"ts": n, "area": 10, "context": context, "accounting_valid": True,
                 "exposure_complete": True, "segments": 1} for n in (101, 102, 103, 104)]
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 50,
                                                 "automatic_sessions": sessions})
    client = await hass_ws_client(hass)
    measurement = {"observed_ml": 100, "resolution_ml": 5, "instrument": "graduated_jug",
                   "boundaries_confirmed": True, "uninterrupted": True, "purpose": "training"}
    for index in range(3):
        await client.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": VACUUM,
            "session_index": index, "session_ts": sessions[index]["ts"], "measurement": measurement})
        result = await client.receive_json()
        assert result["success"]
    before = (await storage.async_get_state())["settings"]
    assert before["consumption_calibrations"][VACUUM][0]["coefficient"] == 10
    await client.send_json_auto_id({"type": f"{DOMAIN}/contribution_preview", "vacuum_entity": VACUUM,
                                   "sample_ids": ["local.101"]})
    baseline_preview = await client.receive_json()
    assert baseline_preview["success"], baseline_preview
    assert baseline_preview["result"]["samples"][0]["measured_ml"] == 100
    registry = er.async_get(hass)
    renamed = "vacuum.r3_renamed"
    registry.async_update_entity(VACUUM, new_entity_id=renamed)
    hass.states.async_remove(VACUUM)
    hass.states.async_set(renamed, "docked")
    await _settle(hass)
    matter = MockConfigEntry(domain="matter", title="Independent robot")
    matter.add_to_hass(hass)
    replacement = registry.async_get_or_create("vacuum", "matter", "r3-independent", config_entry=matter,
                                                suggested_object_id="robot")
    assert replacement.entity_id == VACUUM
    hass.states.async_set(VACUUM, "docked")
    await _settle(hass)
    saved = (await storage.async_get_state())["settings"]
    assert [s["device_id"] for s in saved["local_measurements"][renamed]] == [VACUUM] * 3
    assert not saved["local_measurements"].get(VACUUM)
    if operation == "preview":
        await client.send_json_auto_id({"type": f"{DOMAIN}/contribution_preview", "vacuum_entity": VACUUM,
                                       "sample_ids": ["local.101"]})
        assert not (await client.receive_json())["success"]
        await client.send_json_auto_id({"type": f"{DOMAIN}/contribution_preview", "vacuum_entity": renamed,
                                       "sample_ids": ["local.101"]})
        result = await client.receive_json()
        assert result["success"]
        assert result["result"]["samples"][0]["measured_ml"] == 100
        assert result["result"]["publication_consent"] is False
    else:
        await client.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": renamed,
            "session_index": 3, "session_ts": 104,
            "measurement": {**measurement, "purpose": "validation", "observed_ml": 120}})
        result = await client.receive_json()
        assert result["success"]
        assert result["result"]["calibration"]["coefficient"] == 10
        assert result["result"]["calibration"]["validation"]["validation_ids"] == ["local.104"]


@pytest.mark.parametrize("keep_other", [False, True])
async def test_preupgrade_measurements_after_rename_keep_historical_context(hass, hass_ws_client, keep_other):
    """Only the same owner's proven legacy identifiers are compared as one identity."""
    from copy import deepcopy
    from custom_components.ha_vacuum_water_monitor.calibration import build_local_measurement, fit_local_measurements
    from custom_components.ha_vacuum_water_monitor.contribution import SETTINGS

    storage = await _setup(hass)
    registry = er.async_get(hass)
    renamed = "vacuum.r3_preupgrade"
    registry.async_update_entity(VACUUM, new_entity_id=renamed)
    hass.states.async_remove(VACUUM)
    hass.states.async_set(renamed, "docked")
    await _settle(hass)
    context = {"model_id": "roborock_s8_maxv_ultra", "sku": "EU", "dock_variant": "tank",
        "firmware": "1.0", "integration_id": "roborock", "integration_version": "1.0",
        "reservoir": "dock_clean", "action": "floor_mopping", "device_id": renamed,
        "settings": dict.fromkeys(SETTINGS, "not_applicable")}
    measurement = {"observed_ml": 100, "resolution_ml": 5, "instrument": "graduated_jug",
                   "boundaries_confirmed": True, "uninterrupted": True, "purpose": "training"}
    def session(ts, ctx):
        return {"ts": ts, "area": 10, "context": ctx, "accounting_valid": True,
                "exposure_complete": True, "segments": 1}
    legacy = [build_local_measurement(session(n, context), measurement, renamed) for n in (301, 302, 303)]
    legacy_fit = fit_local_measurements(legacy)
    assert legacy_fit["coefficient"] == 10
    other_method = {**deepcopy(legacy_fit), "id": "local.time", "method": "time", "unit": "ml/min"}
    await storage.async_set_settings({"local_measurements": {renamed: deepcopy(legacy)},
        "consumption_calibrations": {renamed: [legacy_fit, *([other_method] if keep_other else [])]}})
    current_context = {**context, "device_id": VACUUM}
    await storage.async_set_tank_state(renamed, {"initialized": True, "used_ml": 0,
        "automatic_sessions": [session(304, current_context)]})
    independent = MockConfigEntry(domain="matter", title="Independent robot")
    independent.add_to_hass(hass)
    replacement = registry.async_get_or_create("vacuum", "matter", "r3-upgrade-independent", config_entry=independent,
                                                suggested_object_id="robot")
    assert replacement.entity_id == VACUUM
    hass.states.async_set(VACUUM, "docked")
    await _settle(hass)
    client = await hass_ws_client(hass)
    values = {**measurement, "purpose": "validation", "observed_ml": 120}
    await client.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": renamed,
        "session_index": 0, "session_ts": 304, "measurement": values})
    result = await client.receive_json()
    assert result["success"]
    assert result["result"]["calibration"]["coefficient"] == 10
    assert result["result"]["calibration"]["validation"]["validation_ids"] == ["local.304"]
    saved = (await storage.async_get_state())["settings"]
    assert saved["local_measurements"][renamed][:3] == legacy
    saved_profiles = saved["consumption_calibrations"][renamed]
    assert len([p for p in saved_profiles if p["method"] == "area" and p["scope"] == "whole_cycle"]) == 1
    assert (other_method in saved_profiles) is keep_other
    assert not saved["local_measurements"].get(VACUUM)


async def test_measured_calibration_remains_applicable_after_registry_rename(hass, hass_ws_client):
    """A producer event uses the same physical calibration after a registry rename."""
    from custom_components.ha_vacuum_water_monitor.profiles import CONSUMPTION_SETTINGS

    storage = await _setup(hass)
    registry = er.async_get(hass)
    client = await hass_ws_client(hass)
    plan = {"confirmed": True, "sku": "EU", "dock_variant": "tank", "firmware": "1.0",
            "integration_version": "1.0", "settings": dict.fromkeys(CONSUMPTION_SETTINGS, "not_applicable")}
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_measurement_plan", "vacuum_entity": VACUUM, "plan": plan})
    assert (await client.receive_json())["success"]
    hass.states.async_set("select.robot_mop_mode", "deep")
    await _settle(hass)
    hass.states.async_set("select.robot_mop_mode", "standard")
    await _settle(hass)
    state = (await storage.async_get_state())["tank_states"][VACUUM]
    context = state["last_consumption_context"]
    assert context["firmware"] == "1.0"
    sessions = [{"ts": n, "area": 10, "context": context, "accounting_valid": True,
                 "exposure_complete": True, "segments": 1} for n in (201, 202, 203)]
    state.update(initialized=True, used_ml=0, automatic_sessions=sessions)
    await storage.async_set_tank_state(VACUUM, state)
    measurement = {"observed_ml": 100, "resolution_ml": 5, "instrument": "graduated_jug",
                   "boundaries_confirmed": True, "uninterrupted": True, "purpose": "training"}
    for index in range(3):
        await client.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": VACUUM,
            "session_index": index, "session_ts": sessions[index]["ts"], "measurement": measurement})
        assert (await client.receive_json())["success"]
    async def ordinary_session(entity):
        hass.states.async_set(entity, "cleaning", {"status": "cleaning"})
        hass.states.async_set("sensor.robot_status", "cleaning")
        hass.states.async_set("sensor.robot_cleaning_area", "0", {"unit_of_measurement": "m²"})
        await _settle(hass)
        hass.states.async_set("sensor.robot_cleaning_area", "10", {"unit_of_measurement": "m²"})
        await _settle(hass)
        hass.states.async_set(entity, "docked", {"status": "charging"})
        hass.states.async_set("sensor.robot_status", "charging")
        await _settle(hass)
        return (await storage.async_get_state())["tank_states"][entity]

    baseline = await ordinary_session(VACUUM)
    assert baseline["used_ml"] == 100, (baseline.get("whole_cycle_fallback_reason"),
        baseline.get("consumption_resolution"), baseline["automatic_sessions"][0].get("exposure_complete"),
        baseline["automatic_sessions"][0].get("accounting_valid"), baseline["automatic_sessions"][0].get("area"))
    assert baseline["last_accounting_evidence"] == "device_calibration"
    baseline["used_ml"] = 0
    await storage.async_set_tank_state(VACUUM, baseline)
    renamed = "vacuum.r3_calibrated"
    registry.async_update_entity(VACUUM, new_entity_id=renamed)
    hass.states.async_remove(VACUUM)
    hass.states.async_set(renamed, "docked", {"status": "charging"})
    await _settle(hass)
    tank = await ordinary_session(renamed)
    assert tank["used_ml"] == 100
    assert tank["last_accounting_evidence"] == "device_calibration"
    assert tank["automatic_sessions"][0]["water"] == 100


async def test_vacuum_rename_while_unloaded_reconciles_registry_identity(hass):
    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    registry = er.async_get(hass)
    original = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert await hass.config_entries.async_unload(entry.entry_id)
    er.async_get(hass).async_update_entity(VACUUM, new_entity_id="vacuum.r1_offline_rename")
    hass.states.async_remove(VACUUM)
    hass.states.async_set("vacuum.r1_offline_rename", "docked")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = await hass.data[DOMAIN]["storage"].async_get_state()
    assert state["tank_states"]["vacuum.r1_offline_rename"]["used_ml"] == 432
    assert {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)} == original


async def test_vacuum_rename_conflict_does_not_merge_existing_history(hass, caplog):
    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True})
    await storage.async_set_tank_state("vacuum.r1_conflict", {"used_ml": 999, "initialized": True})
    er.async_get(hass).async_update_entity(VACUUM, new_entity_id="vacuum.r1_conflict")
    await _settle(hass)
    states = (await storage.async_get_state())["tank_states"]
    assert states[VACUUM]["used_ml"] == 432
    assert states["vacuum.r1_conflict"]["used_ml"] == 999
    assert any("rename" in r.message.lower() and "conflict" in r.message.lower() for r in caplog.records)


async def test_offline_rename_with_reused_old_id_keeps_identity_and_separate_banks(hass):
    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True,
        "refill_history": [{"used_before_ml": 876}]})
    await storage.async_set_settings({"configured_devices": [{"vacuum_entity": VACUUM, "water_total_ml": 1234}]})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    registry = er.async_get(hass)
    original = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert await hass.config_entries.async_unload(entry.entry_id)
    registry.async_update_entity(VACUUM, new_entity_id="vacuum.r1_offline_rename")
    hass.states.async_remove(VACUUM)
    independent = MockConfigEntry(domain="matter", title="Independent")
    independent.add_to_hass(hass)
    replacement = registry.async_get_or_create("vacuum", "matter", "r1-independent", config_entry=independent,
        suggested_object_id="robot")
    assert replacement.entity_id == VACUUM
    hass.states.async_set(VACUUM, "docked")
    hass.states.async_set("vacuum.r1_offline_rename", "docked")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = await hass.data[DOMAIN]["storage"].async_get_state()
    assert state["tank_states"]["vacuum.r1_offline_rename"]["used_ml"] == 432
    assert state["tank_states"]["vacuum.r1_offline_rename"]["refill_history"] == [{"used_before_ml": 876}]
    assert state["tank_states"].get(VACUUM, {}).get("used_ml", 0) != 432
    assert state["settings"]["configured_devices"][0]["vacuum_entity"] == "vacuum.r1_offline_rename"
    after = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert all(after.get(uid) == entity for uid, entity in original.items())


async def test_offline_reuse_without_original_holds_history_instead_of_attaching_to_new_robot(hass):
    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    registry = er.async_get(hass)
    registry.async_remove(VACUUM)
    hass.states.async_remove(VACUUM)
    independent = MockConfigEntry(domain="matter", title="Independent")
    independent.add_to_hass(hass)
    replacement = registry.async_get_or_create("vacuum", "matter", "r1-other-only", config_entry=independent,
        suggested_object_id="robot")
    assert replacement.entity_id == VACUUM
    hass.states.async_set(VACUUM, "docked")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = await hass.data[DOMAIN]["storage"].async_get_state()
    assert state["tank_states"].get(VACUUM, {}).get("used_ml", 0) != 432
    assert {item["entity_id"] for item in state["registry_identity_conflicts"]} == {VACUUM}


async def test_online_reuse_holds_original_entities_and_recovers_same_id(hass):
    storage = await _setup(hass)
    registry = er.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    original_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    sensor = next(item.entity_id for item in original_entries if item.unique_id.endswith('_vacuum_robot_water_used_since_refill'))
    number = next(item.entity_id for item in original_entries if item.unique_id.endswith('_vacuum_robot_tank_capacity'))
    original_ids = {item.unique_id: item.entity_id for item in original_entries}
    await storage.async_set_tank_state(VACUUM, {'used_ml': 432, 'initialized': True})
    registry.async_remove(VACUUM)
    hass.states.async_remove(VACUUM)
    independent = MockConfigEntry(domain='matter', title='Independent')
    independent.add_to_hass(hass)
    replacement = registry.async_get_or_create('vacuum', 'matter', 'online-b', config_entry=independent, suggested_object_id='robot')
    assert replacement.entity_id == VACUUM
    hass.states.async_set(VACUUM, 'docked')
    await _settle(hass)
    await storage.async_set_tank_state(VACUUM, {'used_ml': 999, 'initialized': True})
    assert hass.states.get(sensor).state == 'unavailable'
    assert hass.states.get(number).state == 'unavailable'
    try:
        await hass.services.async_call('number', 'set_value', {'entity_id': number, 'value': 3000}, blocking=True)
    except Exception:
        pass  # HA versions may either reject or skip an unavailable entity.
    assert (await storage.async_get_state())['tank_states'][VACUUM]['used_ml'] == 999
    assert VACUUM not in (await storage.async_get_settings()).get('device_options', {})
    registry.async_remove(VACUUM)
    hass.states.async_remove(VACUUM)
    upstream = hass.config_entries.async_entries('roborock')[0]
    device = next(d for d in dr.async_entries_for_config_entry(dr.async_get(hass), upstream.entry_id)
                  if ('roborock', 'robot-1') in d.identifiers)
    returned = registry.async_get_or_create('vacuum', 'roborock', 'robot-1', config_entry=upstream,
        device_id=device.id, suggested_object_id='robot')
    assert returned.entity_id == VACUUM
    _robot_states(hass)
    await _settle(hass)
    state = await storage.async_get_state()
    assert state['tank_states'][VACUUM]['used_ml'] == 432
    assert hass.states.get(sensor).state != 'unavailable'
    after = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert all(after.get(uid) == entity for uid, entity in original_ids.items())
    assert len([item for item in after if item.endswith('_vacuum_robot_water_used_since_refill')]) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    recovered = await hass.data[DOMAIN]['storage'].async_get_state()
    assert recovered['tank_states'][VACUUM]['used_ml'] == 432
    after_reload = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert all(after_reload.get(uid) == entity for uid, entity in original_ids.items())


async def test_existing_robot_rename_into_retired_id_blocks_stale_card(hass, hass_ws_client):
    storage = await _setup(hass)
    registry = er.async_get(hass)
    upstream = MockConfigEntry(domain="matter", title="Existing B")
    upstream.add_to_hass(hass)
    b = registry.async_get_or_create("vacuum", "matter", "existing-b", config_entry=upstream,
        suggested_object_id="existing_b")
    assert b.entity_id == "vacuum.existing_b"
    hass.states.async_set(b.entity_id, "docked")
    await _settle(hass)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 432, "initialized": True, "history": ["a"]})
    await storage.async_set_tank_state(b.entity_id, {"used_ml": 999, "initialized": True, "history": ["b"]})
    registry.async_update_entity(VACUUM, new_entity_id="vacuum.a_new")
    hass.states.async_remove(VACUUM)
    hass.states.async_set("vacuum.a_new", "docked")
    await _settle(hass)
    registry.async_update_entity("vacuum.existing_b", new_entity_id=VACUUM)
    hass.states.async_remove("vacuum.existing_b")
    hass.states.async_set(VACUUM, "docked")
    await _settle(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    state = (await client.receive_json())["result"]
    assert VACUUM in state["ambiguous_vacuum_ids"]
    assert state["tank_states"]["vacuum.a_new"]["used_ml"] == 432
    assert state["tank_states"][VACUUM]["used_ml"] == 999
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "configured_devices": [{"vacuum_entity": VACUUM, "water_total_ml": 1234}]}})
    assert not (await client.receive_json())["success"]
    registry.async_update_entity(VACUUM, new_entity_id="vacuum.existing_b")
    hass.states.async_remove(VACUUM)
    hass.states.async_set("vacuum.existing_b", "docked")
    await _settle(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert VACUUM in (await client.receive_json())["result"]["ambiguous_vacuum_ids"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "configured_devices": [{"vacuum_entity": VACUUM, "water_total_ml": 1234}]}})
    assert not (await client.receive_json())["success"]
