"""Native HA registries and ordinary state-change accounting for TapoVac."""
from datetime import timedelta

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
    # The regular heartbeat adopts changed settings before new exposure.
    await hass.data[DOMAIN]["ticker"].run(None)
    await settle(hass)
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": "vacuum.tapo"}, blocking=True)
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
