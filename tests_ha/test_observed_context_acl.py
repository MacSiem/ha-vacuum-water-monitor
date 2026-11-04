"""Stored observation values respect native source permissions, including revocation."""
import asyncio
from .test_ha_runtime import DOMAIN, VACUUM, _setup

async def test_context_source_permissions_and_revocation(hass, hass_ws_client, local_auth, monkeypatch):
    from homeassistant.auth.models import Group
    from pytest_homeassistant_custom_component.common import MockUser
    from custom_components.ha_vacuum_water_monitor import websocket_api
    storage=await _setup(hass)
    source='number.private_wetness'
    observation={'value':'17','min':1,'max':32,'unit':None,'source_entity':source,'source':'frozen'}
    await storage.async_set_tank_state(VACUUM,{'initialized':True,'used_ml':20,
      'last_consumption_context':{'observed_settings':{'wetness_level':observation}}})
    both=Group(name='Both',policy={'entities':{'entity_ids':{VACUUM:{'read':True},source:{'read':True}}}})
    only=Group(name='Robot',policy={'entities':{'entity_ids':{VACUUM:{'read':True}}}})
    user=MockUser(name='Context reader',groups=[both]).add_to_hass(hass)
    token=await hass.auth.async_create_refresh_token(user,client_id='https://test.invalid/')
    client=await hass_ws_client(hass,hass.auth.async_create_access_token(token))
    await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
    result=(await client.receive_json())['result']['tank_states'][VACUUM]
    assert result['last_consumption_context']['observed_settings']['wetness_level']['value']=='17'
    ready,release=asyncio.Event(),asyncio.Event();original=websocket_api._filtered_result
    async def pause(hass_,user_id,value):
        data=await original(hass_,user_id,value);ready.set();await release.wait();return data
    monkeypatch.setattr(websocket_api,'_filtered_result',pause)
    await client.send_json_auto_id({'type':f'{DOMAIN}/get_state'})
    await asyncio.wait_for(ready.wait(),3);user.groups=[only];release.set()
    result=await client.receive_json()
    if result['success']:
        obs=result['result']['tank_states'][VACUUM]['last_consumption_context']['observed_settings']['wetness_level']
        assert obs['value'] is None and obs['source_entity'] is None and obs['restricted'] is True
