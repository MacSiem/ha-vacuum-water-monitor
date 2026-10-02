import unittest
from test_tick import tick, _Hass, _State

class AreaTimeHandoffTests(unittest.TestCase):
    def cycle(self, pace=None, duration_gap=False):
        device = {'vacuum_entity': 'vacuum.test', 'area_sensor': 'sensor.area',
                  'duration_sensor': 'sensor.time', 'cleaning_mode_entity': 'select.mode',
                  'usage_ml_per_m2': {'default': 10},
                  'usage_ml_per_active_minute': {'default': 10}, 'calibration_scope': 'floor_only'}
        state = {'initialized': True, 'used_ml': 0, 'last_area': 0,
                 'last_duration_seconds': 0, 'last_tick_ts': 60000}
        if pace is not None: state['area_rate_m2_per_s'] = pace
        samples = []
        for area, duration, now in [('1','60',120000),
                                   ('unavailable', 'unavailable' if duration_gap else '120',180000),
                                   ('3','180',240000), ('4','240',300000)]:
            state, _ = tick.tick_device(_Hass({'vacuum.test': _State('cleaning'),
                'sensor.area': _State(area, {'unit_of_measurement':'m²'}),
                'sensor.time': _State(duration, {'unit_of_measurement':'s'}),
                'select.mode': _State('mop')}), device, state, now_ts=now)
            samples.append(state)
        return samples

    def test_area_return_after_valid_time_counts_each_interval_once(self):
        samples = self.cycle(pace=1/60)
        self.assertEqual([s['used_ml'] for s in samples], [10,20,30,40])
        self.assertFalse(samples[-1].get('accounting_incomplete'))

    def test_same_handoff_without_prior_pace_keeps_complete_balance(self):
        samples = self.cycle()
        self.assertEqual([s['used_ml'] for s in samples], [10,20,30,40])
        self.assertFalse(samples[-1].get('accounting_incomplete'))

    def test_missing_area_and_time_does_not_become_complete_on_return(self):
        samples = self.cycle(duration_gap=True)
        self.assertTrue(samples[-1].get('accounting_incomplete'))
