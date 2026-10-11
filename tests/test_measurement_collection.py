"""Prospective context declarations cannot alter old measurements or HA facts."""
import unittest
from copy import deepcopy
from test_beta_runtime_path import BASE, descriptor, effective, run, _S
from test_local_measurements import calibration, cycle, measurement


class CollectionTests(unittest.TestCase):
    def test_declared_unexposed_settings_are_recorded_prospectively(self):
        plan = {'confirmed':True, 'sku':'EU', 'dock_variant':'tank',
                'integration_version':'2026.10.0', 'settings':{'wash_mode':'standard'}}
        device = effective({'measurement_plans':{'vacuum.robot':plan}},descriptor())
        state = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0'),
                                      dict(status='cleaning',vac='cleaning',area='10'),
                                      dict(status='charging',area='10')])
        context = state['automatic_sessions'][0]['context']
        self.assertEqual(context['settings']['wash_mode'],'standard')
        self.assertEqual(context['integration_version'],'2026.10.0')
        self.assertEqual(context['field_sources']['wash_mode'],'declared')
        self.assertEqual(context['field_sources']['integration_version'],'declared')
        original = deepcopy(state['automatic_sessions'])
        device = effective({'measurement_plans':{'vacuum.robot':{**plan,'settings':{'wash_mode':'deep'}}}},descriptor())
        state = run(device,state,[dict()])
        self.assertEqual(state['automatic_sessions'],original)

    def test_observed_controls_always_override_declarations(self):
        plan = {'confirmed':True, 'settings':{'water_level':'extreme','mop_mode':'deep'}}
        device = effective({'measurement_plans':{'vacuum.robot':plan}},descriptor())
        state = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0')])
        self.assertEqual(state['session_context']['settings']['water_level'],'medium')
        self.assertEqual(state['session_context']['settings']['mop_mode'],'standard')
        self.assertEqual(state['session_context']['field_sources']['water_level'],'observed')

    def test_invalid_or_unconfirmed_plan_is_not_used(self):
        for plan in ({'confirmed':False,'settings':{'wash_mode':'deep'}},
                     {'confirmed':True,'settings':{'room':'Kitchen'}},
                     {'confirmed':True,'settings':{'wash_mode':'https://private.home'}}):
            with self.subTest(plan=plan):
                device = effective({'measurement_plans':{'vacuum.robot':plan}},descriptor())
                state = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0')])
                self.assertIsNone(state['session_context']['settings']['wash_mode'])

    def test_quality_confirmation_is_saved_and_incomplete_accounting_rejected(self):
        sample = calibration.build_local_measurement(cycle(),measurement(),'vacuum.test')
        self.assertTrue(sample['confirmed'])
        self.assertTrue(sample['quality']['boundaries_confirmed'])
        incomplete = cycle(); incomplete['accounting_valid'] = False
        with self.assertRaises(ValueError):
            calibration.build_local_measurement(incomplete,measurement(),'vacuum.test')

    def test_unconfirmed_or_outlying_samples_cannot_train_a_rate(self):
        samples = [calibration.build_local_measurement(cycle(i),measurement(),'vacuum.test') for i in range(1,5)]
        samples[-1]['observed_ml'] = 10000
        fitted = calibration.fit_local_measurements(samples)
        self.assertEqual(fitted['coefficient'],10)
        self.assertNotIn('local.4',fitted['evidence_ids'])
        samples[0]['confirmed'] = False
        self.assertIsNone(calibration.fit_local_measurements(samples[:3]))

    def test_measured_whole_cycle_profile_reaches_the_real_accounting_consumer(self):
        records = [cycle(i) for i in (1,2,3)]
        for record in records:
            record['context']['settings'].update(mop_mode='standard',water_level='medium')
        samples = [calibration.build_local_measurement(s,measurement(),'vacuum.robot') for s in records]
        fitted = calibration.fit_local_measurements(samples)
        device = {**effective({},descriptor()),'consumption_context':records[0]['context'],
                  'consumption_calibration':[fitted],'usage_ml_per_m2':{},
                  'usage_ml_per_active_minute':{},'wash_volume_ml':None}
        state = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0'),
                                     dict(status='cleaning',vac='cleaning',area='10'),
                                     dict(status='charging',area='10')])
        self.assertEqual(state['used_ml'],100)
        self.assertEqual(state['automatic_sessions'][0]['context']['action'],'whole_cycle')
        self.assertFalse(state.get('accounting_incomplete',False))
        self.assertIsNone(state.get('missing_usage_rate_reason'))

    def test_full_confirmation_after_auto_refill_promotes_without_resetting_again(self):
        import asyncio
        from test_user_device_removal import storage
        async def check(used):
            st = storage.VacuumWaterStorage(None)
            original = {'initialized':True,'last_reset_ts':1000000,'last_reset_source':'dock_cleared',
                        'used_ml':used,'cycle_full_confirmed':False,
                        'refill_history':[{'ts':1000000,'source':'dock_cleared'}]}
            await st.async_set_tank_state('vacuum.robot',original)
            return await st.async_reset_tank('vacuum.robot','2026-10-11T00:00:00Z',1001000,'card')
        state = asyncio.run(check(0))
        self.assertTrue(state['cycle_full_confirmed'])
        self.assertEqual(state['last_reset_ts'],1000000)
        self.assertEqual(len(state['refill_history']),1)
        state = asyncio.run(check(50))
        self.assertFalse(state['cycle_full_confirmed'])
        self.assertEqual(state['used_ml'],50)

    def test_migration_only_qualifies_explicit_old_full_confirmations(self):
        for source,expected in [('card',True),('service',True),('button',True),('lid',False),('dock_cleared',False)]:
            with self.subTest(source=source):
                state = run(effective({},descriptor()),{**BASE,'last_reset_ts':9000000,'last_reset_source':source},[dict()])
                self.assertEqual(state.get('cycle_full_confirmed',False),expected)

    def _physical_device(self):
        records = [cycle(i) for i in (1,2,3)]
        for record in records:
            record['context']['settings'].update(mop_mode='standard',water_level='medium')
        samples = [calibration.build_local_measurement(s,measurement(),'vacuum.robot') for s in records]
        return {**effective({},descriptor()),'consumption_context':records[0]['context'],
                'consumption_calibration':[calibration.fit_local_measurements(samples)]}

    def test_whole_cycle_outside_domain_preserves_automatic_estimate(self):
        device = self._physical_device()
        steps = [dict(status='cleaning',vac='cleaning',area='0'),
                 dict(status='cleaning',vac='cleaning',area='5'),dict(status='charging',area='5')]
        baseline = run({**device,'consumption_calibration':None},dict(BASE),steps)
        state = run(device,dict(BASE),steps)
        self.assertGreater(baseline['used_ml'],0)
        self.assertEqual(state['used_ml'],baseline['used_ml'])
        self.assertFalse(state.get('accounting_incomplete',False))
        self.assertEqual(state['consumption_resolution']['reason'],'exposure_outside_validated_domain')

    def test_dock_restored_controls_do_not_erase_qualified_whole_cycle(self):
        device = self._physical_device()
        state = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0'),
            dict(status='cleaning',vac='cleaning',area='10'),
            dict(status='charging',area='10',intensity='high'),
            dict(status='charging',area='10',intensity='high')])
        self.assertEqual(state['used_ml'],100)
        self.assertFalse(state.get('accounting_incomplete',False))
        self.assertEqual(state['automatic_sessions'][0]['context']['settings']['water_level'],'medium')

    def test_successful_whole_cycle_replaces_provisional_floor_and_wash_once(self):
        device = self._physical_device()
        start = run(device,dict(BASE),[dict(status='cleaning',vac='cleaning',area='0'),
            dict(status='cleaning',vac='cleaning',area='10'),dict(status='washing_the_mop',area='10')])
        self.assertGreater(start['used_ml'],0)
        state = run(device,start,[dict(status='charging',area='10'),dict(status='charging',area='10')],ts=start['last_tick_ts'])
        self.assertEqual(state['used_ml'],100)
        self.assertEqual(state['cycle_action_totals'],{'whole_cycle':100})
        self.assertEqual(state['automatic_sessions'][0]['water'],100)
        self.assertEqual(state['automatic_sessions'][0]['exposures']['area_m2'],10)
        self.assertTrue(any(e.get('superseded_by')=='qualified_whole_cycle' for e in state['consumption_events']))

    def test_declared_full_refill_practice_qualifies_future_auto_refills_only(self):
        for confirmed in (False,True):
            with self.subTest(confirmed=confirmed):
                device = effective({'refill_settings':{'vacuum.robot':{'full_refill_practice_confirmed':confirmed}}},descriptor())
                original = {**BASE,'used_ml':3700,'cycle_full_confirmed':False}
                unchanged = run(device,original,[dict()])
                self.assertFalse(unchanged['cycle_full_confirmed'])
                state = run(device,original,[dict(dock_err='water_empty'),dict(dock_err='water_empty'),dict(dock_err='ok',_gap=120000)])
                self.assertEqual(state['used_ml'],0)
                self.assertEqual(state['cycle_full_confirmed'],confirmed)
                if confirmed:
                    self.assertEqual(state['cycle_full_confirmation_source'],'declared_full_refill_practice')
