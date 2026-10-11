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
