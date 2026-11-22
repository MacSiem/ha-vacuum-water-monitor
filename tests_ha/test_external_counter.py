"""DIY counter is authoritative without mutating VWM's saved balance."""
import pytest
from homeassistant.helpers import entity_registry as er
from .test_ha_runtime import DOMAIN, VACUUM, _setup, _settle


async def test_external_counter_updates_public_state_and_sensors_without_store_writes(hass, hass_ws_client):
    storage = await _setup(hass)
    helper = 'input_number.diy_used'
    hass.states.async_set(helper, '500', {'unit_of_measurement': 'mL'})
    await storage.async_set_settings({'configured_devices': [{'vacuum_entity': VACUUM, 'water_total_ml': 4000, 'water_used_input': helper}]})
    await storage.async_set_tank_state(VACUUM, {'initialized': True, 'used_ml': 125, 'water_empty_active': True, 'accounting_incomplete': True, 'water_anchor_kind': 'empty', 'water_anchor_confidence': 'legacy', 'cycle_full_confirmed': True})
    from custom_components.ha_vacuum_water_monitor.robots import async_notify
    async_notify(hass, {'settings': await storage.async_get_settings()})
    await hass.data[DOMAIN]['ticker'].run(None)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    async def get(i):
        await client.send_json({'id': i, 'type': f'{DOMAIN}/get_state'})
        response = await client.receive_json()
        assert response['success']
        return response['result']['tank_states'][VACUUM]['external_counter']
    assert (await get(1))['used_ml'] == 500
    await client.send_json({'id': 11, 'type': f'{DOMAIN}/get_state'})
    view=(await client.receive_json())['result']['tank_states'][VACUUM]
    assert view['water_empty_active'] is False and view['accounting_incomplete'] is False and view['water_anchor_kind'] is None
    assert view['cycle_full_confirmed'] is False
    registry = er.async_get(hass)
    entity = next(e.entity_id for e in registry.entities.values() if e.platform == DOMAIN and e.unique_id.endswith('_water_used_since_refill') and 'robot' in e.unique_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(entity).state) == 500
    assert hass.states.get(entity).attributes['water_empty_active'] is False
    assert hass.states.get(entity).attributes['accounting_incomplete'] is False
    old=(await storage.async_get_state())['tank_states'][VACUUM]
    assert old['water_empty_active'] is True and old['accounting_incomplete'] is True and old['water_anchor_kind']=='empty'
    hass.states.async_set(helper, '1.5', {'unit_of_measurement': 'L'})
    await _settle(hass)
    assert (await get(12))['used_ml'] == 1500
    assert float(hass.states.get(entity).state) == 1500
    assert (await storage.async_get_state())['tank_states'][VACUUM]['used_ml'] == 125
    hass.states.async_set(helper, 'unavailable', {'unit_of_measurement': 'mL'})
    await _settle(hass)
    assert (await get(13))['used_ml'] is None
    assert hass.states.get(entity).state in ('unknown', 'unavailable')
    assert (await storage.async_get_state())['tank_states'][VACUUM]['used_ml'] == 125
    from custom_components.ha_vacuum_water_monitor.robots import async_mark_refilled
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError, match='external water counter'):
        await async_mark_refilled(hass, VACUUM, 'entity')
    assert (await storage.async_get_state())['tank_states'][VACUUM]['used_ml'] == 125


async def test_external_precedence_units_zero_and_self_reference(hass):
    from custom_components.ha_vacuum_water_monitor.external_counter import project_external_counter
    from custom_components.ha_vacuum_water_monitor.sensor_calculations import estimate_water_state
    hass.states.async_set('input_number.used', '0', {'unit_of_measurement': 'mL'})
    hass.states.async_set('sensor.remaining', '2.5', {'unit_of_measurement': 'L'})
    d={'vacuum_entity':VACUUM,'water_total_ml':4000,'water_used_input':'input_number.used','water_sensor':'sensor.remaining'}
    projected=project_external_counter(hass,d)
    result=estimate_water_state(d,{'external_counter':projected},{})
    assert result['used_ml']==1500 and result['remaining_ml']==2500
    d['water_used_sensor']='sensor.used'
    hass.states.async_set('sensor.used','1.25',{'unit_of_measurement':'L'})
    assert project_external_counter(hass,d)['used_ml']==1500
    hass.states.async_set('sensor.used','-1',{'unit_of_measurement':'L'})
    assert project_external_counter(hass,d)['used_ml']==1500
    d.pop('water_used_sensor')
    hass.states.async_set('sensor.remaining','50',{'unit_of_measurement':'%'})
    result=estimate_water_state(d,{'external_counter':project_external_counter(hass,d)},{})
    assert result['remaining_ml'] is None and result['used_ml'] is None
    entry=er.async_get(hass).async_get_or_create('sensor', DOMAIN, 'external_loop', suggested_object_id='external_loop')
    hass.states.async_set(entry.entity_id,'2',{'unit_of_measurement':'L'})
    d['water_sensor']=entry.entity_id
    assert project_external_counter(hass,d)['remaining_ml'] is None

