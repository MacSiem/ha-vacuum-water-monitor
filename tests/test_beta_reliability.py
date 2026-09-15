"""Regression tests for the 5.7 accounting reliability contract.

Each scenario reproduces a defect observed in 5.5.0-5.6.0 (GitHub issue #12 and the
2026-09-15 adversarial review): refill self-invalidation, per-session area counter
restarts, lost sub-threshold area increments, restarts while docked, masked
incomplete flags, false refills on unrelated dock errors, double-counted wash
sequences and calibration lost on a mop-setting change.
"""

from __future__ import annotations

import asyncio
import unittest

from test_tick import _Hass, _State, tick
from test_user_device_removal import storage


ROBOT = {
    "vacuum_entity": "vacuum.robot",
    "status_sensor": "sensor.robot_status",
    "area_sensor": "sensor.robot_area",
    "mop_mode_entity": "select.robot_mop_mode",
    "mop_intensity_entity": "select.robot_mop_intensity",
    "dock_error_sensor": "sensor.robot_dock_error",
    "tracked_capacity_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "rate_signal": "mop_mode",
    "usage_ml_per_m2": {"fast": 4, "standard": 6, "deep": 9},
    "wash_volume_ml": 150,
    "calibration_scope": "floor_only",
    "accounting_evidence": "user_calibration",
}


def hass(status="charging", vac="docked", area="45.5", mode="standard", dock_err="ok",
         vac_available=True):
    values = {
        "sensor.robot_status": _State(status),
        "sensor.robot_area": _State(str(area), {"unit_of_measurement": "m²"}),
        "select.robot_mop_mode": _State(mode),
        "select.robot_mop_intensity": _State("medium"),
        "sensor.robot_dock_error": _State(dock_err),
    }
    values["vacuum.robot"] = _State(vac if vac_available else "unavailable", {"status": status})
    return _Hass(values, length_unit="km")


def run(state, steps, device=None, start_ts=10_000_000, step_ms=60_000):
    device = device or ROBOT
    ts = start_ts
    for kwargs in steps:
        ts += kwargs.pop("_gap_ms", step_ms)
        state, _dirty = tick.tick_device(hass(**kwargs), device, state, now_ts=ts)
    return state, ts


def refilled_state(previous):
    async def reset():
        st = storage.VacuumWaterStorage(None)
        await st.async_set_tank_state("vacuum.robot", previous)
        return await st.async_reset_tank("vacuum.robot", "2026-09-15T17:42:44+00:00", 9_000_000)
    return asyncio.run(reset())


class RefillBaselineTests(unittest.TestCase):
    def test_refill_while_docked_stays_complete(self):
        state = refilled_state({"used_ml": 3100, "initialized": True, "last_area": 45.5,
                                "last_status": "charging", "accounting_incomplete": True})
        state, _ = run(state, [{}, {}, {}])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], 0)


class AreaCounterTests(unittest.TestCase):
    def test_per_session_counter_restart_is_a_new_baseline_not_a_gap(self):
        state = {"used_ml": 0, "initialized": True, "last_area": 45.5, "last_status": "charging",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [
            {"status": "cleaning", "vac": "cleaning", "area": "0"},
            {"status": "cleaning", "vac": "cleaning", "area": "2.0"},
            {"status": "cleaning", "vac": "cleaning", "area": "4.5"},
        ])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertAlmostEqual(state["used_ml"], 4.5 * 6, places=2)

    def test_restart_observed_after_mopping_already_began_counts_area_since_restart(self):
        state = {"used_ml": 0, "initialized": True, "last_area": 45.5, "last_status": "charging",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [{"status": "cleaning", "vac": "cleaning", "area": "1.2"}])
        self.assertAlmostEqual(state["used_ml"], 1.2 * 6, places=2)
        self.assertFalse(state.get("accounting_incomplete"))

    def test_sub_threshold_increments_accumulate_instead_of_being_lost(self):
        state = {"used_ml": 0, "initialized": True, "last_area": 10.0, "last_status": "cleaning",
                 "last_tick_ts": 9_940_000}
        steps = [{"status": "cleaning", "vac": "cleaning", "area": f"{10 + 0.05 * i:.2f}"}
                 for i in range(1, 21)]
        state, _ = run(state, steps)
        self.assertAlmostEqual(state["used_ml"], 1.0 * 6, delta=0.35)


