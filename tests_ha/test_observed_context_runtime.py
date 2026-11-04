"""HA registry discovery and event update of an optional observed setting."""
from homeassistant.helpers import entity_registry as er
from .test_ha_runtime import DOMAIN, VACUUM, _setup, _settle

async def test_registry_control_refresh_and_ordinary_event(hass, hass_ws_client):
    storage=await _setup(hass)
    registry=er.async_get(hass); vacuum=registry.async_get(VACUUM)
    entity=registry.async_get_or_create('select','roborock','robot_cleaning_cycles',
        device_id=vacuum.device_id,config_entry=hass.config_entries.async_get_entry(vacuum.config_entry_id),
        suggested_object_id='robot_cleaning_cycles',translation_key='cleaning_cycles')
    hass.states.async_set(entity.entity_id,'1')
    client=await hass_ws_client(hass)
    await client.send_json_auto_id({'type':f'{DOMAIN}/refresh_bindings'})
    assert (await client.receive_json())['success']
    assert entity.entity_id in hass.data[DOMAIN]['ticker'].entities
    await hass.services.async_call(DOMAIN,'mark_refilled',{'entity_id':VACUUM},blocking=True)
    await hass.data[DOMAIN]['ticker'].run(None)
    old=(await storage.async_get_state())['tank_states'][VACUUM]
    assert old['last_consumption_context']['observed_settings']['cleaning_cycles']['value']=='1'
    hass.states.async_set(entity.entity_id,'2')
    await _settle(hass)
    new=(await storage.async_get_state())['tank_states'][VACUUM]
    assert new['last_consumption_context']['observed_settings']['cleaning_cycles']['value']=='2'
    assert new['used_ml']==old['used_ml']
