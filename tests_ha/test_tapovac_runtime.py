"""Native HA registries and ordinary state-change accounting for TapoVac."""
from datetime import timedelta
from copy import deepcopy

from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "ha_vacuum_water_monitor"


async def settle(hass):
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()


async def test_tapovac_attribute_updates_reach_native_accounting_and_store(hass, hass_ws_client):
    upstream = MockConfigEntry(domain="tapo_rv30", title="Synthetic TapoVac")
    upstream.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("tapo_rv30", "synthetic")}, manufacturer="Tapo", model="RV50 Pro Omni")
    registry = er.async_get(hass)
    registry.async_get_or_create("vacuum", "tapo_rv30", upstream.entry_id + "_vacuum",
        device_id=dev.id, config_entry=upstream, suggested_object_id="tapo")
    registry.async_get_or_create("select", "tapo_rv30", upstream.entry_id + "_area_unit",
        device_id=dev.id, config_entry=upstream, suggested_object_id="tapo_unit")
    matter = MockConfigEntry(domain="matter", title="Same robot over Matter")
    matter.add_to_hass(hass)
    bridged = dr.async_get(hass).async_get_or_create(config_entry_id=matter.entry_id,
        identifiers={("matter", "node-tapo")}, manufacturer="TP-Link", model="Robotic Vacuum Cleaner")
    registry.async_get_or_create("vacuum", "matter", "node-tapo", device_id=bridged.id,
        config_entry=matter, suggested_object_id="matter_tapo")
    registry.async_get_or_create("select", "matter", "node-tapo-mode", device_id=bridged.id,
        config_entry=matter, suggested_object_id="confirmed_robot_mode", translation_key="clean_mode")
    hass.states.async_set("vacuum.matter_tapo", "docked")
    # No authored mode: the ordinary card action confirms physical identity.
    hass.states.async_set("select.confirmed_robot_mode", "Vacuum and Mop;Deep Clean")
    hass.states.async_set("select.tapo_unit", "m²")
    def update(area, code=1, mode=None):
        if mode is not None:
            hass.states.async_set("select.confirmed_robot_mode", mode)
        hass.states.async_set("vacuum.tapo", "cleaning", {"status_code": code,
            "clean_area": area, "clean_time_min": area, "water_level": "low", "mop_attached": True})
    update(0, code=5)
    entry = MockConfigEntry(domain=DOMAIN, title="VWM", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    storage = hass.data[DOMAIN]["storage"]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"configured_devices": [{"vacuum_entity": "vacuum.tapo",
        "rate_signal": "mop_intensity",
        "usage_ml_per_m2": {"low": 2}, "accounting_evidence": "user_calibration"}]}})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    listed = (await client.receive_json())["result"]["vacuums"]
    assert "cleaning_mode_entity" not in next(v for v in listed if v["entity_id"] == "vacuum.tapo")["signals"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "robot_links": {"vacuum.matter_tapo": "vacuum.tapo"}}})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    listed = (await client.receive_json())["result"]["vacuums"]
    native = next(v for v in listed if v["entity_id"] == "vacuum.tapo")
    assert native["signals"]["cleaning_mode_entity"] == "select.confirmed_robot_mode"
    assert native["linked_mode_source"] == "vacuum.matter_tapo"
    # Establish native activity, then change only the Matter programme. The
    # ordinary state_changed event must reach the native owner's Store state.
    update(0)
    await settle(hass)
    hass.states.async_set("select.confirmed_robot_mode", "Vacuum")
    await settle(hass)
    tank = (await storage.async_get_state())["tank_states"]["vacuum.tapo"]
    assert tank["last_rate_settings"]["cleaning_mode"] == "vacuum"
    hass.states.async_set("select.confirmed_robot_mode", "Vacuum and Mop;Deep Clean")
    await settle(hass)
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": "vacuum.tapo"}, blocking=True)
    # The refill resets the area baseline; 0 -> 0 emits no state_changed.
    # A normal status transition supplies the first post-refill observation.
    update(0, code=5)
    await settle(hass)
    update(0)
    await settle(hass)
    update(2)
    await settle(hass)
    tank = (await storage.async_get_state())["tank_states"]["vacuum.tapo"]
    assert tank["used_ml"] == 4, {k: tank.get(k) for k in ("last_accounting_reason", "last_accounting_source", "last_status", "last_area", "intensity_unmapped", "consumption_resolution")}
    # Same vacuum state, attribute-only mode/status change must wake the ticker.
    update(4, code=2)
    await settle(hass)
    assert (await storage.async_get_state())["tank_states"]["vacuum.tapo"]["used_ml"] == 4
    update(6, mode="Vacuum")
    await settle(hass)
    assert (await storage.async_get_state())["tank_states"]["vacuum.tapo"]["used_ml"] == 4
    assert "select.tapo_unit" in hass.data[DOMAIN]["ticker"].entities
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
    await hass.async_block_till_done()
    persisted = await storage._store.async_load()
    assert persisted["tank_states"]["vacuum.tapo"]["used_ml"] == 4

    assert "select.confirmed_robot_mode" in hass.data[DOMAIN]["ticker"].entities
    saved = (await storage.async_get_state())["settings"]
    assert not saved["configured_devices"][0].get("cleaning_mode_entity")
    # A mode-only update wakes accounting without a native vacuum update.
    hass.states.async_set("select.confirmed_robot_mode", "unavailable")
    await settle(hass)
    assert (await storage.async_get_state())["tank_states"]["vacuum.tapo"]["used_ml"] == 4
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {
        "robot_links": {"vacuum.matter_tapo": "distinct"}}})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/list_vacuums"})
    native = next(v for v in (await client.receive_json())["result"]["vacuums"] if v["entity_id"] == "vacuum.tapo")
    assert "cleaning_mode_entity" not in native["signals"]


