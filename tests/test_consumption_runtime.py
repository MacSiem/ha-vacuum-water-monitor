"""Replay the real tick using a synthetic versioned profile snapshot."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from test_tick import tick, _Hass, _State
from test_profile_selection import profile, context


class RuntimeConsumptionTests(unittest.TestCase):
    def run_tick(self, state=None, area=10, mode='confirmed', firmware='1', now=120000):
        ctx=context();ctx['firmware']=firmware
        device={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area',
                'consumption_context':ctx,'tracked_reservoir':'dock_clean',
                'mop_mode_entity':'select.mode'}
        h=_Hass({'vacuum.test':_State('cleaning'), 'sensor.area':_State(str(area),{'unit_of_measurement':'m²'}),
                 'select.mode':_State(mode)})
        return tick.tick_device(h,device,state or {'used_ml':0,'last_area':9,'last_tick_ts':60000},now_ts=now)[0]

    def test_versioned_profile_is_used_by_tick(self):
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()],'dataset_version':'test'}):
            s=self.run_tick()
        self.assertEqual(s['used_ml'],10)
        self.assertEqual(s['consumption_resolution']['profile_id'],'test.profile')

    def test_changed_observed_setting_invalidates_configured_context(self):
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()]}):
            s=self.run_tick(mode='new_enum')
        self.assertEqual(s['used_ml'],0)
        self.assertEqual(s['consumption_resolution']['source'],'unknown')

    def test_firmware_change_rebaselines_and_does_not_charge(self):
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()]}):
            s=self.run_tick()
            for firmware in ('2','0'):
                changed=self.run_tick(s,area=12,firmware=firmware,now=180000)
                self.assertEqual(changed['used_ml'],10)
                self.assertEqual(changed['last_accounting_reason'],'accounting_context_changed')

    def test_history_captures_historical_context(self):
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()]}):
            s=self.run_tick()
            end=tick.tick_device(_Hass({'vacuum.test':_State('docked')}),
                {'vacuum_entity':'vacuum.test'},s,now_ts=180000)[0]
        self.assertEqual(s['session_context']['firmware'],'1')
        self.assertEqual(s['session_context']['settings']['mop_mode'],'confirmed')

    def test_completed_history_retains_context_and_resolution(self):
        ctx=context()
        device={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','consumption_context':ctx}
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()]}):
            s=tick.tick_device(_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('10',{'unit_of_measurement':'m²'})}),device,{'used_ml':0,'last_area':9,'last_tick_ts':60000},now_ts=120000)[0]
            s=tick.tick_device(_Hass({'vacuum.test':_State('docked'),'sensor.area':_State('10',{'unit_of_measurement':'m²'})}),device,s,now_ts=180000)[0]
        record=s['automatic_sessions'][0]
        self.assertEqual(record.get('context',{}).get('firmware'),'1')
        self.assertEqual(record.get('resolution',{}).get('profile_id'),'test.profile')
        self.assertEqual(record['water'],10)
        ctx['firmware']='mutated'
        self.assertEqual(record['context']['firmware'],'1')

    def test_legacy_firmware_change_invalidates_interval(self):
        h=_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('10',{'unit_of_measurement':'m²'})})
        device={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','usage_ml_per_m2':{'default':10},'firmware':'1'}
        s=tick.tick_device(h,device,{'used_ml':0,'last_area':9,'last_tick_ts':60000},now_ts=120000)[0]
        device['firmware']='2'
        changed=tick.tick_device(h,device,s,now_ts=180000)[0]
        self.assertEqual(changed['last_accounting_reason'],'accounting_context_changed')

    def test_whole_cycle_calibration_is_charged_once_at_completion(self):
        r=profile();r.update(scope='whole_cycle',device_id='vacuum.test',coefficient=12)
        r['context']=context()
        device={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','consumption_context':context(),
                'consumption_calibration':r,'wash_volume_ml':100}
        def run(status,area,state,now):
            h=_Hass({'vacuum.test':_State(status),'sensor.area':_State(str(area),{'unit_of_measurement':'m²'})})
            return tick.tick_device(h,device,state,now_ts=now)[0]
        s=run('cleaning',0,{'used_ml':0,'last_status':'docked'},60000)
        s=run('cleaning',10,s,120000)
        self.assertEqual(s['used_ml'],0)
        s=run('washing_the_mop',10,s,180000)
        self.assertEqual(s['used_ml'],0)
        s=run('docked',10,s,240000)
        self.assertEqual(s['used_ml'],120)
        self.assertEqual(s['automatic_sessions'][0]['water'],120)
        self.assertTrue(s['automatic_sessions'][0]['exposure_complete'])
        s=run('docked',10,s,300000)
        self.assertEqual(s['used_ml'],120)

    def test_physical_sensor_wins_over_whole_cycle_calibration(self):
        r=profile();r.update(scope='whole_cycle',device_id='vacuum.test')
        device={'vacuum_entity':'vacuum.test','consumption_context':context(),'consumption_calibration':r,
                'water_volume_sensor':'sensor.volume','tracked_reservoir':'dock_clean','water_volume_reservoir':'dock_clean'}
        h=_Hass({'vacuum.test':_State('docked'),'sensor.volume':_State('900',{'unit_of_measurement':'mL'})})
        s=tick.tick_device(h,device,{'used_ml':0,'last_water_volume_ml':1000},now_ts=120000)[0]
        self.assertEqual(s['used_ml'],100)
        self.assertEqual(s['consumption_resolution']['source'],'real_sensor')

    def test_interrupted_whole_cycle_never_charges_full_dose(self):
        for interruption in ('unavailable','reset'):
            with self.subTest(interruption=interruption):
                r=profile();r.update(scope='whole_cycle',device_id='vacuum.test')
                d={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','consumption_context':context(),'consumption_calibration':r}
                def run(status,area,state,now):
                    return tick.tick_device(_Hass({'vacuum.test':_State(status),'sensor.area':_State(str(area),{'unit_of_measurement':'m²'})}),d,state,now_ts=now)[0]
                s=run('cleaning',0,{'used_ml':0,'last_status':'docked'},60000)
                s=run('cleaning',10,s,120000)
                s=run('unavailable' if interruption=='unavailable' else 'cleaning',0,s,180000)
                s=run('docked',10,s,240000)
                self.assertEqual(s['used_ml'],0)
                self.assertFalse(s['automatic_sessions'][0]['exposure_complete'])
                self.assertTrue(s.get('accounting_incomplete'))

    def test_unconfigured_device_retains_observed_partial_historical_context(self):
        d={'vacuum_entity':'vacuum.test','profile_key':'known_model','firmware':'1.2',
           'integration_adapter':'roborock','tracked_reservoir':'dock_clean',
           'area_sensor':'sensor.area','mop_mode_entity':'select.mode'}
        h=_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('0',{'unit_of_measurement':'m²'}),'select.mode':_State('standard')})
        s=tick.tick_device(h,d,{'used_ml':0},now_ts=60000)[0]
        self.assertEqual((s.get('session_context') or {}).get('firmware'),'1.2')
        self.assertEqual(s['session_context']['settings']['mop_mode'],'standard')
        self.assertIsNone(s['session_context']['settings']['route'])
        self.assertEqual(s['consumption_resolution']['reason'],'incomplete_context')

    def test_verified_wash_action_is_applied_once(self):
        r=profile();r.update(method='action',unit='ml/action',scope='wash_only',coefficient=80)
        r['context']['action']='mop_wash'
        r['exposure_domain']={'min':1,'max':1}
        d={'vacuum_entity':'vacuum.test','consumption_context':context(),'tracked_reservoir':'dock_clean','wash_completed_sensor':'sensor.completed'}
        def run(status,state,now):
            return tick.tick_device(_Hass({'vacuum.test':_State(status),'sensor.completed':_State('1' if now>=240000 else '0')}),d,state,now_ts=now)[0]
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[r]}):
            s=run('docked',{'used_ml':0},60000)
            s=run('washing_the_mop',s,120000)
            self.assertEqual(s['used_ml'],0)
            s=run('washing_the_mop',s,180000)
            self.assertEqual(s['used_ml'],0)
            s=run('docked',s,240000)
            self.assertEqual(s['used_ml'],80)
            self.assertEqual(s['last_accounting_source'],'wash')
            self.assertEqual(s['consumption_resolution']['profile_id'],'test.profile')
            s=run('docked',s,300000)
            self.assertEqual(s['used_ml'],80)

    def test_labeled_estimate_never_charges_without_verified_completion_binding(self):
        estimate={'id':'estimate.h50','kind':'estimate','estimate_readiness':'labeled_runtime_estimate',
                  'label':'Manufacturer-declared, limited estimate','source_type':'manufacturer_declaration',
                  'confidence':'declared_source_limited','basis_kind':'manufacturer_declared_quantity',
                  'basis_ids':['observation.h50'],'method':'Declared wash quantity',
                  'quantity':{'value':180,'unit':'ml/action'},
                  'context':{'model_id':'xiaomi_h50_pro','reservoir':'dock_clean','action':'first_time_mop_wash'},
                  'limitations':['Completion-counter binding'], 'provenance':[{'claim':'Declared quantity'}],
                  'unknowns':['Firmware']}
        ctx=context();ctx.update(model_id='xiaomi_h50_pro',action='first_time_mop_wash')
        device={'vacuum_entity':'vacuum.test','consumption_context':ctx,'tracked_reservoir':'dock_clean'}
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[],'estimates':[estimate]}):
            state=tick.tick_device(_Hass({'vacuum.test':_State('docked')}),device,{'used_ml':0},now_ts=120000)[0]
        self.assertEqual(state['used_ml'],0)
        self.assertEqual(state['consumption_resolution']['source'],'manufacturer_data')

    def test_mismatched_reservoir_never_uses_profile_for_other_tank(self):
        d={'vacuum_entity':'vacuum.test','consumption_context':context(),'tracked_reservoir':'robot_clean','area_sensor':'sensor.area'}
        h=_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('10',{'unit_of_measurement':'m²'})})
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[profile()]}):
            s=tick.tick_device(h,d,{'used_ml':0,'last_area':9,'last_tick_ts':60000},now_ts=120000)[0]
        self.assertEqual(s['used_ml'],0)
        self.assertEqual(s['consumption_resolution']['reason'],'context_reservoir_mismatch')

    def test_missing_rate_invalidates_total_until_new_refill(self):
        from test_sensor_calculations import estimate_water_state
        d={'vacuum_entity':'vacuum.test','area_sensor':'sensor.area','tracked_capacity_ml':4000}
        h=_Hass({'vacuum.test':_State('cleaning'),'sensor.area':_State('10',{'unit_of_measurement':'m²'})})
        s=tick.tick_device(h,d,{'initialized':True,'used_ml':0,'last_area':9,'last_tick_ts':60000},now_ts=120000)[0]
        self.assertTrue(s.get('accounting_incomplete'))
        result=estimate_water_state(d,s)
        self.assertIsNone(result['remaining_ml'])
        self.assertIsNone(result['used_ml'])
        self.assertEqual(result['state_reason'],'accounting_incomplete')

    def test_increment_must_be_inside_profile_exposure_domain(self):
        r=profile();r['exposure_domain']={'min':10,'max':100}
        with patch('vwmtickpkg.profiles.CONSUMPTION_SNAPSHOT',{'schema_version':2,'profiles':[r]}):
            s=self.run_tick()
        self.assertEqual(s['used_ml'],0)
        self.assertEqual(s['consumption_resolution']['reason'],'exposure_outside_validated_domain')
