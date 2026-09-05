"""Safety regressions: one physical interval must never be charged twice."""
import unittest
from test_tick import tick, _Hass, _State

class SprintAccountingTests(unittest.TestCase):
    def test_bound_context_options_split_accounting(self):
        for role in ("task_scope_entity", "suction_level_entity", "carpet_policy_entity"):
            with self.subTest(role=role):
                device = {"vacuum_entity": "vacuum.test", "area_sensor": "sensor.area",
                          "usage_ml_per_m2": {"default": 10}, role: "select.option"}
                def run(option, area, state, now):
                    entries = {"vacuum.test": _State("cleaning"),
                               "sensor.area": _State(str(area), {"unit_of_measurement": "m²"}),
                               "select.option": _State(option)}
                    return tick.tick_device(_Hass(entries), device, state, now_ts=now)[0]
                first = run("first", 10, {"initialized": True, "used_ml": 0,
                            "last_area": 9, "last_tick_ts": 60000}, 120000)
                previous = first["used_ml"]
                second = run("second", 12, first, 180000)
                self.assertEqual(second["used_ml"], previous)
                self.assertEqual(second["last_accounting_reason"], "accounting_context_changed")
                self.assertFalse(second["session_accounting_valid"])

    def sample(self, device=None, state=None, **values):
        entries={'vacuum.test': _State(values.pop('vacuum','cleaning')), 'sensor.area':_State(values.pop('area','12'),{'unit_of_measurement':'m²'}), 'sensor.duration':_State(values.pop('duration','120'),{'unit_of_measurement':'s'}),'sensor.status':_State(values.pop('status','cleaning')), 'sensor.volume':_State(values.pop('volume','3900'),{'unit_of_measurement':'mL'})}
        return tick.tick_device(_Hass(entries), {'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','status_sensor':'sensor.status','usage_ml_per_m2':{'default':10},'usage_ml_per_active_minute':{'default':20}, **(device or {})}, {'initialized':True,'used_ml':50,'last_area':10,'last_status':'cleaning','last_tick_ts':60000, **(state or {})},now_ts=120000)[0]

    def test_wash_and_floor_cannot_charge_same_sample(self):
        s=self.sample(device={'wash_volume_ml':100,'calibration_scope':'floor_only'},status='washing_the_mop')
        self.assertEqual(s['used_ml'],150)

    def test_missing_vacuum_breaks_counter_continuity(self):
        s=self.sample(vacuum='unavailable')
        self.assertEqual(s['used_ml'],50)
        self.assertEqual(s['last_accounting_reason'],'vacuum_unavailable')

    def test_duration_unavailable_never_becomes_wall_time(self):
        s=self.sample(device={'area_sensor':None,'duration_sensor':'sensor.duration'},duration='unavailable',state={'last_duration_seconds':60})
        self.assertEqual(s['used_ml'],50)
        self.assertEqual(s['last_accounting_reason'],'duration_unavailable')

    def test_missing_area_rate_uses_calibrated_duration(self):
        s=self.sample(device={'usage_ml_per_m2':{},'duration_sensor':'sensor.duration'},state={'last_duration_seconds':60})
        self.assertEqual(s['used_ml'],70)

    def test_authoritative_same_reservoir_volume_wins_over_area(self):
        s=self.sample(device={'water_volume_sensor':'sensor.volume','water_volume_reservoir':'dock_clean','tracked_reservoir':'dock_clean','tracked_capacity_ml':4000},state={'last_water_volume_ml':3950})
        self.assertEqual(s['used_ml'],100)
        self.assertEqual(s['last_accounting_source'],'real_sensor')

    def test_authoritative_sensor_unavailable_does_not_fall_back(self):
        s=self.sample(device={'water_volume_sensor':'sensor.volume','water_volume_reservoir':'dock_clean','tracked_reservoir':'dock_clean','tracked_capacity_ml':4000},volume='unavailable')
        self.assertEqual(s['used_ml'],50)
        self.assertEqual(s['last_accounting_reason'],'real_sensor_unavailable')

    def test_resume_after_duration_gap_only_rebaselines(self):
        s=self.sample(device={'area_sensor':None,'duration_sensor':'sensor.duration'},state={'last_duration_seconds':60,'duration_gap':True})
        self.assertEqual(s['used_ml'],50)

    def test_unavailable_status_never_uses_stale_cleaning_state(self):
        s=self.sample(status='unavailable')
        self.assertEqual(s['used_ml'],50)

    def test_restart_long_gap_never_charges_area_catchup(self):
        s=self.sample(state={'last_tick_ts':1})
        # Within 180 s allowed; a separately simulated long gap is rejected.
        state,_=tick.tick_device(_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('12',{'unit_of_measurement':'m²'})}),{'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','usage_ml_per_m2':{'default':10}},{'used_ml':50,'last_area':10,'last_tick_ts':1000},now_ts=1000000)
        self.assertEqual(state['used_ml'],50)

    def test_completed_cleaning_records_one_automatic_session(self):
        started=self.sample(state={'last_status':'docked'})
        end=self.sample(state=started,status='docked',vacuum='docked')
        self.assertEqual(len(end.get('automatic_sessions',[])),1)
        again=self.sample(state=end,status='docked',vacuum='docked')
        self.assertEqual(len(again['automatic_sessions']),1)

    def test_model_change_rebaselines_and_discards_learned_factor(self):
        before=self.sample(device={'profile_key':'one'})
        after=self.sample(device={'profile_key':'two'},state={**before,'calibration_factor':2,'calibration_samples':3},area='14')
        self.assertEqual(after['used_ml'],before['used_ml'])
        self.assertEqual(after['calibration_samples'],0)
        self.assertEqual(after['last_accounting_reason'],'accounting_context_changed')

    def test_robot_empty_error_cannot_empty_unverified_dock_reservoir(self):
        h=_Hass({'vacuum.test':_State('docked'),'sensor.error':_State('water_tank_empty')})
        s,_=tick.tick_device(h,{'vacuum_entity':'vacuum.test','water_error_sensor':'sensor.error','tracked_capacity_ml':4000,'tracked_reservoir':'dock_clean'},{'initialized':True,'used_ml':1000},now_ts=120000)
        self.assertEqual(s['used_ml'],1000)
        self.assertEqual(s['last_accounting_reason'],'water_anchor_reservoir_unverified')

    def test_real_volume_refill_clears_legacy_empty_anchor(self):
        s=self.sample(device={'water_volume_sensor':'sensor.volume','water_volume_reservoir':'dock_clean','tracked_reservoir':'dock_clean','tracked_capacity_ml':4000},state={'used_ml':3800,'water_empty_active':True,'water_anchor_kind':'empty','last_water_volume_ml':200},volume='4000')
        self.assertFalse(s['water_empty_active']);self.assertEqual(s['used_ml'],0)
        self.assertIsNotNone(s.get('last_reset_iso'))

    def test_alarm_clear_cannot_prove_full_refill(self):
        s,_=tick.tick_device(_Hass({'vacuum.test':_State('docked'),'binary_sensor.shortage':_State('off')}),{'vacuum_entity':'vacuum.test','water_shortage_sensor':'binary_sensor.shortage','tracked_capacity_ml':4000},{'used_ml':3500,'water_empty_active':True,'water_anchor_source':'water_shortage'},now_ts=2000000)
        self.assertEqual(s['used_ml'],3500)
        self.assertEqual(s['last_accounting_reason'],'refill_volume_unmeasured')

    def test_measured_remaining_does_not_require_full_refill(self):
        from test_sensor_calculations import estimate_water_state
        result=estimate_water_state({'tracked_capacity_ml':4000},{'last_accounting_source':'real_sensor','last_water_volume_ml':1234})
        self.assertEqual(result['remaining_ml'],1234)
        self.assertEqual(result['source'],'real_sensor')
        missing=estimate_water_state({'tracked_capacity_ml':4000},{'initialized':True,'last_accounting_source':'real_sensor','last_water_volume_ml':None})
        self.assertIsNone(missing['remaining_ml'])

    def test_whole_cycle_rate_cannot_add_wash_volume(self):
        s=self.sample(device={'wash_volume_ml':100,'calibration_scope':'whole_cycle'},status='washing_the_mop')
        self.assertEqual(s['used_ml'],50)

    def test_setting_change_does_not_charge_crossing_interval(self):
        device={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','cleaning_mode_entity':'select.mode','usage_ml_per_m2':{'default':10}}
        def run(mode,area,state,now):
            return tick.tick_device(_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State(str(area),{'unit_of_measurement':'m²'}),'select.mode':_State(mode)}),device,state,now_ts=now)[0]
        first=run('mopping',10,{'initialized':True,'used_ml':0,'last_area':9,'last_tick_ts':60000},120000)
        previous=first['used_ml']
        start=first['session_start_ts']
        second=run('vacuum_and_mop',12,first,180000)
        self.assertEqual(second['session_start_ts'],start)
        self.assertFalse(second['session_accounting_valid'])
        self.assertEqual(second['used_ml'],previous)
        self.assertEqual(second['last_accounting_reason'],'accounting_context_changed')
        third=run('vacuum_and_mop',13,second,240000)
        self.assertEqual(third['used_ml'],previous+10)
