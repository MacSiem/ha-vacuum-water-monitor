"""5.7.0-beta.2 accuracy: area before a wash or return, Roborock water levels."""

from __future__ import annotations

import unittest

from test_beta_runtime_path import BASE, descriptor, effective, run

S8 = effective({}, descriptor())


def floor_ml_before(status, vac):
    state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0"),
                                 dict(status="cleaning", vac="cleaning", area="5")])
    before = state["used_ml"]
    state = run(S8, state, [dict(status=status, vac=vac, area="7")], ts=10_120_000)
    return state["used_ml"] - before, state


class AreaAtTransitionTests(unittest.TestCase):
    def test_prewash_before_new_task_area_reset_keeps_balance_complete(self):
        state = run(S8, dict(BASE), [
            dict(status="charging", vac="docked", area="22.7", intensity="off"),
            dict(status="charging", vac="docked", area="22.7", intensity="standard"),
            dict(status="washing_the_mop", vac="docked", area="22.7", intensity="standard"),
            dict(status="washing_the_mop", vac="docked", area="0", intensity="standard"),
            dict(status="cleaning", vac="cleaning", area="0", intensity="standard"),
            dict(status="cleaning", vac="cleaning", area="5", intensity="standard"),
        ])
        self.assertAlmostEqual(state["used_ml"], 150 + 5 * 6, places=1)
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertFalse(state.get("session_water_broken"))

    def test_area_cleaned_before_heading_to_wash_is_charged(self):
        added, _ = floor_ml_before("going_to_wash_the_mop", "returning")
        self.assertAlmostEqual(added, 2 * 6 + 150, places=1)

    def test_area_cleaned_before_returning_is_charged(self):
        added, state = floor_ml_before("returning_home", "returning")
        self.assertAlmostEqual(added, 2 * 6, places=1)
        self.assertFalse(state.get("accounting_incomplete"))

    def test_area_counter_moving_while_docked_after_docking_is_not_floor_water(self):
        state = run(S8, dict(BASE), [dict(status="charging", area="45.5"), dict(status="charging", area="47.5")])
        self.assertEqual(state["used_ml"], 0)


class SavedScopeTests(unittest.TestCase):
    def test_capacity_saved_with_a_scope_but_no_rate_keeps_counting_washes(self):
        custom = {"entity:vacuum.robot": {"tracked_capacity_ml": 4000, "calibration_scope": "whole_cycle"}}
        dev = effective({"custom_calibration": custom}, descriptor())
        self.assertEqual(dev["calibration_scope"], "floor_only")
        state = run(dev, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0"),
                                      dict(status="cleaning", vac="cleaning", area="10"),
                                      dict(status="going_to_wash_the_mop", vac="returning", area="10")])
        self.assertAlmostEqual(state["used_ml"], 10 * 6 + 150, places=1)

    def test_a_measured_whole_cycle_rate_keeps_its_scope(self):
        custom = {"entity:vacuum.robot": {"usage_ml_per_m2": {"default": 20}, "calibration_scope": "whole_cycle"}}
        dev = effective({"custom_calibration": custom}, descriptor())
        self.assertEqual(dev["calibration_scope"], "whole_cycle")


class WaterLevelTests(unittest.TestCase):
    def ml_for(self, level):
        state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity=level),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity=level)])
        return state

    def test_roborock_levels_map_to_the_estimate(self):
        expected = {"mild": 42, "standard": 60, "intense": 78, "extreme": 90, "slight": 42, "min": 42, "max": 78}
        for level, ml in expected.items():
            with self.subTest(level=level):
                state = self.ml_for(level)
                self.assertAlmostEqual(state["used_ml"], ml, places=1)
                self.assertIsNone(state.get("intensity_unmapped"))

    def test_levels_without_a_factor_are_not_billed_as_medium(self):
        for level in ("smart_mode", "custom_water_flow", "custom"):
            with self.subTest(level=level):
                state = self.ml_for(level)
                self.assertEqual(state["used_ml"], 0)
                self.assertEqual(state["intensity_unmapped"], level)
                self.assertTrue(state.get("accounting_incomplete"))

    def test_time_fallback_respects_the_same_water_level_factors_as_area(self):
        device = {**S8, "area_sensor": None,
                  "usage_ml_per_active_minute": {"default": 2},
                  "time_accounting_evidence": "user_measured"}
        for level, expected_ml in (("mild", 1.4), ("standard", 2.0),
                                   ("intense", 2.6), ("extreme", 3.0)):
            with self.subTest(level=level):
                first = run(device, dict(BASE), [dict(status="cleaning", vac="cleaning",
                                                      intensity=level)])
                before = first["used_ml"]
                after = run(device, first, [dict(status="cleaning", vac="cleaning",
                                                 intensity=level)], ts=10_060_000)
                self.assertAlmostEqual(after["used_ml"] - before, expected_ml, places=2)
                self.assertFalse(after.get("accounting_incomplete"))

    def test_unmapped_level_does_not_escape_through_time_fallback(self):
        device = {**S8, "area_sensor": None,
                  "usage_ml_per_active_minute": {"default": 2},
                  "time_accounting_evidence": "user_measured"}
        state = run(device, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0",
                                             intensity="custom_water_flow")])
        self.assertEqual(state["used_ml"], 0)
        self.assertTrue(state.get("accounting_incomplete"))


if __name__ == "__main__":
    unittest.main()