async def test_external_sources_obey_native_read_and_last_helpers(hass, hass_ws_client, monkeypatch):
    from custom_components.ha_vacuum_water_monitor import feature_access
    from custom_components.ha_vacuum_water_monitor.external_counter import project_external_counter
    storage=await _setup(hass)
    hass.states.async_set('input_number.used','0',{'unit_of_measurement':'mL'})
    hass.states.async_set('sensor.session','0.25',{'unit_of_measurement':'L'})
    hass.states.async_set('input_datetime.refill','2026-11-04 08:00:00')
    device={'vacuum_entity':VACUUM,'water_used_input':'input_number.used','last_session_sensor':'sensor.session','last_reset_entity':'input_datetime.refill'}
    await storage.async_set_settings({'configured_devices':[device]})
    projected=project_external_counter(hass,device)
    assert projected['used_ml']==0 and projected['last_session_ml']==250 and projected['last_reset']=='2026-11-04 08:00:00'
    client=await hass_ws_client(hass)
    original=feature_access.check_native_read
    async def deny_source(hass_,user_id,entities):
        return False if 'input_number.used' in entities else await original(hass_,user_id,entities)
    monkeypatch.setattr(feature_access,'check_native_read',deny_source)
    await client.send_json({'id':1,'type':f'{DOMAIN}/get_state'})
    response=await client.receive_json()
    assert response['success'] and response['result']['tank_states'][VACUUM]['external_counter']['used_ml'] is None
    await client.send_json({'id':2,'type':f'{DOMAIN}/set_settings','patch':{'configured_devices':[device]},'partial':True})
    assert not (await client.receive_json())['success']

async def test_external_helper_acl_with_real_users(hass, hass_ws_client, local_auth):
    from homeassistant.auth.models import Group
    from pytest_homeassistant_custom_component.common import MockUser
    storage=await _setup(hass)
    hass.states.async_set('input_number.private_used','500',{'unit_of_measurement':'mL'})
    await storage.async_set_settings({'configured_devices':[{'vacuum_entity':VACUUM,'water_used_input':'input_number.private_used'}]})
    for source_allowed in (False,True):
        ids={VACUUM:{'read':True}}
        if source_allowed: ids['input_number.private_used']={'read':True}
        user=MockUser(name='External counter reader',groups=[Group(name='Scoped',policy={'entities':{'entity_ids':ids}})]).add_to_hass(hass)
        refresh=await hass.auth.async_create_refresh_token(user,client_id='https://r7-test.invalid/')
        client=await hass_ws_client(hass,hass.auth.async_create_access_token(refresh))
        await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
        response=await client.receive_json()
        assert response['success']
        data=response['result']; counter=data['tank_states'][VACUUM]['external_counter']
        assert counter['used_ml']==(500 if source_allowed else None)
        if not source_allowed: assert 'input_number.private_used' not in repr(data)

async def test_external_counter_works_without_stored_baseline(hass, hass_ws_client):
    storage=await _setup(hass)
    hass.states.async_set('input_number.zero','0',{'unit_of_measurement':'mL'})
    await storage.async_set_settings({'configured_devices':[{'vacuum_entity':VACUUM,'water_used_input':'input_number.zero','water_total_ml':4000}]})
    before=await storage.async_get_state()
    client=await hass_ws_client(hass)
    await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
    response=await client.receive_json()
    assert response['success'] and response['result']['tank_states'][VACUUM]['external_counter']['used_ml']==0
    assert await storage.async_get_state()==before

