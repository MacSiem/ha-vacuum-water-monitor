"""Registry identity, rather than a mutable entity_id, owns observed setting banks."""
from homeassistant.helpers import entity_registry as er, device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from homeassistant.auth.models import Group
from .test_ha_runtime import DOMAIN,VACUUM,_setup

async def test_source_rename_acl_old_id_reuse_and_real_replacement(hass,hass_ws_client,local_auth):
 storage=await _setup(hass);registry=er.async_get(hass);vac=registry.async_get(VACUUM)
 entry=hass.config_entries.async_get_entry(vac.config_entry_id)
 setting=registry.async_get_or_create('select','roborock','robot_cycles_unique',device_id=vac.device_id,
     config_entry=entry,suggested_object_id='robot_cycles',translation_key='cleaning_cycles')
 old=setting.entity_id;stable_id=setting.id;hass.states.async_set(old,'1')
 client=await hass_ws_client(hass)
 async def refresh():
  await client.send_json_auto_id({'type':f'{DOMAIN}/refresh_bindings'})
  result=await client.receive_json();assert result['success'],result
  await hass.data[DOMAIN]['ticker'].run(None);await hass.async_block_till_done()
 await refresh()
 s=(await storage.async_get_state())['tank_states'][VACUUM]
 assert s['last_consumption_context']['observed_settings']['cleaning_cycles']['source_registry_id']==stable_id
 old_context=s['last_consumption_context'];old_digest=s['accounting_calibration_context']
 s.update(calibration_factor=1.3,calibration_samples=3)
 s['automatic_sessions']=[{'ts':123,'context':old_context,'water':50}]
 await storage.async_set_tank_state(VACUUM,s)
 renamed='select.renamed_cycles'
 registry.async_update_entity(old,new_entity_id=renamed)
 hass.states.async_remove(old);hass.states.async_set(renamed,'1')
 await refresh()
 s=(await storage.async_get_state())['tank_states'][VACUUM]
 assert s['accounting_calibration_context']==old_digest
 assert s['calibration_factor']==1.3 and s['calibration_samples']==3
 assert s['automatic_sessions'][0]['context']['observed_settings']['cleaning_cycles']['source_entity']==old
 # Reusing the old id on a foreign device must not redirect historical ACL.
 foreign=MockConfigEntry(domain='foreign',title='Foreign');foreign.add_to_hass(hass)
 foreign_device=dr.async_get(hass).async_get_or_create(config_entry_id=foreign.entry_id,identifiers={('foreign','other')})
 registry.async_get_or_create('select','foreign','other_cycles_unique',device_id=foreign_device.id,
      config_entry=foreign,suggested_object_id='robot_cycles',translation_key='cleaning_cycles')
 group=Group(name='Current source',policy={'entities':{'entity_ids':{VACUUM:{'read':True},renamed:{'read':True}}}})
 user=MockUser(name='Scoped observer',groups=[group]).add_to_hass(hass)
 token=await hass.auth.async_create_refresh_token(user,client_id='https://test.invalid/')
 scoped=await hass_ws_client(hass,hass.auth.async_create_access_token(token))
 await scoped.send_json_auto_id({'type':f'{DOMAIN}/get_state'});result=await scoped.receive_json();assert result['success']
 obs=result['result']['tank_states'][VACUUM]['automatic_sessions'][0]['context']['observed_settings']['cleaning_cycles']
 assert obs['value']=='1' and obs['source_entity']==renamed
 # An actual replacement on the same device gets a new stable id and bank.
 registry.async_remove(renamed);hass.states.async_remove(renamed)
 replacement=registry.async_get_or_create('select','roborock','different_cycles_unique',device_id=vac.device_id,
     config_entry=entry,suggested_object_id='renamed_cycles',translation_key='cleaning_cycles')
 hass.states.async_set(replacement.entity_id,'1');await refresh()
 s=(await storage.async_get_state())['tank_states'][VACUUM]
 assert replacement.id!=stable_id and s['accounting_calibration_context']!=old_digest
 assert s['calibration_factor']==1 and s['calibration_samples']==0
 assert s['nominal_calibration_contexts'][old_digest]['calibration_factor']==1.3
 # Even if the same locator is allowed, the deleted source UUID cannot be resolved.
 await scoped.send_json_auto_id({'type':f'{DOMAIN}/get_state'});result=await scoped.receive_json();assert result['success']
 obs=result['result']['tank_states'][VACUUM]['automatic_sessions'][0]['context']['observed_settings']['cleaning_cycles']
 assert obs['value'] is None and obs['restricted'] is True