async def test_settings_rebinds_a_to_b_and_unlinks_without_a_heartbeat(hass, hass_ws_client):
    native = MockConfigEntry(domain="tapo_rv30", title="Tapo")
    native.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    robot = devices.async_get_or_create(config_entry_id=native.entry_id,
        identifiers={("tapo_rv30", "r1-robot")}, manufacturer="Tapo", model="RV50 Pro Omni")
    entities.async_get_or_create("vacuum", "tapo_rv30", native.entry_id + "_vacuum", device_id=robot.id,
        config_entry=native, suggested_object_id="r1_native")
    entities.async_get_or_create("select", "tapo_rv30", native.entry_id + "_area_unit", device_id=robot.id,
        config_entry=native, suggested_object_id="r1_area_unit")
    hass.states.async_set("select.r1_area_unit", "m²")
    for suffix in ("a", "b"):
        upstream = MockConfigEntry(domain="matter", title=f"Matter {suffix}")
        upstream.add_to_hass(hass)
        bridge = devices.async_get_or_create(config_entry_id=upstream.entry_id,
            identifiers={("matter", f"r1-{suffix}")}, manufacturer="Tapo", model="Robot")
        entities.async_get_or_create("vacuum", "matter", f"r1-vac-{suffix}", device_id=bridge.id,
            config_entry=upstream, suggested_object_id=f"r1_{suffix}")
        entities.async_get_or_create("select", "matter", f"r1-mode-{suffix}", device_id=bridge.id,
            config_entry=upstream, suggested_object_id=f"r1_mode_{suffix}", translation_key="clean_mode")
        hass.states.async_set(f"vacuum.r1_{suffix}", "docked")
        hass.states.async_set(f"select.r1_mode_{suffix}", "Vacuum")
    hass.states.async_set("vacuum.r1_native", "cleaning", {"status_code": 1, "clean_area": 0,
        "clean_time_min": 0, "water_level": "low", "mop_attached": True})
    entry = MockConfigEntry(domain=DOMAIN, title="VWM", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    client = await hass_ws_client(hass)
    storage = hass.data[DOMAIN]["storage"]
    await storage.async_set_tank_state("vacuum.r1_b", {"used_ml": 123, "initialized": True,
        "refill_history": [{"used_before_ml": 456}]})

    async def links(value):
        await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"robot_links": value}})
        assert (await client.receive_json())["success"]
        await settle(hass)

    async def mode():
        return (await storage.async_get_state())["tank_states"]["vacuum.r1_native"]["last_rate_settings"]["cleaning_mode"]

    await links({"vacuum.r1_a": "vacuum.r1_native", "vacuum.r1_b": "distinct"})
    hass.states.async_set("select.r1_mode_a", "Vacuum and Mop")
    await settle(hass)
    assert await mode() == "vacuum_and_mop"
    await links({"vacuum.r1_a": "distinct", "vacuum.r1_b": "vacuum.r1_native"})
    hass.states.async_set("select.r1_mode_a", "Vacuum then Mop")
    await settle(hass)
    assert await mode() == "vacuum"
    hass.states.async_set("select.r1_mode_b", "Vacuum and Mop")
    await settle(hass)
    assert await mode() == "vacuum_and_mop"
    await links({"vacuum.r1_a": "distinct", "vacuum.r1_b": "distinct"})
    assert await mode() is None
    hass.states.async_set("select.r1_mode_b", "Vacuum")
    await settle(hass)
    assert await mode() is None
    state = await storage.async_get_state()
    assert state["tank_states"]["vacuum.r1_native"].get("used_ml", 0) == 0
    assert state["tank_states"]["vacuum.r1_b"]["used_ml"] == 123
    assert state["tank_states"]["vacuum.r1_b"]["refill_history"] == [{"used_before_ml": 456}]


