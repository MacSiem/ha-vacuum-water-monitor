"""5.7.0-beta.2: calibration survives misplaced anchors, short gaps and failed washes.

Audit 2026-09-15 (S2/S3/D/E): the first calibration samples were accepted
unconditionally (a lifted tank taught 2.53, an unreported top-up 0.655), one
unavailable tick invalidated the whole tank, and a wash that failed because the
dock ran dry was charged in full.
"""

from __future__ import annotations

import importlib
import unittest

from test_beta_runtime_path import BASE, descriptor, effective, run

estimation = importlib.import_module("vwmruntimepkg.estimation")

S8 = effective({}, descriptor())  # owner_device estimate, 4000 ml dock tank, 5% residual -> 3800 ml target


def tank(state, used, ts):
    """One tank closing at the given predicted use, then the dock clears after a refill."""
    return run(S8, {**state, "used_ml": used}, [dict(dock_err="water_empty"), dict(dock_err="ok", _gap=180_000)], ts=ts)


def cleaning(areas, **overrides):
    return [dict(status="cleaning", vac="cleaning", area=str(a), **overrides) for a in areas]


class ConfirmationGateTests(unittest.TestCase):
    def test_lifted_tank_does_not_teach_the_device(self):
        state = tank(dict(BASE), 1500, 10_000_000)
        self.assertEqual(state.get("calibration_samples", 0), 0)
        self.assertEqual(state["calibration_history"][0]["reason"], "calibration_sample_unconfirmed")
        self.assertIsNotNone(state["calibration_pending_log_factor"])
        self.assertEqual(state["used_ml"], 0, "the refill after the anchor still applies")
        state = tank(state, 3700, 20_000_000)
        self.assertEqual(state["calibration_samples"], 1)
        self.assertAlmostEqual(state["calibration_factor"], 3800 / 3700, delta=0.01)
        self.assertIsNone(state["calibration_pending_log_factor"])

    def test_unreported_top_up_is_held(self):
        state = tank(dict(BASE), 5800, 10_000_000)
        self.assertFalse(state["calibration_history"][0]["accepted"])
        self.assertEqual(state.get("calibration_factor", 1), 1)

    def test_a_genuinely_different_robot_is_learned_after_two_consistent_tanks(self):
        state = tank(dict(BASE), 3000, 10_000_000)
        self.assertEqual(state.get("calibration_samples", 0), 0)
        state = tank(state, 3050, 20_000_000)
        self.assertEqual(state["calibration_samples"], 2)
        self.assertEqual(state["calibration_history"][0]["reason"], "calibration_sample_confirmed")
        self.assertAlmostEqual(state["calibration_factor"], 1.257, delta=0.02)

    def test_after_three_tanks_the_outlier_gate_takes_over(self):
        state = dict(BASE)
        for index, used in enumerate((3700, 3750, 3650)):
            state = tank(state, used, 10_000_000 * (index + 1))
        self.assertEqual(state["calibration_samples"], 3)
        state = tank(state, 1500, 50_000_000)
        self.assertEqual(state["calibration_history"][0]["reason"], "calibration_sample_outlier")
        self.assertIsNone(state["calibration_pending_log_factor"])


