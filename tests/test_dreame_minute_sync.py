"""Dreame interruptions and confirmed-dock idle observations."""
import asyncio
import unittest

from test_beta_runtime_path import BASE, _S, hass, tick
from test_dreame_observed_settings import fixture
from test_user_device_removal import storage


def sample(status='charging', vacuum='docked', area='45', wetness='unavailable', dock=None):
    values = {
        'sensor.robot_state': _S(status),
        'sensor.robot_area': _S(area, {'unit_of_measurement': 'm²'}),
        'select.robot_mode': _S('mopping'),
        'select.robot_humidity': _S('medium'),
        'number.robot_wetness': _S(wetness, {'min': 1, 'max': 32}),
        'select.robot_route': _S('standard'),
        'select.robot_remop': _S('off'),
        'select.robot_reclean': _S('off'),
        'switch.robot_smart': _S('off'),
    }
    if dock is not None:
        values['sensor.dock'] = _S(dock)
    return hass(status=status, vac=vacuum, extra=values)


async def repair(initial):
    store = storage.VacuumWaterStorage(None)
    await store.async_set_tank_state('vacuum.robot', initial)
    return await store.async_reset_tank('vacuum.robot', '2026-11-25T22:12:30Z', 20_000_000, source='repair')


class DreameMinuteSyncTests(unittest.TestCase):
    def test_idle_repair_keeps_full_balance_until_control_returns(self):
        device = fixture()
        device.update(usage_ml_per_m2={'default': 10}, calibration_scope='floor_only')
        state = asyncio.run(repair({**BASE, 'used_ml': 900, 'last_status': 'charging'}))
        for now in (20_018_000, 20_078_000, 20_138_000):
            state, _ = tick.tick_device(sample(), device, state, now_ts=now)
            self.assertFalse(state['accounting_incomplete'])
            self.assertEqual(state['used_ml'], 0)
            self.assertNotIn('last_accounting_interruption', state)
        state, _ = tick.tick_device(sample(wetness='16'), device, state, now_ts=20_198_000)
        self.assertFalse(state['accounting_incomplete'])
        self.assertEqual(state['used_ml'], 0)
        state, _ = tick.tick_device(sample(status='cleaning', vacuum='cleaning', area='0', wetness='16'),
                                    device, state, now_ts=20_258_000)
        state, _ = tick.tick_device(sample(status='cleaning', vacuum='cleaning', area='2', wetness='16'),
                                    device, state, now_ts=20_318_000)
        self.assertEqual(state['used_ml'], 20)
        self.assertFalse(state['accounting_incomplete'])
        self.assertTrue(state['session_accounting_valid'])

    def test_deferred_learning_does_not_start_at_an_unobserved_active_transition(self):
        device = fixture()
        device.update(tracked_reservoir='dock_clean', tracked_capacity_ml=4500)
        state = asyncio.run(repair({**BASE, 'used_ml': 900, 'last_status': 'charging'}))
        state, _ = tick.tick_device(sample(), device, state, now_ts=20_018_000)
        self.assertTrue(state.get('nominal_time_waiting_for_settings'))
        state, _ = tick.tick_device(sample(status='cleaning', vacuum='cleaning', area='0', wetness='16'),
                                    device, state, now_ts=20_078_000)
        self.assertIsNone((state.get('nominal_time_learning') or {}).get('cycle'))

    def test_deferred_learning_starts_only_after_settings_recover_at_dock(self):
        device = fixture()
        device.update(tracked_reservoir='dock_clean', tracked_capacity_ml=4500)
        state = asyncio.run(repair({**BASE, 'used_ml': 900, 'last_status': 'charging'}))
        state, _ = tick.tick_device(sample(), device, state, now_ts=20_018_000)
        state, _ = tick.tick_device(sample(wetness='16'), device, state, now_ts=20_078_000)
        self.assertIsNotNone((state.get('nominal_time_learning') or {}).get('cycle'))
        self.assertFalse(state['accounting_incomplete'])

    def test_missing_control_is_still_an_interruption_when_exposure_is_possible(self):
        device = fixture()
        cases = [
            ('cleaning', 'cleaning', {}, None),
            ('charging', 'returning', {}, None),
            ('charging', 'docked', {'session_start_ts': 19_900_000}, None),
            ('charging', 'docked', {'last_status': 'returning'}, None),
            ('charging', 'docked', {'gap_exposure_possible': True}, None),
            ('charging', 'docked', {'last_area': 40}, None),
            ('charging', 'docked', {}, 'washing_mop'),
            ('charging', 'docked', {}, 'unavailable'),
            ('charging', 'docked', {'last_dock_status': 'washing_mop'}, 'idle'),
        ]
        for status, vacuum, changes, dock in cases:
            with self.subTest(status=status, vacuum=vacuum, changes=changes, dock=dock):
                config = dict(device)
                if dock is not None:
                    config['dock_status_sensor'] = 'sensor.dock'
                state = {**BASE, 'last_area': None, 'last_status': 'charging', 'last_tick_ts': 0,
                         'last_reset_ts': 20_000_000, 'last_dock_status': 'idle', **changes}
                result, _ = tick.tick_device(sample(status=status, vacuum=vacuum, dock=dock),
                                             config, state, now_ts=20_018_000)
                self.assertTrue(result['accounting_incomplete'])
                self.assertIn('observed_setting_unavailable', result['last_accounting_interruption']['reasons'])

    def test_missing_initial_area_is_attributed_to_missing_exposure(self):
        state = {**BASE, 'last_area': None, 'last_status': 'cleaning', 'last_tick_ts': 0}
        result, _ = tick.tick_device(sample(status='cleaning', vacuum='cleaning', wetness='16'),
                                     fixture(), state, now_ts=20_018_000)
        self.assertTrue(result['accounting_incomplete'])
        self.assertIn('initial_area_exposure_unobserved', result['last_accounting_interruption']['reasons'])
