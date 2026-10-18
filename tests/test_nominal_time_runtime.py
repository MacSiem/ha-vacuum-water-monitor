"""Full nominal tanks teach the real Matter profile without an invented seed."""
from copy import deepcopy
import unittest
from test_beta_runtime_path import discovery, sc, tick, _S, _Hass
from test_tick import _load_tick


def device():
    entities = [{'entity_id': 'vacuum.tapo', 'platform': 'matter', 'device_id': 'one'}]
    entities += [{'entity_id': eid, 'platform': 'matter', 'device_id': 'one',
                  'translation_key': key} for eid, key in (
                    ('sensor.tapo_status', 'operational_state'),
                    ('select.tapo_mode', 'clean_mode'))]
    desc = discovery.discover_descriptors(entities, [{'id': 'one', 'manufacturer': 'Tapo',
                'model': 'RV50 Pro Omni', 'model_id': '1797'}], {})[0]
    return sc.build_vacuum_devices({}, {}, [desc])[0]


def observe(dev, state, now, active, mode='Vacuum and Mop;Deep Clean'):
    hass = _Hass({'vacuum.tapo': _S('cleaning' if active else 'docked'),
                  'sensor.tapo_status': _S('running' if active else 'docked'),
                  'select.tapo_mode': _S(mode)})
    return tick.tick_device(hass, dev, state, now_ts=now)[0]


class NominalTimeRuntimeTests(unittest.TestCase):
    def test_three_full_tanks_activate_a_private_rate_on_next_refill(self):
        dev = device()
        self.assertFalse(dev.get('usage_ml_per_active_minute'))
        state = {}
        refill = _load_tick().__dict__['FULL_CONFIRMATION_SOURCES']  # shared public source contract
        self.assertIn('service', refill)
        from importlib import import_module
        apply_refill = import_module(tick.__package__ + '.refill').apply_refill
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            apply_refill(state, now, 'service', rebaseline=True)
            state = observe(dev, state, now, False)
            for minute in range(10):
                state = observe(dev, state, now + 60_000 + minute * 60_000, True)
            state = observe(dev, state, now + 660_000, False)
            state['user_empty_active'] = True
            state = observe(dev, state, now + 720_000, False)
        resolution = state.get('nominal_time_resolution') or {}
        self.assertEqual(resolution.get('status'), 'active')
        self.assertEqual(resolution.get('accuracy'), 'not_established')
        self.assertEqual(resolution.get('sample_count'), 3)
        now += 2_000_000
        apply_refill(state, now, 'service', rebaseline=True)
        state = observe(dev, state, now, False)
        state = observe(dev, state, now + 60_000, True)
        state = observe(dev, state, now + 120_000, True)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10, places=2)
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertEqual(state['last_accounting_evidence'], 'nominal_full_to_empty_time')

    def test_missing_mop_mode_does_not_create_learning_exposure(self):
        dev = device()
        state = {'initialized': True, 'last_reset_ts': 10_000_000,
                 'cycle_full_confirmed': True, 'used_ml': 0}
        for minute in range(12):
            state = observe(dev, state, 10_000_000 + minute * 60_000, True, mode='Vacuum Only')
        self.assertEqual(state['used_ml'], 0)
        self.assertFalse((state.get('nominal_time_learning') or {}).get('contexts'))
