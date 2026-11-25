"""Public issue 26 contract, HA Core Ecovacs stable translation keys."""
from test_beta_runtime_path import _Hass, _S, discovery, effective, tick, sc
from vwmruntimepkg.health import robot_health


def test_discovery_and_tick_without_measurements_or_buttons_as_completion():
    roles={'sensor.area':'stats_area','sensor.time':'stats_time','number.water_flow_level':'water_amount',
           'select.mode':'work_mode','number.passes':'clean_count','binary_sensor.mop':'water_mop_attached',
           'sensor.station':'station_state','button.wash':'station_action'}
    entries=[{'entity_id':'vacuum.test','platform':'ecovacs','device_id':'d','unique_id':'vac'}]
    entries += [{'entity_id':e,'platform':'ecovacs','device_id':'d','unique_id':e,'translation_key':key}
                for e,key in roles.items()]
    descriptor=discovery.discover_descriptors(entries,[{'id':'d','manufacturer':'Ecovacs',
        'model_id':'k2iwaq','sw_version':'1.103.0'}],{})[0]
    device=effective({},descriptor)
    for key, entity in [('area_sensor','sensor.area'),('duration_sensor','sensor.time'),
                        ('mop_intensity_entity','number.water_flow_level'),('cleaning_mode_entity','select.mode'),
                        ('passes_entity','number.passes'),('mop_attached_sensor','binary_sensor.mop'),
                        ('dock_status_sensor','sensor.station')]:
        assert device.get(key)==entity
    assert not device.get('wash_completed_sensor')
    values={'vacuum.test':_S('cleaning'), 'sensor.area':_S('0',{'unit_of_measurement':'m²'}),
            'sensor.time':_S('0',{'unit_of_measurement':'min'}), 'number.water_flow_level':_S('23'),
            'select.mode':_S('mop'), 'number.passes':_S('1'), 'binary_sensor.mop':_S('on'),
            'sensor.station':_S('idle'), 'button.wash':_S('unknown')}
    def step(state,ts,**changes):
        for key,value in changes.items():
            if key=='sensor.area': values[key]=_S(str(value),{'unit_of_measurement':'m²'})
            elif key=='sensor.time': values[key]=_S(str(value),{'unit_of_measurement':'min'})
            else: values[key]=_S(str(value))
        return tick.tick_device(_Hass(values),device,state,now_ts=ts)[0]
    state=step({"used_ml":0},60000)
    assert state.get('session_start_ts')
    state=step(state,120000,**{'sensor.area':3,'sensor.time':2})
    assert state['last_area']==3 and state['used_ml']==0
    assert state['missing_usage_rate_reason']=='missing_area_rate'
    assert sc.estimate_water_state(device,state,{})['remaining_ml'] is None
    assert not state.get('split_session_observation',{}).get('valid')
    state=step(state,150000,**{'vacuum.test':'docked','sensor.station':'emptying_dustbin'})
    assert not state.get('wash_sequence_active') and state['used_ml']==0
    state=step(state,180000,**{'sensor.station':'washing_mop'})
    assert state['wash_sequence_active'] and state['used_ml']==0
    assert not state.get('verified_wash_active')
    state=step(state,240000,**{'sensor.station':'drying_mop','button.wash':'pressed'})
    assert state['used_ml']==0 and not state.get('last_wash_charged_ml')
    report=robot_health(device,device,state,sc.estimate_water_state(device,state,{}))
    checks={x['id'] for x in report['checks']}
    assert {'split_wash_completion_missing','split_water_measurement_missing'} <= checks
    measured={**device, 'wash_completed_sensor':'sensor.counter', 'water_volume_sensor':'sensor.volume',
              'water_volume_reservoir':'dock_clean'}
    checks={x['id'] for x in robot_health(measured,measured,state,sc.estimate_water_state(measured,state,{}))['checks']}
    assert not {'split_wash_completion_missing','split_water_measurement_missing'} & checks
    # A selected output is not wet evidence in a dry or sequential programme.
    assert not tick._is_mop_active('vacuum',None,True,None,mop_intensity='23',require_evidence=True)
    assert not tick._is_mop_active('mop_after_vacuum',None,True,None,mop_intensity='23',require_evidence=True)
    assert tick._is_mop_active('mop',None,True,None,mop_intensity='50',require_evidence=True)
    assert tick._is_mop_active('vacuum_and_mop',None,True,None,mop_intensity='23',require_evidence=True)
    dry=step({"used_ml":0},300000,**{'vacuum.test':'cleaning','select.mode':'vacuum','sensor.area':0,'sensor.station':'idle'})
    dry=step(dry,360000,**{'sensor.area':3})
    assert dry['used_ml']==0 and dry.get('missing_usage_rate_reason') is None
