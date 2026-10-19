"""Contract tests for private nominal time learning (no Home Assistant needed)."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components/ha_vacuum_water_monitor/nominal_time_learning.py"
if not MODULE.exists():  # Standalone artifact before integration.
    MODULE = ROOT / "nominal_time_learning.py"
SPEC = importlib.util.spec_from_file_location("nominal_time_learning", MODULE)
learning = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(learning)

CONTEXT = {
    "device_id": "vacuum.one", "reservoir": "robot_clean",
    "firmware": "1.2", "settings": {"water_level": "medium", "route": "normal"},
}


def full(state=None, *, context=CONTEXT, now=1_000, capacity=100):
    return learning.start_full(
        state or {}, context=context, capacity_ml=capacity, now_ts=now,
    )


def observe(state, now, active, *, context=CONTEXT, capacity=100, available=True):
    return learning.observe(state, now_ts=now, active=active, context=context,
                            capacity_ml=capacity, available=available)


def result(state, *, context=CONTEXT, capacity=100):
    return learning.resolve(state, context=context, capacity_ml=capacity)


def tank(state=None, *, context=CONTEXT, now=1_000, minutes=10, capacity=100):
    """Ten active minutes consume the assumed usable 95 ml: 9.5 ml/min."""
    state = full(state, context=context, now=now, capacity=capacity)
    state = observe(state, now, True, context=context, capacity=capacity)
    remaining = minutes * 60_000
    while remaining:
        step = min(60_000, remaining)
        now += step
        remaining -= step
        state = observe(state, now, True, context=context, capacity=capacity)
    return learning.finish_empty(state, now_ts=now, context=context, capacity_ml=capacity)


class NominalTimeLearningTests(unittest.TestCase):
    def test_two_cycles_are_provisional_and_three_activate_median(self):
        state = tank(minutes=10)
        self.assertEqual(result(state)["status"], "provisional")
        self.assertIsNone(result(state)["usage_ml_per_active_minute"])
        state = tank(state, minutes=9, now=2_000_000)
        self.assertEqual(result(state)["status"], "provisional")
        state = tank(state, minutes=11, now=4_000_000)
        resolved = result(state)
        self.assertEqual(resolved["status"], "active")
        self.assertAlmostEqual(resolved["usage_ml_per_active_minute"], 9.5)
        self.assertEqual(resolved["accuracy"], "not_established")
        self.assertEqual(resolved["scope"], "private_device")
        self.assertEqual(resolved["residual_assumed_percent"], 5)

    def test_idle_vacuum_and_dock_wash_never_add_minutes(self):
        state = full()
        # active=False covers vacuum-only, dock washing and normal idle.
        for now in (1_000, 61_000, 121_000, 181_000):
            state = observe(state, now, False)
        state = observe(state, 181_000, True)
        state = observe(state, 241_000, False)
        state = observe(state, 10_000_000, False)  # Long, observed idle is safe.
        state = observe(state, 10_000_000, True)
        state = observe(state, 10_060_000, False)
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=10_060_000)
        sample = state["contexts"][0]["samples"][0]
        self.assertAlmostEqual(sample["active_minutes"], 2)
        self.assertAlmostEqual(sample["rate_ml_per_minute"], 47.5)

    def test_missing_rate_does_not_block_independent_time_observation(self):
        # There is deliberately no supplied coefficient or accounting-complete flag.
        state = tank()
        self.assertEqual(result(state)["sample_count"], 1)

    def test_active_gap_over_180_seconds_discards_the_cycle(self):
        state = observe(full(), 1_000, True)
        state = observe(state, 181_001, True)
        self.assertEqual(state["last_reason"], "active_observation_gap")
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=181_001)
        self.assertEqual(result(state)["sample_count"], 0)

    def test_exact_gap_boundary_is_included(self):
        state = observe(full(), 1_000, True)
        state = observe(state, 181_000, False)
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=181_000)
        self.assertAlmostEqual(state["contexts"][0]["samples"][0]["active_minutes"], 3)

    def test_unavailable_or_unknown_activity_discards_even_during_idle(self):
        for active, available in ((True, False), (False, False), (None, True), (1, True)):
            with self.subTest(active=active, available=available):
                state = observe(full(), 2_000, active, available=available)
                self.assertIsNone(state["cycle"])

    def test_settings_capacity_firmware_and_device_changes_discard_cycle(self):
        contexts = []
        for field, value in (("firmware", "1.3"), ("device_id", "vacuum.two"),
                             ("reservoir", "dock_clean")):
            contexts.append({**CONTEXT, field: value})
        contexts.append({**CONTEXT, "settings": {"water_level": "high", "route": "normal"}})
        contexts.append({**CONTEXT, "settings": {"water_level": "medium"}})
        for context in contexts:
            with self.subTest(context=context):
                state = observe(full(), 2_000, True, context=context)
                self.assertIsNone(state["cycle"])
        self.assertIsNone(observe(full(), 2_000, True, capacity=101)["cycle"])

    def test_mid_cycle_refill_restarts_without_learning_partial_tank(self):
        state = observe(full(), 1_000, True)
        state = observe(state, 61_000, True)
        state = full(state, now=61_000)
        self.assertEqual(state["last_reason"], "refill_during_cycle")
        self.assertEqual(result(state)["sample_count"], 0)
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=61_000)
        self.assertEqual(result(state)["sample_count"], 0)

    def test_no_active_minutes_and_duplicate_empty_do_not_make_samples(self):
        state = learning.finish_empty(full(), context=CONTEXT, capacity_ml=100, now_ts=1_000)
        self.assertEqual(result(state)["sample_count"], 0)
        state = tank()
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=601_000)
        self.assertEqual(result(state)["sample_count"], 1)

    def test_outlier_does_not_promote_before_three_consistent_cycles(self):
        state = tank(minutes=10)
        state = tank(state, minutes=1, now=2_000_000)
        state = tank(state, minutes=10, now=4_000_000)
        self.assertEqual(result(state)["status"], "provisional")
        state = tank(state, minutes=10, now=6_000_000)
        self.assertEqual(result(state)["status"], "provisional")
        state = tank(state, minutes=10, now=8_000_000)
        self.assertEqual(result(state)["status"], "active")
        self.assertAlmostEqual(result(state)["usage_ml_per_active_minute"], 9.5)

    def test_post_activation_outlier_cannot_change_the_rate(self):
        state = {}
        for index in range(3):
            state = tank(state, now=1_000 + index * 2_000_000)
        state = tank(state, minutes=1, now=8_000_000)
        self.assertEqual(state["last_reason"], "time_sample_outlier")
        self.assertEqual(result(state)["status"], "active")
        self.assertAlmostEqual(result(state)["usage_ml_per_active_minute"], 9.5)

    def test_contexts_and_robots_remain_independent_and_old_samples_survive(self):
        state = {}
        other = {**CONTEXT, "device_id": "vacuum.two"}
        for index in range(3):
            state = tank(state, now=1_000 + index * 2_000_000)
        state = tank(state, context=other, minutes=5, now=8_000_000)
        self.assertEqual(result(state, context=other)["status"], "provisional")
        self.assertAlmostEqual(result(state)["usage_ml_per_active_minute"], 9.5)
        self.assertEqual(result(state, capacity=101)["status"], "unavailable")

    def test_json_round_trip_mid_cycle_preserves_observation_and_samples(self):
        state = tank()
        state = full(state, now=2_000_000)
        state = observe(state, 2_000_000, True)
        state = json.loads(json.dumps(state, allow_nan=False))
        state = observe(state, 2_060_000, False)
        state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100, now_ts=2_060_000)
        self.assertEqual(result(state)["sample_count"], 2)
        self.assertAlmostEqual(state["contexts"][0]["samples"][-1]["active_minutes"], 1)

    def test_operations_never_mutate_the_callers_state_or_context(self):
        state = full()
        before = deepcopy(state)
        updated = observe(state, 1_000, True)
        self.assertEqual(state, before)
        updated["cycle"]["context"]["settings"]["water_level"] = "changed"
        self.assertEqual(CONTEXT["settings"]["water_level"], "medium")

    def test_invalid_numbers_are_rejected_without_creating_cycles(self):
        for value in (True, False, float("nan"), float("inf"), 0, -1, "100"):
            with self.subTest(value=value):
                self.assertIsNone(full(capacity=value)["cycle"])
                self.assertIsNone(full(now=value)["cycle"])
                self.assertIsNone(observe(full(), value, True)["cycle"])

    def test_backward_clock_and_explicit_invalidation_preserve_prior_samples(self):
        state = full(tank(), now=2_000_000)
        state = observe(state, 1_999_999, True)
        self.assertEqual(state["last_reason"], "invalid_observation_time")
        self.assertEqual(result(state)["sample_count"], 1)
        state = learning.invalidate(full(state, now=3_000_000), "settings_changed")
        self.assertIsNone(state["cycle"])
        self.assertEqual(result(state)["sample_count"], 1)

    def test_history_is_bounded_without_outliers_evicting_the_active_estimate(self):
        state = {}
        for index in range(3):
            state = tank(state, now=1_000 + index * 2_000_000)
        for index in range(30):
            state = tank(state, minutes=1, now=8_000_000 + index * 2_000_000)
        self.assertLessEqual(len(state["contexts"][0]["samples"]), 8)
        self.assertAlmostEqual(result(state)["usage_ml_per_active_minute"], 9.5)

    def test_malformed_context_and_nonfinite_stored_sample_cannot_resolve(self):
        for context in ({}, {"device_id": "vacuum.one"}, {**CONTEXT, "settings": {}},
                        {**CONTEXT, "settings": {"water_level": float("nan")}}):
            self.assertIsNone(full(context=context)["cycle"])
        state = tank()
        state["contexts"][0]["samples"][0]["rate_ml_per_minute"] = float("nan")
        self.assertEqual(result(state)["status"], "unavailable")

    def test_empty_without_confirmed_full_or_with_unavailable_state_cannot_learn(self):
        for state in ({}, observe(full(), 1_000, True)):
            state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100,
                                          now_ts=61_000, available=False)
            self.assertEqual(result(state)["sample_count"], 0)

    def test_explicit_residual_assumption_does_not_reuse_default_samples(self):
        state = {}
        for index in range(3):
            now = 1_000 + index * 2_000_000
            state = learning.start_full(state, context=CONTEXT, capacity_ml=100,
                                        now_ts=now, residual_percent=10)
            state = observe(state, now, True)
            for offset in range(1, 11):
                state = observe(state, now + offset * 60_000, True)
            state = learning.finish_empty(state, context=CONTEXT, capacity_ml=100,
                                          now_ts=now + 600_000)
        resolved = learning.resolve(state, context=CONTEXT, capacity_ml=100, residual_percent=10)
        self.assertEqual(resolved["status"], "active")
        self.assertAlmostEqual(resolved["usage_ml_per_active_minute"], 9)
        self.assertEqual(result(state)["status"], "unavailable")
        for residual in (True, float("nan"), float("inf"), -1, 100):
            invalid = learning.start_full(state, context=CONTEXT, capacity_ml=100,
                                         now_ts=8_000_000, residual_percent=residual)
            self.assertIsNone(invalid["cycle"])

    def test_switching_settings_preserves_the_previous_context_for_later_use(self):
        state = {}
        for index in range(3):
            state = tank(state, now=1_000 + index * 2_000_000)
        high = {**CONTEXT, "settings": {"water_level": "high", "route": "normal"}}
        state = tank(state, context=high, minutes=5, now=8_000_000)
        self.assertEqual(result(state, context=high)["status"], "provisional")
        self.assertEqual(result(state)["status"], "active")
        self.assertAlmostEqual(result(state)["usage_ml_per_active_minute"], 9.5)


if __name__ == "__main__":
    unittest.main()

class CounterTimeLearningTests(unittest.TestCase):
    def test_counter_minutes_replace_wall_time_and_missing_counter_invalidates(self):
        state = learning.start_full({}, context=CONTEXT, capacity_ml=100, now_ts=1_000)
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=1_000,
                                 active=True, use_counter=True, counter_minutes=0)
        # Polls can be 30 seconds apart while the minute counter stays at zero.
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=31_000,
                                 active=True, use_counter=True, counter_minutes=0)
        self.assertEqual(state["cycle"]["active_minutes"], 0)
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=61_000,
                                 active=True, use_counter=True, counter_minutes=1)
        self.assertEqual(state["cycle"]["active_minutes"], 1)
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=91_000,
                                 active=True, use_counter=True, counter_minutes=None)
        self.assertIsNone(state["cycle"])

    def test_counter_reset_during_active_run_invalidates_sample(self):
        state = learning.start_full({}, context=CONTEXT, capacity_ml=100, now_ts=1_000)
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=1_000,
                                 active=True, use_counter=True, counter_minutes=10)
        state = learning.observe(state, context=CONTEXT, capacity_ml=100, now_ts=61_000,
                                 active=True, use_counter=True, counter_minutes=0)
        self.assertIsNone(state["cycle"])