async def test_external_source_revoked_after_async_projection_is_not_returned(hass, hass_ws_client, local_auth, monkeypatch):
    import asyncio
    from homeassistant.auth.models import Group
    from pytest_homeassistant_custom_component.common import MockUser
    from custom_components.ha_vacuum_water_monitor import websocket_api
    storage=await _setup(hass)
    hass.states.async_set('input_number.private_used','500',{'unit_of_measurement':'mL'})
    await storage.async_set_settings({'configured_devices':[{'vacuum_entity':VACUUM,'water_used_input':'input_number.private_used'}]})
    all_group=Group(name='Both',policy={'entities':{'entity_ids':{VACUUM:{'read':True},'input_number.private_used':{'read':True}}}})
    robot_group=Group(name='Robot only',policy={'entities':{'entity_ids':{VACUUM:{'read':True}}}})
    user=MockUser(name='ACL race',groups=[all_group]).add_to_hass(hass)
    refresh=await hass.auth.async_create_refresh_token(user,client_id='https://r7-test.invalid/')
    client=await hass_ws_client(hass,hass.auth.async_create_access_token(refresh))
    original=websocket_api._filtered_result; ready,release=asyncio.Event(),asyncio.Event()
    async def pause(hass_,user_id,value):
        result=await original(hass_,user_id,value)
        ready.set();await release.wait();return result
    monkeypatch.setattr(websocket_api,'_filtered_result',pause)
    await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
    await asyncio.wait_for(ready.wait(),3)
    user.groups=[robot_group]
    release.set();response=await client.receive_json()
    assert not response['success'] or response['result']['tank_states'][VACUUM]['external_counter']['used_ml'] is None

@pytest.mark.parametrize('kind', ['water_used_sensor','water_sensor'])
async def test_standalone_sensor_is_authoritative_without_input(hass, kind):
    from custom_components.ha_vacuum_water_monitor.external_counter import project_external_counter, source_entities
    from custom_components.ha_vacuum_water_monitor.sensor_calculations import estimate_water_state
    from custom_components.ha_vacuum_water_monitor.tick import _has_user_priv_helpers
    hass.states.async_set('sensor.diy','1.5',{'unit_of_measurement':'L'})
    d={'vacuum_entity':VACUUM,'water_total_ml':4000,kind:'sensor.diy'}
    p=project_external_counter(hass,d); assert p is not None and 'sensor.diy' in source_entities(d)
    result=estimate_water_state(d,{'external_counter':p,'used_ml':125,'initialized':True},{})
    assert _has_user_priv_helpers(hass,d)
    if kind=='water_sensor': assert result['remaining_ml']==1500 and result['used_ml']==2500
    else: assert result['used_ml']==1500 and result['remaining_ml']==2500
    assert result['nominal_time_resolution']=={} and result['calibration_samples']==0


async def test_auxiliary_hooks_do_not_disable_automatic_accounting(hass,hass_ws_client):
    from custom_components.ha_vacuum_water_monitor.tick import _has_user_priv_helpers
    storage=await _setup(hass)
    hass.states.async_set('sensor.session','0.2',{'unit_of_measurement':'L'})
    hass.states.async_set('input_datetime.refill','2026-11-04 08:00:00')
    d={'vacuum_entity':VACUUM,'last_session_sensor':'sensor.session','last_reset_entity':'input_datetime.refill'}
    assert not _has_user_priv_helpers(hass,d)
    await storage.async_set_settings({'configured_devices':[d]})
    client=await hass_ws_client(hass);await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
    result=(await client.receive_json())['result']['tank_states'][VACUUM]
    assert 'external_counter' not in result
    assert result['external_metadata']['last_session_ml']==200 and result['external_metadata']['last_reset']=='2026-11-04 08:00:00'

async def test_external_counter_suppresses_forecast_and_old_confidence(hass):
    from custom_components.ha_vacuum_water_monitor.sensor import CleaningsLeftSensor
    from custom_components.ha_vacuum_water_monitor.sensor_calculations import estimate_water_state
    from custom_components.ha_vacuum_water_monitor.external_counter import project_external_counter
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    hass.states.async_set('input_number.used','500',{'unit_of_measurement':'mL'})
    device={'vacuum_entity':VACUUM,'water_total_ml':4000,'water_used_input':'input_number.used'}
    tank={'initialized':True,'used_ml':125,'calibration_factor':1.8,'calibration_samples':8,
          'nominal_time_resolution':{'status':'active'},'external_counter':project_external_counter(hass,device)}
    estimate=estimate_water_state(device,tank,{})
    assert estimate['nominal_time_resolution']=={} and estimate['calibration_factor'] is None and estimate['calibration_samples']==0
    assert estimate['cycle_full_confirmed'] is False and estimate['water_anchor_kind'] is None
    sensor=CleaningsLeftSensor(hass,MockConfigEntry(domain=DOMAIN),device)
    async def context(): return {},tank
    sensor._store_context=context
    await sensor.async_update()
    assert sensor.native_value is None and sensor.extra_state_attributes['basis_runs']==0
