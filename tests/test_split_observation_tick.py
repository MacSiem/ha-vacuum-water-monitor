"""The normal tick collects exposure independently of a configured water rate."""
from test_tick import tick, _Hass, _State


def test_normal_tick_records_completed_wash_and_wet_area():
    device = {"vacuum_entity": "vacuum.test", "measurement_identity": "robot-1",
              "status_sensor": "sensor.status", "area_sensor": "sensor.area",
              "cleaning_mode_entity": "select.clean", "mop_mode_entity": "select.mop",
              "mop_intensity_entity": "select.water", "wash_mode_entity": "select.wash",
              "wash_completed_sensor": "sensor.completed", "tracked_reservoir": "dock_clean",
              "dock_variant": "dock-1", "firmware": "1", "integration_adapter": "test",
              "integration_version": "1", "split_no_unmeasured_transfer": True}
    def step(state, ts, status, area, count):
        values = {"vacuum.test": _State("docked" if status == "docked" else "cleaning"),
                  "sensor.status": _State(status), "sensor.area": _State(str(area), {"unit_of_measurement": "m²"}),
                  "select.clean": _State("mopping"), "select.mop": _State("standard"),
                  "select.water": _State("medium"), "select.wash": _State("standard"),
                  "sensor.completed": _State(str(count))}
        return tick.tick_device(_Hass(values), device, state, now_ts=ts)[0]
    state = step({}, 1_000_000, "mopping", 0, 0)
    state = step(state, 1_060_000, "mopping", 2, 0)
    state = step(state, 1_120_000, "washing_mop", 2, 0)
    state = step(state, 1_180_000, "mopping", 2, 1)
    state = step(state, 1_240_000, "mopping", 3, 1)
    state = step(state, 1_300_000, "docked", 3, 1)
    sample = state["automatic_sessions"][0]["split_observation"]
    assert sample["area_m2"] == 3
    assert sample["wash_count"] == 1
    assert "observed_ml" not in sample


def test_sensor_observations_use_a_persistent_fourth_holdout_and_reject_rise():
    observer = tick.split_observation
    device = {"vacuum_entity": "vacuum.test", "tracked_reservoir": "dock_clean",
              "wash_completed_sensor": "sensor.completed", "split_no_unmeasured_transfer": True,
              "water_volume_sensor": "sensor.tank"}
    context = {"dock_variant": "dock", "firmware": "1", "integration_id": "test", "integration_version": "1"}
    settings = {"cleaning_mode": "mopping", "mop_mode": "standard", "water_level": "medium", "wash_mode_entity": "standard"}
    state = {"last_water_volume_ml": 500.0, "session_exposure_complete": True}
    def cycle(start, increase=False):
        state["session_start_ts"] = start
        for offset, area, washing, count, volume in [(0, 0., False, 0., 500.), (1, 2., False, 0., 480.),
                                                     (2, 2., True, 0., 470.), (3, 2., False, 1., 490. if increase else 450.)]:
            observer.observe(state, device, context, settings, now=start + offset * 1000, area=area,
                             wet=True, cleaning=not washing, washing=washing, completed=count,
                             volume=volume, resolution=1., volume_binding_ok=True,
                             max_interval=2000, max_area=10.)
        record = {}
        observer.finish(state, record, "docked")
        return record
    for i in range(4):
        assert "split_observation" in cycle(10000 + i * 10000)
    assert [s["purpose"] for s in state["split_sensor_measurements"]] == ["training"] * 3 + ["validation"]
    assert "split_observation" not in cycle(60000, increase=True)
    assert len(state["split_sensor_measurements"]) == 4


def test_standalone_wash_requires_direct_idle_and_equal_counter():
    device = {'vacuum_entity':'vacuum.test', 'status_sensor':'sensor.status', 'area_sensor':'sensor.area',
              'cleaning_mode_entity':'select.clean', 'mop_mode_entity':'select.mop',
              'mop_intensity_entity':'select.water', 'wash_mode_entity':'select.wash',
              'wash_completed_sensor':'sensor.completed', 'tracked_reservoir':'dock_clean',
              'dock_variant':'dock', 'firmware':'1', 'integration_adapter':'test',
              'integration_version':'1', 'split_no_unmeasured_transfer':True}
    def step(s, ts, status, count):
        h = _Hass({'vacuum.test':_State('docked'), 'sensor.status':_State(status),
                   'sensor.area':_State('7', {'unit_of_measurement':'m²'}),
                   'sensor.completed':_State(str(count)), 'select.clean':_State('mopping'),
                   'select.mop':_State('wet'), 'select.water':_State('high'), 'select.wash':_State('normal')})
        return tick.tick_device(h,device,s,now_ts=ts)[0]
    s=step({},60000,'docked',0)
    s=step(s,120000,'washing_the_mop',0)
    s=step(s,180000,'docked',1)
    assert s['automatic_sessions'][0]['split_observation']['wash_count'] == 1
    s=step({},60000,'docked',0)
    s=step(s,120000,'washing_the_mop',1)
    s=step(s,180000,'docked',2)
    assert 'split_observation' not in s['automatic_sessions'][0]


def test_idle_baseline_updates_do_not_schedule_store_writes():
    before = {'last_tick_ts': 60000, 'split_idle_baseline': {'ts': 60000}, 'used_ml': 1}
    after = {'last_tick_ts': 120000, 'split_idle_baseline': {'ts': 120000}, 'used_ml': 1}
    assert tick._only_tick_timestamp_changed(before, after)
    after['used_ml'] = 2
    assert not tick._only_tick_timestamp_changed(before, after)


