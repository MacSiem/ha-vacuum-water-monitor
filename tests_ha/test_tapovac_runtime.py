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


async def test_tapovac_attribute_updates_reach_native_accounting_and_store(hass):
    upstream = MockConfigEntry(domain="tapo_rv30", title="Synthetic TapoVac")
    upstream.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("tapo_rv30", "synthetic")}, manufacturer="Tapo", model="RV50 Pro Omni")
    registry = er.async_get(hass)
    registry.async_get_or_create("vacuum", "tapo_rv30", upstream.entry_id + "_vacuum",
        device_id=dev.id, config_entry=upstream, suggested_object_id="tapo")
    registry.async_get_or_create("select", "tapo_rv30", upstream.entry_id + "_area_unit",
        device_id=dev.id, config_entry=upstream, suggested_object_id="tapo_unit")
    # Authored mode binding is explicit. It is not inferred from a Matter name.
    hass.states.async_set("select.confirmed_robot_mode", "Vacuum and Mop;Deep Clean")
    hass.states.async_set("select.tapo_unit", "m²")
    def update(area, code=1, mode=None):
        if mode is not None:
            hass.states.async_set("select.confirmed_robot_mode", mode)
        hass.states.async_set("vacuum.tapo", "cleaning", {"status_code": code,
            "clean_area": area, "clean_time_min": area, "water_level": "low", "mop_attached": True})
    update(0)
    entry = MockConfigEntry(domain=DOMAIN, title="VWM", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    storage = hass.data[DOMAIN]["storage"]
    await storage.async_set_settings({"configured_devices": [{"vacuum_entity": "vacuum.tapo",
        "cleaning_mode_entity": "select.confirmed_robot_mode", "rate_signal": "mop_intensity",
        "usage_ml_per_m2": {"low": 2}, "accounting_evidence": "user_calibration"}]})
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": "vacuum.tapo"}, blocking=True)
    await settle(hass)
    update(2)
    await settle(hass)
    tank = (await storage.async_get_state())["tank_states"]["vacuum.tapo"]
    assert tank["used_ml"] == 4
    # Same vacuum state, attribute-only mode/status change must wake the ticker.
    update(4, code=2)
    await settle(hass)
    assert (await storage.async_get_state())["tank_states"]["vacuum.tapo"]["used_ml"] == 4
    update(6, mode="Vacuum")
    await settle(hass)
    assert (await storage.async_get_state())["tank_states"]["vacuum.tapo"]["used_ml"] == 4
    assert "select.tapo_unit" in hass.data[DOMAIN]["ticker"].entities
    await storage.async_save()
    persisted = await storage._store.async_load()
    assert persisted["tank_states"]["vacuum.tapo"]["used_ml"] == 4
