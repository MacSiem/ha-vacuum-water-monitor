"""Area-only Qrevo estimates must wait for short-gap counter recovery."""
import unittest

from test_beta_runtime_path import BASE, descriptor, effective, run, sc


class QrevoAreaRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.device = effective({}, descriptor("a245"))
        self.assertTrue(self.device.get("usage_ml_per_m2"))
        self.assertFalse(self.device.get("usage_ml_per_active_minute"))

    def sequence(self, gap=10000, recovered_area="3", recovered_intensity="medium"):
        return [dict(status="cleaning", vac="cleaning", area="0"),
                dict(status="cleaning", vac="cleaning", area="2"),
                dict(status="cleaning", vac="cleaning", area="unknown", _gap=10000),
                dict(status="cleaning", vac="cleaning", area=recovered_area,
                     intensity=recovered_intensity, _gap=gap)]

    def test_short_area_only_gap_recovers_without_refill(self):
        state = run(self.device, dict(BASE), self.sequence())
        self.assertEqual(state["bridged_gaps"], 1)
        self.assertEqual(state["used_ml"], 30)
        self.assertFalse(state.get("accounting_incomplete"))
        estimate = sc.estimate_water_state(self.device, state, {})
        self.assertIsNotNone(estimate["remaining_ml"])

    def test_gap_with_unknown_loss_remains_incomplete(self):
        for kwargs in ({"gap": 360000, "recovered_area": "20"},
                       {"recovered_intensity": "high"}, {"recovered_area": "0"}):
            with self.subTest(kwargs=kwargs):
                state = run(self.device, dict(BASE), self.sequence(**kwargs))
                self.assertTrue(state.get("accounting_incomplete"))
                self.assertIsNone(sc.estimate_water_state(self.device, state, {})["remaining_ml"])