def test_sensor_fresh_sessions_survive_old_binding_gap_but_not_new_gaps_or_rises():
    device = {'vacuum_entity':'vacuum.test', 'status_sensor':'sensor.status', 'area_sensor':'sensor.area',
              'cleaning_mode_entity':'select.clean', 'mop_mode_entity':'select.mop',
              'mop_intensity_entity':'select.water', 'wash_mode_entity':'select.wash',
              'wash_completed_sensor':'sensor.completed', 'tracked_reservoir':'dock_clean',
              'water_volume_sensor':'sensor.tank', 'water_volume_reservoir':'dock_clean',
              'dock_variant':'dock', 'firmware':'1', 'integration_adapter':'test',
              'integration_version':'1', 'split_no_unmeasured_transfer':True}
    def step(s, ts, status, area, volume):
        values={'vacuum.test':_State('docked' if status == 'docked' else 'cleaning'),
                'sensor.status':_State(status), 'sensor.area':_State(str(area),{'unit_of_measurement':'m²'}),
                'sensor.new_area':_State(str(area),{'unit_of_measurement':'m²'}),
                'sensor.tank':_State(str(volume),{'unit_of_measurement':'ml'}),
                'sensor.completed':_State('0'), 'select.clean':_State('mopping'),
                'select.mop':_State('wet'), 'select.water':_State('high'), 'select.wash':_State('normal')}
        return tick.tick_device(_Hass(values),device,s,now_ts=ts)[0]
    s=step({},60000,'docked',0,3500.0)
    device['area_sensor']='sensor.new_area'
    s=step(s,120000,'docked',0,3500.0)
    s=step(s,150000,'docked',0,3500.0)
    # An interrupted former context left a persistent area gap before the new run.
    s['area_gap']=True
    for i in range(4):
        ts=180000+i*240000
        volume=3500.0-i*40
        s=step(s,ts,'mopping',0,volume)
        s=step(s,ts+60000,'mopping',10,volume-35)
        s=step(s,ts+120000,'docked',10,volume-35)
        s=step(s,ts+180000,'docked',0,volume-40)
    assert [x['purpose'] for x in s['split_sensor_measurements']]==['training']*3+['validation']
    assert all(x['area_m2']==10 and x['observed_ml']==35 for x in s['split_sensor_measurements'])
    before=len(s['split_sensor_measurements'])
    s=step(s,1200000,'mopping',0,3300.0)
    s=step(s,1260000,'mopping',5,3290.0)
    s=step(s,1320000,'mopping','unknown',3280.0)
    s=step(s,1380000,'mopping',10,3270.0)
    s=step(s,1440000,'docked',10,3270.0)
    assert len(s['split_sensor_measurements'])==before
    s=step(s,1500000,'docked',0,3270.0)
    s=step(s,1560000,'mopping',0,3270.0)
    s=step(s,1620000,'mopping',5,3260.0)
    s=step(s,1680000,'mopping',10,3265.0)
    s=step(s,1740000,'docked',10,3265.0)
    assert len(s['split_sensor_measurements'])==before
    s=step(s,1800000,'docked',0,3265.0)
    s=step(s,1860000,'mopping',0,3265.0)
    s=step(s,1920000,'mopping',5,3255.0)
    s=step(s,1980000,'unavailable',5,3255.0)
    s=step(s,2040000,'mopping',10,3245.0)
    s=step(s,2100000,'docked',10,3245.0)
    assert len(s['split_sensor_measurements'])==before


def test_bound_sensor_keeps_standalone_dock_wash_open_until_counter_completion():
    device = {'vacuum_entity':'vacuum.test', 'dock_status_sensor':'sensor.dock',
              'area_sensor':'sensor.area', 'cleaning_mode_entity':'select.clean',
              'mop_mode_entity':'select.mop', 'mop_intensity_entity':'select.water',
              'wash_mode_entity':'select.wash', 'wash_completed_sensor':'sensor.completed',
              'tracked_reservoir':'dock_clean', 'water_volume_sensor':'sensor.tank',
              'water_volume_reservoir':'dock_clean', 'dock_variant':'dock', 'firmware':'1',
              'integration_adapter':'test', 'integration_version':'1',
              'split_no_unmeasured_transfer':True}
    def step(state, ts, dock, count, volume):
        values={'vacuum.test':_State('docked'), 'sensor.dock':_State(dock),
                'sensor.area':_State('0',{'unit_of_measurement':'m²'}),
                'sensor.tank':_State(str(volume),{'unit_of_measurement':'ml'}),
                'sensor.completed':_State(str(count)), 'select.clean':_State('mopping'),
                'select.mop':_State('wet'), 'select.water':_State('high'),
                'select.wash':_State('normal')}
        return tick.tick_device(_Hass(values),device,state,now_ts=ts)[0]
    s=step({},60000,'idle',0,3500.0)
    s=step(s,120000,'washing_mop',0,3500.0)
    assert s['session_start_ts']==120000
    assert s['split_session_observation']['valid']
    s=step(s,180000,'washing_mop',0,3485.0)
    assert s['session_start_ts']==120000
    s=step(s,240000,'idle',1,3470.0)
    samples=s['split_sensor_measurements']
    assert len(samples)==1
    assert samples[0]['area_m2']==0 and samples[0]['wash_count']==1
    assert samples[0]['observed_ml']==30.0
    s=step(s,300000,'idle',1,3470.0)
    assert len(s['split_sensor_measurements'])==1
    assert s['used_ml']==30.0
