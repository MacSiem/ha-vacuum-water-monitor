"""Runtime integration of separately learned floor and completed-wash doses."""
import sys
import types
import unittest
from unittest.mock import patch

from test_tick import tick, _Hass, _State


class SplitRuntimeTests(unittest.TestCase):
    def test_current_identity_floor_rate_and_confirmed_wash(self):
        identities = []
        def identity(hass, device, context):
            identities.append(context['settings']['mop_mode'])
            return {'mode': identities[-1]}
        def resolve(samples, key):
            self.assertEqual(samples, ['manual', 'sensor'])
            if key['mode'] == 'wet':
                return {'floor_ml_per_m2': 5, 'wash_ml_per_completed_action': 80}
            return None
        observation = types.ModuleType('vwmtickpkg.split_observation')
        observation.identity = identity
        device = {'vacuum_entity': 'vacuum.test', 'tracked_reservoir': 'dock_clean',
                  'area_sensor': 'sensor.area', 'mop_mode_entity': 'select.mode',
                  'mop_intensity_entity': 'select.intensity', 'intensity_factor': {'high': 3},
                  'wash_completed_sensor': 'sensor.completed', 'split_measurements': ['manual']}
        def run(state, ts, status, area, count, mode='wet', water=None):
            values = {'vacuum.test': _State(status), 'select.mode': _State(mode),
                      'select.intensity': _State('high'), 'sensor.area': _State(str(area), {'unit_of_measurement': 'm²'}),
                      'sensor.completed': _State(str(count))}
            if water is not None:
                values['sensor.water'] = _State(water)
            return tick.tick_device(_Hass(values), device, state, now_ts=ts)[0]
        with patch.dict(sys.modules, {'vwmtickpkg.split_observation': observation}), \
             patch('vwmtickpkg.split_learning.resolve', resolve, create=True):
            state = run({'used_ml': 0, 'split_sensor_measurements': ['sensor'], 'calibration_factor': 2}, 60000, 'cleaning', 0, 0)
            state = run(state, 120000, 'cleaning', 2, 0)
            self.assertEqual(state['used_ml'], 10)
            state = run(state, 180000, 'washing_the_mop', 2, 0)
            state = run(state, 240000, 'washing_the_mop', 2, 0)
            self.assertEqual(state['used_ml'], 10)
            state = run(state, 300000, 'docked', 2, 1)
            self.assertEqual(state['used_ml'], 90)
            state = run(state, 360000, 'docked', 2, 1)
            self.assertEqual(state['used_ml'], 90)
            state = run(state, 420000, 'cleaning', 2, 1, mode='dry')
            self.assertEqual(identities[-1], 'dry')
            self.assertEqual(state['used_ml'], 90)
            device['water_volume_sensor'] = 'sensor.water'
            state = run(state, 480000, 'cleaning', 4, 1, water='unavailable')
            self.assertEqual(state['used_ml'], 90)


if __name__ == '__main__':
    unittest.main()
