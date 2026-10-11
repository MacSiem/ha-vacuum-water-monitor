"""Nominal empty events must not become independent measured training samples."""
import unittest
from test_beta_runtime_path import BASE, descriptor, effective, run


class ConfirmedAccountingTests(unittest.TestCase):
    def test_unconfirmed_nominal_empty_does_not_learn_even_after_repetition(self):
        device = effective({}, descriptor())
        state = dict(BASE)
        for index in range(2):
            state = run(device, {**state, 'used_ml':3700},
                        [dict(dock_err='water_empty'), dict(dock_err='ok',_gap=180000)],
                        ts=(index+1)*10000000)
        self.assertEqual(state.get('calibration_samples',0),0)
        self.assertEqual(state.get('calibration_factor',1),1)
        self.assertFalse(state['calibration_history'][0]['accepted'])
        self.assertEqual(state['calibration_history'][0]['basis'],'nominal_capacity')

    def test_empty_keeps_existing_legacy_factor_and_history(self):
        device = effective({}, descriptor())
        state = run(device, {**BASE, 'used_ml':3700, 'calibration_factor':1.1,
                            'calibration_samples':2, 'calibration_history':[{'ts':1,'accepted':True}]},
                    [dict(dock_err='water_empty')])
        self.assertEqual(state['calibration_factor'],1.1)
        self.assertEqual(state['calibration_samples'],2)
        self.assertEqual(state['calibration_history'][-1],{'ts':1,'accepted':True})

    def test_empty_does_not_refund_unmeasured_fraction_of_a_wash(self):
        state = run(effective({}, descriptor()), {**BASE, 'used_ml':2500,
                    'last_wash_charged_ts':10000000,'last_wash_charged_ml':150},
                    [dict(dock_err='water_empty')],ts=10000000)
        event = state['calibration_history'][0]
        self.assertEqual(event['predicted_ml'],2500)
        self.assertNotIn('failed_wash_refund_ml',event)
        self.assertEqual(event['reason'],'calibration_sample_full_unconfirmed')

    def test_confirmed_full_cycle_learns_relative_balance_without_claiming_measured_ml(self):
        state = run(effective({}, descriptor()), {**BASE, 'used_ml':3700,
                    'cycle_full_confirmed':True, 'last_reset_ts':1000},
                    [dict(dock_err='water_empty')])
        self.assertEqual(state['calibration_samples'],1)
        self.assertAlmostEqual(state['calibration_factor'],3800/3700,places=4)
        event = state['calibration_history'][0]
        self.assertTrue(event['accepted'])
        self.assertFalse(event['measurement_confirmed'])
        self.assertEqual(event['basis'],'nominal_capacity')

    def test_lost_first_floor_exposure_disqualifies_the_whole_tank(self):
        state = run(effective({},descriptor()), {**BASE,'last_area':None,
                    'cycle_full_confirmed':True},
                    [dict(status='cleaning',vac='cleaning',area='4'),
                     dict(status='charging',area='10')])
        self.assertTrue(state['accounting_incomplete'])

    def test_prewash_belongs_to_the_run_and_is_not_lost_from_history(self):
        state = run(effective({},descriptor()),dict(BASE),[
            dict(status='washing_the_mop',area='45.5'),
            dict(status='washing_the_mop',area='0'),
            dict(status='cleaning',vac='cleaning',area='0'),
            dict(status='cleaning',vac='cleaning',area='10'),
            dict(status='charging',area='10')])
        session = state['automatic_sessions'][0]
        self.assertEqual(session['water'],210)
        self.assertEqual(session['action_totals'],{'mop_wash':150,'floor_mopping':60})
        self.assertEqual(session['area'],10)
        self.assertTrue(session['exposure_complete'])

    def test_real_volume_sensor_does_not_leave_a_phantom_estimated_wash(self):
        from test_beta_runtime_path import _S
        device = {**effective({},descriptor()),'water_volume_sensor':'sensor.volume',
                  'water_volume_reservoir':'dock_clean','tracked_reservoir':'dock_clean',
                  'tracked_capacity_ml':4000}
        state = run(device,{**BASE,'last_water_volume_ml':3000},[
            dict(status='washing_the_mop',extra={'sensor.volume':_S('2900',{'unit_of_measurement':'ml'})})])
        self.assertEqual(state['used_ml'],100)
        self.assertEqual([(e['source'],e['amount_ml'],e['quantity_kind'])
                         for e in state['consumption_events']],[('real_sensor',100,'measured')])

    def test_floor_and_wash_have_separate_auditable_doses(self):
        device = effective({}, descriptor())
        state = run(device,{**BASE,'last_area':0},[
            dict(status='cleaning',vac='cleaning',area='0'),
            dict(status='cleaning',vac='cleaning',area='10'),
            dict(status='washing_the_mop',vac='docked',area='10'),
            dict(status='washing_the_mop',vac='docked',area='10'),
            dict(status='charging',vac='docked',area='10')])
        doses = state.get('consumption_events',[])
        self.assertEqual([(d['action'],d['amount_ml']) for d in reversed(doses)],
                         [('floor_mopping',60),('mop_wash',150)])
        self.assertEqual(sum(d['amount_ml'] for d in doses),state['used_ml'])
        self.assertTrue(all(d['quantity_kind']=='estimate' for d in doses))
        self.assertTrue(all(d['context']['model_id']=='roborock_s8_maxv_ultra' for d in doses))

    def test_nominal_anchor_is_not_a_consumption_event(self):
        state = run(effective({},descriptor()),{**BASE,'used_ml':2500},[dict(dock_err='water_empty')])
        self.assertEqual(state.get('consumption_events',[]),[])
        self.assertEqual(state['last_calibration_predicted_ml'],2500)


if __name__ == '__main__':
    unittest.main()
