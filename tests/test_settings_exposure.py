"""A discarded interval must not become a complete refill-to-empty sample."""
import unittest
from test_beta_runtime_path import BASE, descriptor, effective, run

class SettingsExposureTests(unittest.TestCase):
    def test_mode_change_with_area_exposure_excludes_tank_from_learning(self):
        device = effective({}, descriptor())
        first = run(device, {**BASE, 'last_reset_ts': 1}, [
            dict(status='cleaning', vac='cleaning', area='0', intensity='standard'),
            dict(status='cleaning', vac='cleaning', area='5', intensity='standard')])
        changed = run(device, first, [dict(status='cleaning', vac='cleaning', area='7', intensity='mild')], ts=10120000)
        self.assertEqual(changed['used_ml'], first['used_ml'])
        self.assertTrue(changed.get('accounting_incomplete'))
        end = run(device, {**changed, 'used_ml': 3000}, [dict(dock_err='water_empty', intensity='mild', area='7')], ts=20120000)
        self.assertEqual(end.get('calibration_samples', 0), 0)

    def test_mode_change_with_only_active_time_exposure_marks_tank_incomplete(self):
        device = {**effective({}, descriptor()), 'area_sensor': None,
                  'usage_ml_per_active_minute': {'default': 2}}
        first = run(device, dict(BASE), [dict(status='cleaning', vac='cleaning', intensity='standard')])
        changed = run(device, first, [dict(status='cleaning', vac='cleaning', intensity='mild')], ts=10060000)
        self.assertEqual(changed['used_ml'], first['used_ml'])
        self.assertTrue(changed.get('accounting_incomplete'))

    def test_docked_setting_change_without_exposure_keeps_tank_complete(self):
        device = effective({}, descriptor())
        first = run(device, dict(BASE), [dict(area='45.5', intensity='standard')])
        changed = run(device, first, [dict(area='45.5', intensity='mild')], ts=10060000)
        self.assertFalse(changed.get('accounting_incomplete'))
        self.assertEqual(changed['used_ml'], first['used_ml'])

    def test_setting_change_during_vacuum_only_does_not_invalidate_water(self):
        device = effective({}, descriptor())
        first = run(device, dict(BASE), [dict(status='cleaning', vac='cleaning', area='0', intensity='off'),
                                        dict(status='cleaning', vac='cleaning', area='5', intensity='off')])
        # A route setting changes while output remains off.
        from test_beta_runtime_path import hass, tick, _S
        changed, _ = tick.tick_device(hass(status='cleaning', vac='cleaning', area='7', intensity='off',
            extra={'select.robot_mop_mode': _S('deep')}), device, first, now_ts=10180000)
        self.assertFalse(changed.get('accounting_incomplete'))
        self.assertEqual(changed['used_ml'], 0)
