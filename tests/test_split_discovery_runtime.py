"""Saved measurements reach ordinary discovered-device accounting."""
import asyncio
from copy import deepcopy
from unittest.mock import patch

from test_beta_runtime_path import tick, discovery, _Hass, _S
from test_user_device_removal import storage
from test_local_measurements import measurement


def test_saved_split_rates_reach_discovered_tick_and_do_not_survive_setting_change():
    async def run():
        entity='vacuum.synthetic'
        roles={'sensor.area':'cleaning_area','sensor.status':'status',
               'number.water':'mop_intensity','select.clean':'cleaning_mode',
               'binary_sensor.mop':'mop_attached'}
        entries=[{'entity_id':entity,'platform':'roborock','unique_id':'vac','device_id':'d'}]
        entries += [{'entity_id':key,'platform':'roborock','unique_id':key,'device_id':'d',
                     'translation_key':value} for key,value in roles.items()]
        entries += [{'entity_id':'sensor.completed','platform':'roborock','unique_id':'completed','device_id':'d'}]
        desc=discovery.discover_descriptors(entries,[{'id':'d','manufacturer':'Roborock',
            'model_id':'synthetic.unlisted','model':'synthetic.unlisted'}],
            {item['entity_id']:{'state':'1','attributes':{}} for item in entries})[0]
        assert desc['usage_ml_per_m2'] == {} and desc['usage_ml_per_active_minute'] == {}
        st=storage.VacuumWaterStorage(None)
        await st.async_set_settings({'configured_devices':[{'vacuum_entity':entity,'tracked_reservoir':'dock_clean','calibration_scope':'floor_only'}],
                                    'signal_overrides':{entity:{'wash_completed_sensor':'sensor.completed'}}})
        await st.async_set_measurement_plan(entity,{'confirmed':True, 'split_no_unmeasured_transfer':True,
             'dock_variant':'dock','firmware':'1','integration_version':'1',
             'settings':{'mop_mode':'standard','wash_mode':'standard'}})
        values={entity:_S('cleaning'), 'sensor.status':_S('cleaning'),
                'sensor.area':_S('0',{'unit_of_measurement':'m²'}), 'number.water':_S('23'),
                'select.clean':_S('mop'), 'binary_sensor.mop':_S('on'), 'sensor.completed':_S('0')}
        h=_Hass(values)
        def effective():
            return tick._devices_to_tick(h,stored['settings'],stored['tank_states'],stored)[0]
        with patch.object(tick,'list_vacuums',return_value=[desc]):
            stored=await st.async_get_state()
            state=tick.tick_device(h,effective(),{},now_ts=60000)[0]
            identity=state['split_session_observation']['identity']
            assert identity
            for i,(area,wash) in enumerate([(0,1),(10,0),(20,1),(25,1)]):
                ts=1000+i
                obs={'id':f'sample.{ts}', 'identity':deepcopy(identity), 'quality':dict(tick.split_observation.QUALITY),
                     'area_m2':area,'wash_count':wash}
                await st.async_set_tank_state(entity,{'automatic_sessions':[{'ts':ts,'split_observation':obs}]})
                result=await st.async_save_measurement(entity,0,ts,{**measurement(),'observed_ml':3.5*area+30*wash,
                    'resolution_ml':1, 'purpose':'validation' if i==3 else 'training'})
            assert result['split_calibration']['floor_ml_per_m2'] == 3.5
            stored=await st.async_get_state()
            state=tick.tick_device(h,effective(),{},now_ts=120000)[0]
            assert state['consumption_resolution']['source']=='split_learning'
            assert state['split_resolution']['reason']=='qualified'
            values['sensor.area']=_S('25',{'unit_of_measurement':'m²'})
            state=tick.tick_device(h,effective(),state,now_ts=180000)[0]
            assert state['used_ml']==87.5
            values['number.water']=_S('99'); values['sensor.area']=_S('26',{'unit_of_measurement':'m²'})
            values['sensor.status']=_S('docked'); values[entity]=_S('docked')
            changed=tick.tick_device(h,effective(),deepcopy(state),now_ts=240000)[0]
            assert changed['used_ml']==87.5
            assert changed['split_resolution']['reason']=='no_compatible_rate'
            values['number.water']=_S('23'); values['sensor.area']=_S('25',{'unit_of_measurement':'m²'})
            values[entity]=_S('cleaning')
            values['sensor.status']=_S('washing_the_mop')
            state=tick.tick_device(h,effective(),state,now_ts=240000)[0]
            values['sensor.status']=_S('docked');values[entity]=_S('docked');values['sensor.completed']=_S('1')
            state=tick.tick_device(h,effective(),state,now_ts=300000)[0]
            assert state['used_ml']==117.5
            values['number.water']=_S('99');values['sensor.area']=_S('26',{'unit_of_measurement':'m²'})
            state=tick.tick_device(h,effective(),state,now_ts=360000)[0]
            assert state['used_ml']==117.5
            assert state['split_resolution']['reason']=='no_compatible_rate'
    asyncio.run(run())


def test_idle_baseline_rejects_previous_process_epoch():
    observer=tick.split_observation
    state={}
    d={'vacuum_entity':'vacuum.test','tracked_reservoir':'dock_clean',
       'wash_completed_sensor':'sensor.count','split_no_unmeasured_transfer':True}
    ctx={'dock_variant':'dock','firmware':'1','integration_id':'test','integration_version':'1'}
    settings={'mop_mode':'wet','water_level':'high','cleaning_mode':'mop','wash_mode_entity':'normal'}
    def observe(now, status, washing):
        observer.observe(state,d,ctx,settings,now=now,area=5.,wet=True,cleaning=False,washing=washing,
                         completed=0.,volume=None,resolution=None,volume_binding_ok=False,
                         max_interval=180000,max_area=25,status=status)
    observe(60000,'docked',False)
    state['split_idle_baseline']['epoch']='previous-process'
    state['session_start_ts']=120000
    observe(120000,'washing_the_mop',True)
    assert not state['split_session_observation']['valid']
