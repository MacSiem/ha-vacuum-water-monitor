"""5.9: how long the water lasts, how good the estimate was, and learning without a dock signal."""

from __future__ import annotations

import importlib
import unittest

from test_beta_runtime_path import BASE, SIGNALS, descriptor, effective, run, tick

forecast = importlib.import_module("vwmruntimepkg.forecast")
refill = importlib.import_module("vwmruntimepkg.refill")

DAY = 86_400_000
NOW = 100 * DAY


def runs(*waters, every_days=2):
    return [{"ts": NOW - i * every_days * DAY, "started_ts": NOW - i * every_days * DAY - 3_600_000, "water": w}
            for i, w in enumerate(waters)]


class SupplyForecastTests(unittest.TestCase):
    def test_needs_three_mopping_runs(self):
        result = forecast.supply_forecast({"automatic_sessions": runs(400, 380)}, 2000, NOW)
        self.assertIsNone(result["cleanings_left"])
        self.assertEqual(result["basis_runs"], 2)

    def test_vacuum_only_runs_and_unknown_water_are_ignored(self):
        sessions = runs(400, 0, None, 10, 420, 380)
        result = forecast.supply_forecast({"automatic_sessions": sessions}, 2000, NOW)
        self.assertEqual(result["basis_runs"], 3)
        self.assertEqual(result["water_per_cleaning_ml"], 400)
        self.assertEqual(result["cleanings_left"], 5)

    def test_days_left_from_recent_daily_use(self):
        # 400 ml every 2 days over the last 8 days -> 5 runs in a 8.04-day span.
        result = forecast.supply_forecast({"automatic_sessions": runs(400, 400, 400, 400, 400)}, 1000, NOW)
        self.assertEqual(result["cleanings_left"], 2)
        self.assertAlmostEqual(result["water_per_day_ml"], 2000 / (8 + 1 / 24), places=0)
        self.assertAlmostEqual(result["days_left"], 1000 / result["water_per_day_ml"], places=0)

    def test_no_daily_rate_in_the_first_week(self):
        result = forecast.supply_forecast({"automatic_sessions": runs(400, 400, 400, every_days=1)}, 3000, NOW)
        self.assertEqual(result["cleanings_left"], 7)
        self.assertIsNone(result["days_left"])

    def test_unknown_remaining_gives_rates_only(self):
        result = forecast.supply_forecast({"automatic_sessions": runs(400, 400, 400)}, None, NOW)
        self.assertIsNone(result["cleanings_left"])
        self.assertEqual(result["water_per_cleaning_ml"], 400)


class TrackRecordTests(unittest.TestCase):
    def test_last_tank_and_typical_error(self):
        history = [
            {"ts": 3, "error_percent": -2.0, "accepted": True, "reason": None},
            {"ts": 2, "error_percent": 40.0, "accepted": False, "reason": "calibration_sample_outlier"},
            {"ts": 1, "error_percent": 7.4, "accepted": True, "reason": None},
        ]
        result = forecast.estimate_track_record({"calibration_history": history})
        self.assertEqual(result["last_tank"]["error_percent"], -2.0)
        self.assertEqual(result["recent_errors_percent"], [-2.0, 40.0, 7.4])
        # A tank that was not learned (partial fill) does not count as the estimate's error.
        self.assertEqual(result["typical_error_percent"], 4.7)

    def test_no_history(self):
        self.assertEqual(forecast.estimate_track_record({})["last_tank"], None)


class UserEmptyAnchorTests(unittest.TestCase):
    """A robot whose dock cannot report an empty tank learns from the Tank empty button."""

    def setUp(self):
        signals = {k: v for k, v in SIGNALS.items() if v != "dock_error"}
        self.device = effective({}, descriptor(signals=signals))
        self.assertFalse(self.device.get("dock_error_sensor"))

    def test_pressing_tank_empty_anchors_and_learns(self):
        capacity = tick._device_capacity_ml(self.device)
        state = {**BASE, "used_ml": capacity * 0.8, "last_reset_ts": 1, "user_empty_active": True}
        state = run(self.device, state, [dict()])
        self.assertTrue(state["water_empty_active"])
        self.assertEqual(state["water_anchor_source"], "user_empty")
        self.assertEqual(state["water_anchor_kind"], "empty")
        tank = state["calibration_history"][0]
        self.assertAlmostEqual(tank["target_ml"], capacity * 0.95, places=0)
        self.assertTrue(tank["accepted"])
        self.assertEqual(state["calibration_samples"], 1)
        # Nothing more is counted until the refill; the refill clears the mark.
        before = state["used_ml"]
        state = run(self.device, state, [dict(status="cleaning", vac="cleaning", area=str(a)) for a in (46, 50)])
        self.assertEqual(state["used_ml"], before)
        refill.apply_refill(state, 99_000_000, "card", rebaseline=True)
        self.assertFalse(state["user_empty_active"])
        self.assertFalse(state["water_empty_active"])

    def test_tank_empty_right_after_a_mistaken_refill_is_not_swallowed(self):
        state = {**BASE, "used_ml": 0, "initialized": True, "last_reset_ts": 9_990_000,
                 "last_reset_source": "card", "user_empty_active": True}
        state = run(self.device, state, [dict()])
        self.assertTrue(state["water_empty_active"])
        self.assertFalse(state.get("water_empty_acknowledged"))
        self.assertEqual(state["water_anchor_source"], "user_empty")

    def test_a_short_tank_is_anchored_but_not_learned(self):
        capacity = tick._device_capacity_ml(self.device)
        state = {**BASE, "used_ml": capacity * 0.1, "last_reset_ts": 1, "user_empty_active": True}
        state = run(self.device, state, [dict()])
        self.assertTrue(state["water_empty_active"])
        self.assertEqual(state.get("calibration_samples", 0), 0)


if __name__ == "__main__":
    unittest.main()