async def test_nominal_bank_follows_registry_identity_after_rename_and_reuse(hass):
    """Registry rename preserves the private nominal context, never another robot's bank."""
    from custom_components.ha_vacuum_water_monitor import nominal_time_learning as learning

    upstream = MockConfigEntry(domain="matter", title="Nominal synthetic")
    upstream.add_to_hass(hass)
    registry, devices = er.async_get(hass), dr.async_get(hass)
    device = devices.async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("matter", "r3-nominal")}, manufacturer="Tapo", model="RV50 Pro Omni", model_id="1797")
    original = registry.async_get_or_create("vacuum", "matter", "r3-nominal-vac", device_id=device.id,
        config_entry=upstream, suggested_object_id="r3_nominal").entity_id
    assert original == "vacuum.r3_nominal"
    registry.async_get_or_create("select", "matter", "r3-nominal-mode", device_id=device.id,
        config_entry=upstream, suggested_object_id="r3_nominal_mode", translation_key="clean_mode")
    hass.states.async_set(original, "docked")
    hass.states.async_set("select.r3_nominal_mode", "Vacuum and Mop;Deep Clean")
    entry = MockConfigEntry(domain=DOMAIN, title="VWM", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    storage = hass.data[DOMAIN]["storage"]
    tank = (await storage.async_get_state())["tank_states"][original]
    context = deepcopy(tank["last_consumption_context"])
    context.pop("action", None)
    context.pop("field_sources", None)
    assert context["device_id"] == original
    capacity = 5000
    bank = {}
    for n in range(3):
        now = 1_000_000 + n * 1_000_000
        bank = learning.start_full(bank, context=context, capacity_ml=capacity, now_ts=now)
        bank = learning.observe(bank, context=context, capacity_ml=capacity, now_ts=now, active=True)
        for step in range(1, 11):
            bank = learning.observe(bank, context=context, capacity_ml=capacity,
                                    now_ts=now + step * 60_000, active=True)
        bank = learning.finish_empty(bank, context=context, capacity_ml=capacity, now_ts=now + 600_000)
    assert learning.resolve(bank, context=context, capacity_ml=capacity)["status"] == "active"
    tank.update(nominal_time_learning=bank, initialized=True, used_ml=123)
    await storage.async_set_tank_state(original, tank)
    renamed = "vacuum.r3_nominal_renamed"
    registry.async_update_entity(original, new_entity_id=renamed)
    hass.states.async_remove(original)
    hass.states.async_set(renamed, "docked")
    await settle(hass)
    independent = MockConfigEntry(domain="matter", title="Another robot")
    independent.add_to_hass(hass)
    replacement = registry.async_get_or_create("vacuum", "matter", "r3-other", config_entry=independent,
                                                 suggested_object_id="r3_nominal")
    assert replacement.entity_id == original
    hass.states.async_set(original, "docked")
    hass.states.async_set("select.r3_nominal_mode", "Vacuum")
    await settle(hass)
    hass.states.async_set("select.r3_nominal_mode", "Vacuum and Mop;Deep Clean")
    await settle(hass)
    tanks = (await storage.async_get_state())["tank_states"]
    assert tanks[renamed]["nominal_time_resolution"]["status"] == "active"
    assert tanks[renamed]["nominal_time_resolution"]["sample_count"] == 3
    assert tanks[renamed]["nominal_time_resolution"]["accuracy"] == "not_established"
    assert tanks[renamed]["nominal_time_learning"]["contexts"][0]["context"]["device_id"] == original
    assert not (tanks.get(original, {}).get("nominal_time_learning") or {}).get("contexts")