class RestartAndGapTests(unittest.TestCase):
    def test_unavailable_robot_while_docked_does_not_invalidate_balance(self):
        state = {"used_ml": 500, "initialized": True, "last_area": 45.5, "last_status": "charging",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [{"vac_available": False}, {}, {}])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], 500)

    def test_long_tick_gap_while_docked_does_not_invalidate_balance(self):
        state = {"used_ml": 500, "initialized": True, "last_area": 45.5, "last_status": "charging",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [{"_gap_ms": 3_600_000}, {}])
        self.assertFalse(state.get("accounting_incomplete"))

    def test_gap_while_mopping_is_still_reported_incomplete(self):
        state = {"used_ml": 500, "initialized": True, "last_area": 10.0, "last_status": "cleaning",
                 "last_tick_ts": 9_940_000, "session_start_ts": 9_000_000}
        state, _ = run(state, [
            {"status": "cleaning", "vac": "cleaning", "area": "12.0", "_gap_ms": 900_000},
            {"status": "cleaning", "vac": "cleaning", "area": "14.0"},
        ])
        self.assertTrue(state.get("accounting_incomplete"))

    def test_missing_rate_while_mopping_is_not_masked_by_a_later_reason(self):
        device = {**ROBOT, "usage_ml_per_m2": {}, "wash_volume_ml": None, "tracked_reservoir": None}
        state = {"used_ml": 0, "initialized": True, "last_area": 10.0, "last_status": "cleaning",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [
            {"status": "cleaning", "vac": "cleaning", "area": "12.0", "dock_err": "water_empty"},
        ], device=device)
        self.assertTrue(state.get("accounting_incomplete"))


class RefillDetectionTests(unittest.TestCase):
    def _empty_state(self):
        return {"used_ml": 3700, "initialized": True, "last_area": 45.5, "last_status": "charging",
                "last_dock_err": "water_empty", "water_empty_active": True,
                "water_anchor_source": "dock_error", "last_tick_ts": 9_940_000, "last_reset_ts": 0}

    def test_unrelated_dock_error_after_empty_is_not_a_refill(self):
        device = {**ROBOT, "refill_on_clear": True, "water_anchor_reservoir": "dock_clean"}
        state, _ = run(self._empty_state(), [{"dock_err": "waste_water_tank_full"}], device=device)
        self.assertNotEqual(state["used_ml"], 0)

    def test_empty_cleared_to_ok_is_a_refill(self):
        device = {**ROBOT, "refill_on_clear": True, "water_anchor_reservoir": "dock_clean"}
        state, _ = run(self._empty_state(), [{"dock_err": "ok"}], device=device)
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_accounting_reason"], "refill_detected")


class WashSequenceTests(unittest.TestCase):
    def test_docking_between_wash_phases_does_not_start_a_second_wash(self):
        state = {"used_ml": 0, "initialized": True, "last_area": 20.0, "last_status": "cleaning",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [
            {"status": "going_to_wash_the_mop", "vac": "cleaning", "area": "20.0"},
            {"status": "docking", "vac": "returning", "area": "20.0"},
            {"status": "washing_the_mop", "vac": "docked", "area": "20.0"},
            {"status": "washing_the_mop", "vac": "docked", "area": "20.0"},
            {"status": "cleaning", "vac": "cleaning", "area": "20.0"},
        ])
        self.assertEqual(state["used_ml"], 150)

    def test_next_wash_after_mopping_resumes_is_counted(self):
        state = {"used_ml": 0, "initialized": True, "last_area": 20.0, "last_status": "cleaning",
                 "last_tick_ts": 9_940_000}
        state, _ = run(state, [
            {"status": "washing_the_mop", "vac": "docked", "area": "20.0"},
            {"status": "cleaning", "vac": "cleaning", "area": "20.0"},
            {"status": "going_to_wash_the_mop", "vac": "cleaning", "area": "20.0"},
        ])
        self.assertEqual(state["used_ml"], 300)


class CalibrationPersistenceTests(unittest.TestCase):
    def _calibrated(self):
        state = {"used_ml": 100, "initialized": True, "last_area": 45.5, "last_status": "charging",
                 "last_tick_ts": 9_940_000, "calibration_factor": 1.3, "calibration_samples": 2}
        state, _ = run(state, [{}])
        self.assertEqual(state["calibration_factor"], 1.3)
        return state

    def test_mop_mode_change_keeps_calibration(self):
        state, _ = run(self._calibrated(), [{"mode": "deep"}, {"mode": "fast"}])
        self.assertEqual(state["calibration_factor"], 1.3)
        self.assertEqual(state["calibration_samples"], 2)

    def test_dataset_revision_change_keeps_calibration(self):
        state = self._calibrated()
        snapshot = tick.consumption_profiles.CONSUMPTION_SNAPSHOT
        original = snapshot.get("dataset_version")
        try:
            snapshot["dataset_version"] = "9.9.9-test"
            state, _ = run(state, [{}], start_ts=20_000_000)
        finally:
            snapshot["dataset_version"] = original
        self.assertEqual(state["calibration_factor"], 1.3)

    def test_model_change_resets_calibration(self):
        device = {**ROBOT, "profile_key": "another_model"}
        state, _ = run(self._calibrated(), [{}], device=device, start_ts=20_000_000)
        self.assertEqual(state["calibration_factor"], 1)
        self.assertEqual(state["calibration_samples"], 0)

    def test_upgrade_from_state_without_static_context_does_not_reset(self):
        state = self._calibrated()
        state.pop("accounting_context_static", None)
        state.pop("accounting_context_calibration", None)
        state["accounting_context"] = "legacy-5.6-hash"
        state, _ = run(state, [{}], start_ts=20_000_000)
        self.assertEqual(state["calibration_factor"], 1.3)


if __name__ == "__main__":
    unittest.main()
