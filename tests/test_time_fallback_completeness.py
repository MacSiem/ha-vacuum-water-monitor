import unittest
import test_sprint_accounting as accounting

class TimeFallbackCompletenessTests(unittest.TestCase):
    def test_successful_time_fallback_keeps_tank_complete(self):
        state = accounting.SprintAccountingTests().sample(
            device={'usage_ml_per_m2': {}, 'duration_sensor': 'sensor.duration'},
            state={'last_duration_seconds': 60})
        self.assertEqual(state['used_ml'], 70)
        self.assertEqual(state['last_accounting_source'], 'active_time')
        self.assertFalse(state.get('accounting_incomplete'))

    def test_unavailable_duration_does_not_mask_lost_exposure(self):
        state = accounting.SprintAccountingTests().sample(
            device={'usage_ml_per_m2': {}, 'duration_sensor': 'sensor.duration'},
            duration='unavailable', state={'last_duration_seconds': 60})
        self.assertEqual(state['used_ml'], 50)
        self.assertTrue(state.get('accounting_incomplete'))

    def test_missing_both_rates_remains_incomplete(self):
        state = accounting.SprintAccountingTests().sample(
            device={'usage_ml_per_m2': {}, 'usage_ml_per_active_minute': {},
                    'duration_sensor': 'sensor.duration'},
            state={'last_duration_seconds': 60})
        self.assertEqual(state['used_ml'], 50)
        self.assertTrue(state.get('accounting_incomplete'))
