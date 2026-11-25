"""Area-only Qrevo estimates must wait for short-gap counter recovery."""
import unittest

from test_beta_runtime_path import BASE, _S, descriptor, effective, run, sc


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

    def test_both_qrevo_models_keep_refill_baseline_on_idle_and_count_french_wash(self):
        for model in ("a245", "a170"):
            with self.subTest(model=model):
                device = effective({}, descriptor(model))
                idle = run(device, dict(BASE), [dict(status="charging", area="0"),
                                                dict(status="charging", area="0")])
                self.assertFalse(idle.get("accounting_incomplete"))
                self.assertIsNotNone(sc.estimate_water_state(device, idle, {})["remaining_ml"])
                washing = run(device, idle, [dict(status="Lavage de la serpillère", area="0")])
                self.assertTrue(washing["wash_sequence_active"])
                self.assertGreater(washing["used_ml"], idle["used_ml"])

    def test_bound_unchanged_duration_does_not_poison_recoverable_area_gap(self):
        for model in ("a245", "a170"):
            with self.subTest(model=model):
                device = {**effective({}, descriptor(model)), "duration_sensor": "sensor.duration",
                          "usage_ml_per_m2": {"standard": 10}, "wash_volume_ml": 45,
                          "calibration_scope": "floor_only"}
                duration = {"sensor.duration": _S("1", {"unit_of_measurement": "min"})}
                def step(status, area, vac="cleaning", gap=2700):
                    return dict(status=status, vac=vac, area=area, extra=duration, _gap=gap)
                state = run(device, dict(BASE), [step("charging", "0", "docked"),
                    step("Lavage de la serpillère", "0", "docked"),
                    step("cleaning", "0"), step("cleaning", "2")])
                self.assertEqual(state["used_ml"], 65)
                state = run(device, state, [step("cleaning", "unknown")], ts=10_010_800)
                self.assertEqual(state["used_ml"], 65)
                self.assertFalse(state.get("accounting_incomplete"))
                state = run(device, state, [step("cleaning", "3")], ts=10_013_500)
                self.assertEqual(state["used_ml"], 75)
                self.assertEqual(state["bridged_gaps"], 1)
                self.assertFalse(state.get("accounting_incomplete"))
                self.assertEqual(sc.estimate_water_state(device, state, {})["remaining_ml"], 3925)

    def test_bound_duration_preserves_unsafe_and_preexisting_interruptions(self):
        device = {**self.device, "duration_sensor": "sensor.duration"}
        duration = {"sensor.duration": _S("1", {"unit_of_measurement": "min"})}
        for label, gap, area, intensity, incomplete in (
            ("long", 360000, "3", "medium", False),
            ("settings", 2700, "3", "high", False),
            ("counter_reset", 2700, "0", "medium", False),
            ("prior_interruption", 2700, "3", "medium", True),
        ):
            with self.subTest(label=label):
                steps = self.sequence(gap=gap, recovered_area=area, recovered_intensity=intensity)
                for step in steps:
                    step["extra"] = duration
                state = run(device, {**BASE, "accounting_incomplete": incomplete}, steps)
                self.assertTrue(state.get("accounting_incomplete"))
                self.assertIsNone(sc.estimate_water_state(device, state, {})["remaining_ml"])

    def test_short_area_only_gap_recovers_without_refill(self):
        state = run(self.device, dict(BASE), self.sequence())
        self.assertEqual(state["bridged_gaps"], 1)
        self.assertEqual(state["used_ml"], 30)
        self.assertFalse(state.get("accounting_incomplete"))
        estimate = sc.estimate_water_state(self.device, state, {})
        self.assertIsNotNone(estimate["remaining_ml"])

    def test_waiting_never_invents_a_time_dose_and_expires(self):
        steps = self.sequence()[:3]
        waiting = run(self.device, dict(BASE), steps)
        self.assertEqual(waiting["used_ml"], 20)
        self.assertFalse(waiting.get("accounting_incomplete"))
        self.assertEqual(waiting["last_accounting_reason"], "area_unavailable")
        expired = run(self.device, waiting, [dict(status="cleaning", vac="cleaning", area="unknown")],
                      ts=20_000_000)
        self.assertEqual(expired["used_ml"], 20)
        self.assertTrue(expired.get("accounting_incomplete"))

    def test_gap_with_unknown_loss_remains_incomplete(self):
        for kwargs in ({"gap": 360000, "recovered_area": "20"},
                       {"recovered_intensity": "high"}, {"recovered_area": "0"}):
            with self.subTest(kwargs=kwargs):
                state = run(self.device, dict(BASE), self.sequence(**kwargs))
                self.assertTrue(state.get("accounting_incomplete"))
                self.assertIsNone(sc.estimate_water_state(self.device, state, {})["remaining_ml"])