class GapBridgingTests(unittest.TestCase):
    START = [dict(status="cleaning", vac="cleaning", area="0")]

    def reference(self):
        return run(S8, dict(BASE), self.START + cleaning((4, 8, 12, 16)))

    def test_one_unavailable_robot_tick_mid_session_is_bridged(self):
        reference = self.reference()
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(vac="unavailable", status="unavailable")]
                    + cleaning((16,)))
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], reference["used_ml"])
        self.assertEqual(state["bridged_gaps"], 1)

    def test_status_sensor_dropout_is_bridged(self):
        reference = self.reference()
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(status="unknown", vac="cleaning", area="12")]
                    + cleaning((16,)))
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], reference["used_ml"])

    def test_home_assistant_restart_is_bridged_when_cleaning_kept_pace(self):
        reference = run(S8, dict(BASE), self.START + cleaning((4, 8, 12, 16, 20, 24, 28)))
        state = run(S8, dict(BASE), self.START + cleaning((4, 8, 12)) + [dict(status="cleaning", vac="cleaning", area="28", _gap=240_000)])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], reference["used_ml"])

    def test_gap_that_could_hide_a_wash_is_not_bridged(self):
        # 4 minutes with only 4 m² while the robot cleans 4 m²/min: time went somewhere else.
        state = run(S8, dict(BASE), self.START + cleaning((4, 8, 12)) + [dict(status="cleaning", vac="cleaning", area="16", _gap=240_000)])
        self.assertTrue(state["accounting_incomplete"])

    def test_long_home_assistant_downtime_with_the_robot_unavailable_at_startup_is_not_bridged(self):
        # Review 2026-09-16: the gap must start at the last observation, not at the first unavailable tick.
        state = run(S8, dict(BASE), self.START + cleaning((4, 8, 10))
                    + [dict(vac="unavailable", status="unavailable", _gap=1_800_000),
                       dict(status="charging", vac="docked", area="30")])
        self.assertTrue(state["accounting_incomplete"])

    def test_short_gap_with_no_cleaning_progress_is_not_bridged(self):
        # An 85 s dropout while the area stood still: a wash could have happened.
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(vac="unavailable", status="unavailable", _gap=40_000)]
                    + [dict(status="cleaning", vac="cleaning", area="8", _gap=45_000)])
        self.assertTrue(state["accounting_incomplete"])

    def test_long_gap_still_marks_the_tank_incomplete(self):
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(vac="unavailable", status="unavailable")]
                    + [dict(status="cleaning", vac="cleaning", area="30", _gap=900_000)])
        self.assertTrue(state["accounting_incomplete"])

    def test_settings_changed_during_the_gap_are_not_bridged(self):
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(vac="unavailable", status="unavailable")]
                    + cleaning((16,), intensity="high"))
        self.assertTrue(state["accounting_incomplete"])

    def test_counter_restart_during_the_gap_is_not_bridged(self):
        state = run(S8, dict(BASE), self.START + cleaning((4, 8)) + [dict(vac="unavailable", status="unavailable")]
                    + cleaning((2,)))
        self.assertTrue(state["accounting_incomplete"])

    def test_gap_while_docked_needs_no_bridge(self):
        state = run(S8, dict(BASE), [dict(), dict(vac="unavailable", status="unavailable"), dict(_gap=3_600_000)])
        self.assertFalse(state.get("accounting_incomplete"))


class FailedWashTests(unittest.TestCase):
    def test_wash_interrupted_by_an_empty_dock_is_half_refunded(self):
        state = run(S8, {**BASE, "used_ml": 3500}, self.session_to_wash() + [
            dict(status="washing_the_mop", vac="docked", area="10", dock_err="water_empty")])
        record = state["calibration_history"][0]
        self.assertEqual(record["failed_wash_refund_ml"], 75.0)
        charged = 3500 + 10 * 6 + 150
        self.assertAlmostEqual(record["predicted_ml"], charged - 75, delta=0.5)

    def test_an_earlier_completed_wash_is_not_refunded(self):
        state = run(S8, {**BASE, "used_ml": 3500}, self.session_to_wash() + [
            dict(status="charging", vac="docked", area="10", _gap=600_000),
            dict(status="charging", vac="docked", area="10", dock_err="water_empty")])
        self.assertNotIn("failed_wash_refund_ml", state["calibration_history"][0])

    @staticmethod
    def session_to_wash():
        return [dict(status="cleaning", vac="cleaning", area="0"), dict(status="cleaning", vac="cleaning", area="10"),
                dict(status="going_to_wash_the_mop", vac="returning", area="10")]


class RollbackWindowTests(unittest.TestCase):
    def test_window_left_behind_by_an_older_release_is_ignored(self):
        stale = {"calibration_log_factors": [0.3, 0.31, 0.29], "calibration_samples": 0, "calibration_factor": 1}
        self.assertEqual(estimation.seed_log_factors(stale), [])
        self.assertEqual(estimation.uncertainty_log_factors(stale), [])
        relearned = {"calibration_log_factors": [0.3, 0.31, 0.29], "calibration_samples": 2, "calibration_factor": 1.1}
        self.assertEqual(len(estimation.seed_log_factors(relearned)), 2)
        current = {"calibration_log_factors": [0.3, 0.31], "calibration_samples": 2, "calibration_factor": 1.36}
        self.assertEqual(estimation.seed_log_factors(current), [0.3, 0.31])


if __name__ == "__main__":
    unittest.main()
