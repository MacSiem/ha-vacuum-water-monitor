"""Measured level samples through tick_device, with no HA or physical robot."""
import json
import unittest
from test_beta_runtime_path import tick, sc, effective, descriptor, hass, _S


def device():
    return {**effective({}, descriptor()), 'water_volume_sensor': 'sensor.volume',
            'tracked_reservoir': 'dock_clean', 'water_volume_reservoir': 'dock_clean',
            'tracked_capacity_ml': 4000}


def step(dev, state, now, status, area, volume, *, volume_unit='ml', area_unit='m²'):
    sensors = {'sensor.volume': _S(str(volume), {'unit_of_measurement': volume_unit}),
               'sensor.robot_area': _S(str(area), {'unit_of_measurement': area_unit})}
    h = hass(status=status, vac='cleaning' if status == 'cleaning' else 'docked', area=area, extra=sensors)
    return tick.tick_device(h, dev, state, now_ts=now)[0]


def session(dev, state, now, start=3500, draw=100):
    for offset, status, area, volume in [(0, 'charging', 0, start), (60, 'cleaning', 0, start),
                                        (120, 'cleaning', 5, start-draw/2),
                                        (180, 'cleaning', 10, start-draw),
                                        (240, 'charging', 10, start-draw)]:
        state = step(dev, state, now + offset*1000, status, area, volume)
    return state


class PhysicalRuntimeTests(unittest.TestCase):
    def test_measured_whole_session_learning_and_restart(self):
        dev = device()
        state = {}
        for n in range(3):
            state = session(dev, state, 10000000 + n*600000, 3500 - n*100)
            state = json.loads(json.dumps(state))
        result = state['physical_learning_resolution']
        self.assertEqual(result['status'], 'active')
        self.assertEqual(result['scope'], 'whole_session')
        self.assertEqual(result['coefficient_ml_per_m2'], 10)
        self.assertEqual(sc.estimate_water_state(dev, state)['physical_learning_resolution'], result)
        self.assertEqual(state['consumption_resolution']['source'], 'real_sensor')
        state = session(dev, state, 12000000, 3200, draw=300)
        self.assertEqual(state['physical_learning_resolution']['coefficient_ml_per_m2'], 10)
        self.assertEqual(state['physical_learning_resolution']['pending_count'], 1)
        for n in range(2):
            state = session(dev, state, 12600000 + n*600000, 2900 - n*300, draw=300)
        self.assertEqual(state['physical_learning_resolution']['coefficient_ml_per_m2'], 30)

    def test_reject_refill_gap_units_and_reservoir(self):
        dev = device()
        for mode in ('refill', 'gap', 'unit', 'reservoir', 'area_unit', 'reset', 'binding'):
            with self.subTest(mode=mode):
                state = step(dev, {}, 10000000, 'charging', 0, 3500)
                state = step(dev, state, 10060000, 'cleaning', 0, 3500)
                changed = {**dev}
                if mode == 'reservoir': changed['water_volume_reservoir'] = 'robot_clean'
                if mode == 'binding': changed['water_volume_sensor'] = 'sensor.other'
                now = 10300001 if mode == 'gap' else 10120000
                state = step(changed, state, now, 'cleaning', -1 if mode == 'reset' else 5,
                             3600 if mode == 'refill' else 3450,
                             volume_unit='gal' if mode == 'unit' else 'ml',
                             area_unit='gallons' if mode == 'area_unit' else 'm²')
                state = step(dev, state, now+60000, 'cleaning', 6, 3440)
                state = step(dev, state, now+120000, 'charging', 10, 3400)
                self.assertFalse((state.get('physical_learning') or {}).get('contexts'))

    def test_old_model_survives_reconnect_and_context_change(self):
        dev = device()
        state = {}
        for n in range(3):
            state = session(dev, state, 10000000 + n*600000, 3500-n*100)
        state = step(dev, state, 12000000, 'charging', 0, 3200)
        state = step(dev, state, 12060000, 'cleaning', 0, 3200)
        state = step(dev, state, 12120000, 'cleaning', 2, 'unavailable')
        state = step(dev, state, 12180000, 'cleaning', 4, 3160)
        state = step(dev, state, 12240000, 'charging', 10, 3100)
        self.assertEqual(state['physical_learning_resolution']['sample_count'], 3)
        self.assertEqual(state['physical_learning_resolution']['coefficient_ml_per_m2'], 10)
        changed = {**dev, 'observed_firmware': 'new-firmware'}
        state = session(changed, state, 13000000, 3100)
        self.assertNotEqual(state['physical_learning_resolution']['status'], 'active')
        state = session(dev, state, 14000000, 3000)
        self.assertEqual(state['physical_learning_resolution']['status'], 'active')
        self.assertEqual(state['physical_learning_resolution']['coefficient_ml_per_m2'], 10)

    def test_explicit_refill_invalidates_open_physical_observation(self):
        from importlib import import_module
        refill = import_module(tick.__package__ + '.refill')
        dev = device()
        state = step(dev, {}, 10000000, 'charging', 0, 3500)
        state = step(dev, state, 10060000, 'cleaning', 0, 3500)
        refill.apply_refill(state, 10090000, 'service', rebaseline=True)
        state = step(dev, state, 10120000, 'cleaning', 0, 3500)
        state = step(dev, state, 10180000, 'cleaning', 10, 3400)
        state = step(dev, state, 10240000, 'charging', 10, 3400)
        self.assertFalse(state['physical_learning']['contexts'])

    def test_bad_observation_at_zero_cannot_restart_same_session(self):
        dev = device()
        state = step(dev, {}, 10000000, 'charging', 0, 3500)
        state = step(dev, state, 10060000, 'cleaning', 0, 3500)
        state = step(dev, state, 10120000, 'cleaning', 0, 3600)
        state = step(dev, state, 10180000, 'cleaning', 0, 3600)
        state = step(dev, state, 10240000, 'cleaning', 10, 3500)
        state = step(dev, state, 10300000, 'charging', 10, 3500)
        self.assertFalse((state.get('physical_learning') or {}).get('contexts'))
