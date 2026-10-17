"""Rejected area samples must not distort learning or task history.

These reproduce source defects discovered while investigating issue #11;
they do not assert that the author's undocumented area jump was a false alarm.
"""
import copy
import json
import unittest

from test_beta_runtime_path import BASE, descriptor, effective, run


class AreaObservationValidationTests(unittest.TestCase):
    def setUp(self):
        self.device = effective({}, descriptor())

    def test_new_task_first_nonzero_area_matches_counted_water_in_history(self):
        state = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="2"),
            dict(status="cleaning", vac="cleaning", area="4"),
            dict(status="charging", vac="docked", area="4"),
        ])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], 24)
        self.assertEqual(state["automatic_sessions"][0]["water"], 24)
        self.assertEqual(state["automatic_sessions"][0]["area"], 4)

    def test_rejected_area_jump_does_not_train_cleaning_pace(self):
        before = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
        ])
        self.assertGreater(before["area_rate_m2_per_s"], 0)
        after = run(self.device, copy.deepcopy(before), [
            dict(status="cleaning", vac="cleaning", area="40"),
        ], ts=10_120_000)
        self.assertEqual(after["used_ml"], before["used_ml"])
        self.assertTrue(after["accounting_incomplete"])
        self.assertIn("area_anomaly", after["last_accounting_interruption"]["reasons"])
        self.assertEqual(after["area_rate_m2_per_s"], before["area_rate_m2_per_s"])
        # The accepted pace, not the rejected jump, must survive persisted state.
        self.assertEqual(json.loads(json.dumps(after))["area_rate_m2_per_s"], before["area_rate_m2_per_s"])
