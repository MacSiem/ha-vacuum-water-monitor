"""Interruption evidence for Dreame's periodic accounting observations."""
import asyncio
import unittest

from test_beta_runtime_path import BASE, _S, hass, tick
from test_dreame_observed_settings import fixture
from test_user_device_removal import storage


class DreameMinuteSyncTests(unittest.TestCase):
    def test_unknown_bound_control_after_repair_is_the_interruption_cause(self):
        device = fixture()
        initial = {**BASE, 'used_ml': 900, 'last_status': 'charging'}
        async def repair():
            store = storage.VacuumWaterStorage(None)
            await store.async_set_tank_state('vacuum.robot', initial)
            return await store.async_reset_tank('vacuum.robot', '2026-11-25T22:12:30Z', 20_000_000, source='repair')
        state = asyncio.run(repair())
        extra = {'sensor.robot_state': _S('charging'), 'sensor.robot_area': _S('45', {'unit_of_measurement': 'm²'}),
                 'select.robot_mode': _S('mopping'), 'select.robot_humidity': _S('medium'),
                 'number.robot_wetness': _S('unavailable'), 'select.robot_route': _S('standard'),
                 'select.robot_remop': _S('off'), 'select.robot_reclean': _S('off'), 'switch.robot_smart': _S('off')}
        result, _ = tick.tick_device(hass(extra=extra), device, state, now_ts=20_018_000)
        self.assertTrue(result['accounting_incomplete'])
        self.assertEqual(result['used_ml'], 0)
        incident = result['last_accounting_interruption']
        self.assertIn('observed_setting_unavailable', incident['reasons'])
        self.assertIn('area_baseline_initialized', incident['reasons'])
        self.assertEqual(incident['source'], 'context')

    def test_missing_initial_area_is_attributed_to_missing_exposure(self):
        device = fixture()
        state = {**BASE, 'last_area': None, 'last_status': 'cleaning', 'last_tick_ts': 0}
        extra = {'sensor.robot_state': _S('cleaning'), 'sensor.robot_area': _S('45', {'unit_of_measurement': 'm²'}),
                 'select.robot_mode': _S('mopping'), 'select.robot_humidity': _S('medium'),
                 'number.robot_wetness': _S('16', {'min': 1, 'max': 32}), 'select.robot_route': _S('standard'),
                 'select.robot_remop': _S('off'), 'select.robot_reclean': _S('off'), 'switch.robot_smart': _S('off')}
        result, _ = tick.tick_device(hass(status='cleaning', vac='cleaning', extra=extra), device, state, now_ts=20_018_000)
        self.assertTrue(result['accounting_incomplete'])
        self.assertIn('initial_area_exposure_unobserved', result['last_accounting_interruption']['reasons'])
