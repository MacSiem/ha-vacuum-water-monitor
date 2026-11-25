"""Real split observer, resolver and normal accounting tick."""
from test_tick import tick, _Hass, _State
from test_split_observation_tick import test_normal_tick_records_completed_wash_and_wet_area


def test_real_rates_follow_current_context_and_counter():
    d = {'vacuum_entity':'vacuum.test', 'tracked_reservoir':'dock_clean', 'dock_variant':'dock1',
         'firmware':'1', 'integration_adapter':'test', 'integration_version':'1',
         'area_sensor':'sensor.area', 'mop_mode_entity':'select.mop',
         'cleaning_mode_entity':'select.clean', 'mop_intensity_entity':'select.water',
         'wash_mode_entity':'select.wash', 'wash_completed_sensor':'sensor.completed',
         'split_no_unmeasured_transfer': True, 'intensity_factor':{'high':3}}
    def step(s, ts, status, area, count, mode='wet'):
        h = _Hass({'vacuum.test':_State(status), 'sensor.area':_State(str(area), {'unit_of_measurement':'m²'}),
                   'select.mop':_State(mode), 'select.clean':_State('mopping'), 'select.water':_State('high'),
                   'select.wash':_State('normal'), 'sensor.completed':_State(str(count))})
        return tick.tick_device(h,d,s,now_ts=ts)[0]
    state = step({'used_ml':0,'calibration_factor':2}, 60000, 'cleaning',0,0)
    identity = state['split_session_observation']['identity']
    assert identity is not None
    quality = dict(tick.split_observation.QUALITY)
    samples = []
    for i, (area, wash) in enumerate([(10,0),(20,0),(30,0),(40,0),(0,1),(0,2),(0,3),(0,4)]):
        samples.append({'id':str(i),'identity':identity, 'quality':quality,'area_m2':area,'wash_count':wash,
                        'observed_ml':5*area+80*wash,'resolution_ml':1,
                        'source':'measured_refill' if i%2 else 'bound_reservoir_sensor',
                        'purpose':'validation' if i in (3,7) else 'training'})
    d['split_measurements'] = samples[:4]
    state['split_sensor_measurements'] = samples[4:]
    state = step(state,120000,'cleaning',2,0)
    assert state['used_ml'] == 10
    state = step(state,180000,'washing_the_mop',2,0)
    state = step(state,240000,'washing_the_mop',2,0)
    assert state['used_ml'] == 10
    state = step(state,300000,'docked',2,1)
    assert state['used_ml'] == 90
    state = step(state,360000,'docked',2,1)
    assert state['used_ml'] == 90
    d['water_volume_sensor'] = 'sensor.missing'
    state = step(state,420000,'cleaning',4,1)
    assert state['used_ml'] == 90


def test_action_contexts_are_independent():
    observer = tick.split_observation
    device = {'vacuum_entity':'vacuum.test', 'tracked_reservoir':'dock_clean',
              'split_no_unmeasured_transfer':True, 'wash_completed_sensor':'sensor.count'}
    context = {'dock_variant':'dock', 'firmware':'1', 'integration_id':'test', 'integration_version':'1'}
    settings = {'cleaning_mode':'mopping','mop_mode':'wet','water_level':'high','wash_mode_entity':'normal',
                'observed_settings':{'route':{'value':'standard'},'wash_mode':{'value':'normal'}}}
    original = observer.identity(device, context, settings)
    changed = {**settings, 'mop_mode':'dry', 'observed_settings':{'route':{'value':'other'}, 'wash_mode':{'value':'normal'}}}
    other = observer.identity(device, context, changed)
    assert original['floor_context'] != other['floor_context']
    assert original['wash_context'] == other['wash_context']
