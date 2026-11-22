"""A dock restoring its defaults must not erase the completed mop run."""
import unittest
from unittest.mock import patch
from test_profile_selection import context, profile
from test_beta_runtime_path import BASE, descriptor, effective, hass, tick, sc, _S


class RestoredModeSessionTests(unittest.TestCase):
    def test_docked_default_restore_keeps_final_area_and_session_water(self):
        device=effective({},descriptor())
        device['cleaning_mode_entity']='select.cleaning_mode'
        state={**BASE,'last_area':0,'last_status':'charging'}
        steps=[('washing_the_mop','docked',0,'deep','intense','mop'),
               ('cleaning','cleaning',0,'deep','intense','mop'),
               ('cleaning','cleaning',10,'deep','intense','mop'),
               ('washing_the_mop','docked',10,'deep','intense','mop'),
               ('cleaning','cleaning',15.4,'deep','intense','mop'),
               ('charging','docked',15.5,'standard','extreme','vac_and_mop')]
        for index,(status,vac,area,mode,intensity,clean_mode) in enumerate(steps):
            h=hass(status=status,vac=vac,area=str(area),intensity=intensity,
                   extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+index*60_000)[0]
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertAlmostEqual(state['used_ml'],300+15.5*9*1.3,places=2)
        self.assertIsNotNone(state['automatic_sessions'][0]['water'])
        self.assertEqual(state['automatic_sessions'][0]['context']['settings']['mop_mode'],'deep')

    def _run_steps(self, steps, step_ms=60_000):
        device=effective({},descriptor())
        device['cleaning_mode_entity']='select.cleaning_mode'
        state={**BASE,'last_area':0,'last_status':'charging'}
        for index,(status,vac,area,mode,intensity,clean_mode) in enumerate(steps):
            h=hass(status=status,vac=vac,area=str(area),intensity=intensity,
                   extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+index*step_ms)[0]
        return state

    # Roborock S8 MaxV Ultra 19.11.2026: the routine restores "standard" when the
    # robot reaches the dock, a few seconds before the session closes.
    RUN = [('washing_the_mop','docked',0,'deep_plus','intense','mop'),
           ('cleaning','cleaning',0,'deep_plus','intense','mop'),
           ('cleaning','cleaning',12,'deep_plus','intense','mop'),
           ('washing_the_mop','docked',12,'deep_plus','intense','mop'),
           ('cleaning','cleaning',20,'deep_plus','intense','mop'),
           ('washing_the_mop','docked',20,'deep_plus','intense','mop')]

    def test_settings_restored_at_the_dock_keep_a_valid_session(self):
        state=self._run_steps(self.RUN+[('charging','docked',20,'standard','standard','vac_and_mop'),
                                        ('charging','docked',20,'standard','standard','vac_and_mop')])
        session=state['automatic_sessions'][0]
        self.assertTrue(session['accounting_valid'])
        self.assertEqual(session['context']['settings']['mop_mode'],'deep_plus')
        self.assertNotIn('session_settled_context_change',state)

    def test_settings_restored_while_the_dock_still_reports_washing_stay_valid(self):
        state=self._run_steps(self.RUN+[('washing_the_mop','docked',20,'standard','standard','vac_and_mop'),
                                        ('charging','docked',20,'standard','standard','vac_and_mop')])
        # The final wash was charged when it started; nothing was dispensed later.
        self.assertTrue(state['automatic_sessions'][0]['accounting_valid'])

    def test_a_new_wash_after_the_change_makes_a_mixed_run(self):
        state=self._run_steps(self.RUN+[('washing_the_mop','docked',20,'standard','standard','mop'),
                                        ('cleaning','cleaning',20,'standard','standard','mop'),
                                        ('washing_the_mop','docked',20,'standard','standard','mop')], step_ms=20_000)
        self.assertFalse(state['session_accounting_valid'])

    def test_resuming_under_the_restored_settings_starts_a_separate_session(self):
        state=self._run_steps(self.RUN+[('charging','docked',20,'standard','standard','mop'),
                                        ('cleaning','cleaning',20,'standard','standard','mop'),
                                        ('cleaning','cleaning',26,'standard','standard','mop')], step_ms=30_000)
        first=state['automatic_sessions'][0]
        self.assertTrue(first['accounting_valid'])
        self.assertEqual(first['context']['settings']['mop_mode'],'deep_plus')
        self.assertEqual(state['session_context']['settings']['mop_mode'],'standard')

    def test_empty_is_visible_even_when_prior_consumption_was_incomplete(self):
        device=effective({},descriptor())
        result=sc.estimate_water_state(device,{**BASE,'accounting_incomplete':True,
            'water_empty_active':True,'water_anchor_kind':'empty','used_ml':3800},{})
        self.assertEqual(result['remaining_percent'],0)
        self.assertEqual(result['remaining_ml'],0)
        self.assertIsNone(result['used_ml'])
        self.assertEqual(result['state_reason'],'water_empty')

    def test_returning_restore_and_late_area_use_last_floor_rate(self):
        device=effective({},descriptor())
        device['cleaning_mode_entity']='select.cleaning_mode'
        state={**BASE,'last_area':0,'last_status':'charging'}
        steps=[('cleaning','cleaning',0,'deep','intense','mop'),
               ('cleaning','cleaning',10,'deep','intense','mop'),
               ('returning_home','returning',10,'deep','extreme','vac_and_mop'),
               ('returning_home','returning',10.2,'standard','extreme','vac_and_mop'),
               ('charging','docked',10.2,'standard','extreme','vac_and_mop')]
        for i,(status,vac,area,mode,intensity,clean_mode) in enumerate(steps):
            h=hass(status=status,vac=vac,area=area,intensity=intensity,
                   extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+i*15_000)[0]
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertAlmostEqual(state['used_ml'],10.2*9*1.3,places=2)
        self.assertTrue(state['automatic_sessions'][0]['accounting_valid'])
        self.assertEqual(state['automatic_sessions'][0]['context']['settings']['water_level'],'intense')

    def test_mode_change_during_floor_exposure_stays_incomplete(self):
        device=effective({},descriptor())
        state={**BASE,'last_area':0,'last_status':'charging'}
        for i,(area,mode) in enumerate([(0,'deep'),(10,'deep'),(11,'standard')]):
            state=tick.tick_device(hass(status='cleaning',vac='cleaning',area=area,intensity='intense',
                extra={'select.robot_mop_mode':_S(mode)}),device,state,now_ts=10_060_000+i*60_000)[0]
        self.assertTrue(state['accounting_incomplete'])
        self.assertFalse(state['session_accounting_valid'])

    def test_shortage_does_not_manufacture_empty_from_incomplete(self):
        result=sc.estimate_water_state(effective({},descriptor()),{**BASE,
            'accounting_incomplete':True,'water_empty_active':True,
            'water_anchor_kind':'shortage','used_ml':3800},{})
        self.assertIsNone(result['remaining_percent'])
        self.assertEqual(result['state_reason'],'accounting_incomplete')

    def test_numeric_output_range_keeps_its_resolved_factor_at_dock(self):
        device=effective({},descriptor())
        device['mop_intensity_entity']='number.output'
        state={**BASE,'last_area':0,'last_status':'charging'}
        for i,(status,vac,area) in enumerate([('cleaning','cleaning',0),('cleaning','cleaning',1),('returning_home','returning',2)]):
            h=hass(status=status,vac=vac,area=area,extra={
                'select.robot_mop_mode':_S('deep'),
                'number.output':_S('10',{'min':1,'max':10,'step':1})})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+i*60_000)[0]
        self.assertAlmostEqual(state['used_ml'],2*9*1.3,places=2)
        self.assertFalse(state.get('accounting_incomplete'))

    def test_verified_floor_profile_keeps_last_dose_after_default_restore(self):
        ctx=context()
        device={'vacuum_entity':'vacuum.robot','area_sensor':'sensor.robot_area',
            'mop_mode_entity':'select.robot_mop_mode','status_sensor':'sensor.robot_status',
            'consumption_context':ctx,'tracked_reservoir':'dock_clean',
            'calibration_scope':'floor_only','rate_signal':'mop_mode'}
        state={**BASE,'last_area':0,'last_status':'charging'}
        with patch.object(tick.consumption_profiles,'CONSUMPTION_SNAPSHOT',
                {'schema_version':2,'profiles':[profile()],'dataset_version':'test'}):
            for i,(status,vac,area,mode) in enumerate([('cleaning','cleaning',0,'confirmed'),
                    ('cleaning','cleaning',1,'confirmed'),('returning_home','returning',2,'standard')]):
                h=hass(status=status,vac=vac,area=area,extra={'select.robot_mop_mode':_S(mode)})
                state=tick.tick_device(h,device,state,now_ts=10_060_000+i*60_000)[0]
        self.assertEqual(state['used_ml'],20)
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertEqual(state['last_accounting_evidence'],'verified_model')

    def test_closing_floor_dose_works_for_each_supported_rate_signal(self):
        for signal,rates in [('mop_mode',{'deep':9,'standard':6}),
                ('mop_intensity',{'high':9,'extreme':6}),
                ('cleaning_mode',{'mop':9,'vac_and_mop':6})]:
            with self.subTest(signal=signal):
                device=effective({},descriptor())
                device.update(rate_signal=signal,usage_ml_per_m2=rates,cleaning_mode_entity='select.cleaning_mode')
                state={**BASE,'last_area':0,'last_status':'charging'}
                for i,(status,vac,area,mode,intensity,clean_mode) in enumerate([
                        ('cleaning','cleaning',0,'deep','intense','mop'),
                        ('cleaning','cleaning',1,'deep','intense','mop'),
                        ('returning_home','returning',2,'standard','extreme','vac_and_mop')]):
                    h=hass(status=status,vac=vac,area=area,intensity=intensity,
                        extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
                    state=tick.tick_device(h,device,state,now_ts=10_060_000+i*60_000)[0]
                self.assertAlmostEqual(state['used_ml'],2*9*1.3,places=2)
                self.assertFalse(state.get('accounting_incomplete'))
