"""Accuracy benchmark for labelled estimates and the empty-tank calibrator.

The truth generator deliberately has a different structure from the estimator:
pump flow in ml/min over mopping minutes, route speed, carpet lift, adaptive
flow noise, per-wash volume noise, base self-clean, an unusable residual in the
tank, occasional untracked top-ups and duplicated/missed wash statuses. The
estimator sees only what Home Assistant exposes (area by route and water level,
wash status count) plus the catalogue prior. The metric is prequential: the
predicted consumption at the empty-tank signal is scored before the calibrator
learns from that tank.

Assumptions are illustrative; thresholds guard against regressions in method
quality, they are not accuracy promises for a particular robot.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import random
import unittest

PKG = Path(__file__).resolve().parents[1] / "custom_components/ha_vacuum_water_monitor"
_spec = importlib.util.spec_from_file_location("vwm_bench_estimation", PKG / "estimation.py")
estimation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(estimation)

ROUTES = ("fast", "standard", "deep")
LEVELS = ("low", "medium", "high")
SPEED = {"fast": 1.1, "standard": 0.85, "deep": 0.6}
FLOW = {"pad": {"low": 3.0, "medium": 5.0, "high": 7.5},
        "roller": {"low": 6.0, "medium": 9.0, "high": 12.0}}
CAPACITY = 4000.0
# Production closes an estimated dock tank at capacity minus the default 5% residual.
ASSUMED_RESIDUAL = CAPACITY * estimation.DEFAULT_EMPTY_RESIDUAL_PERCENT / 100


def _percentile(values, q):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def _simulate(kind, prior_system, calibrate=True, devices=120, tanks=7, seed=20260915, topup=0.02):
    rng = random.Random(seed)
    prior = estimation.CLASS_PRIORS[prior_system]
    errors = [[] for _ in range(tanks)]
    for _ in range(devices):
        flow_mult = rng.gauss(1, 0.10)
        speed_mult = {r: rng.gauss(1, 0.05) for r in ROUTES}
        wash_ml = 150 * rng.gauss(0.9, 0.10)
        final_ml = 150 * rng.gauss(0.9, 0.10) if kind == "pad" else 200 * rng.gauss(1, 0.1)
        base_ml = rng.uniform(20, 60)
        residual = rng.uniform(120, 320)
        carpet = rng.uniform(0, 0.25)
        log_factors: list[float] = []
        for tank in range(tanks):
            weights = ([rng.random() + 0.2 for _ in ROUTES], [rng.random() + 0.2 for _ in LEVELS])
            level = CAPACITY
            drawn = 0.0
            predicted_raw = 0.0
            while True:
                route = rng.choices(ROUTES, weights[0])[0]
                water = rng.choices(LEVELS, weights[1])[0]
                area = rng.uniform(20, 60)
                minutes = area / (SPEED[route] * speed_mult[route])
                lift = min(0.5, carpet * rng.uniform(0.5, 1.5))
                floor = FLOW[kind][water] * flow_mult * rng.gauss(1, 0.08) * minutes * (1 - lift)
                if kind == "pad":
                    mids = int(minutes // 15)
                    washes = mids + 1
                    wash = sum(wash_ml * rng.gauss(1, 0.08) for _ in range(mids)) + final_ml * rng.gauss(1, 0.08)
                else:
                    washes = 1
                    wash = final_ml * rng.gauss(1, 0.08)
                truth = floor + wash + base_ml
                observed_washes = max(0, washes + (rng.random() < 0.05) - (rng.random() < 0.03))
                estimate = (area * prior["usage_ml_per_m2"][route] * prior["intensity_factor"][water]
                            + observed_washes * prior["wash_volume_ml"])
                available = level - residual
                if truth <= available:
                    level -= truth
                    drawn += truth
                    predicted_raw += estimate
                    if rng.random() < topup:
                        level = CAPACITY
                else:
                    fraction = max(available, 0) / truth
                    drawn += max(available, 0)
                    predicted_raw += estimate * fraction
                    break
            factor = math.exp(estimation.median(log_factors)) if log_factors else 1.0
            errors[tank].append(abs(predicted_raw * factor - drawn) / drawn)
            if calibrate:
                observed = (CAPACITY - ASSUMED_RESIDUAL) / predicted_raw
                log_factors, _factor, _accepted, _reason = estimation.update_calibration(log_factors, observed)
    return [(_percentile(e, 0.5) * 100, _percentile(e, 0.9) * 100) for e in errors]


class EstimationBenchmarkTests(unittest.TestCase):
    def test_owner_prior_on_pad_robot_converges_after_three_tanks(self):
        result = _simulate("pad", "pad")
        for median, p90 in result[3:]:
            self.assertLessEqual(median, 5.0, result)
            self.assertLessEqual(p90, 12.0, result)

    def test_wrong_structure_prior_on_roller_robot_is_corrected(self):
        result = _simulate("roller", "pad")
        self.assertGreater(result[0][0], 20.0, result)
        for median, p90 in result[4:]:
            self.assertLessEqual(median, 8.0, result)
            self.assertLessEqual(p90, 20.0, result)

    def test_calibration_beats_prior_only(self):
        calibrated = _simulate("pad", "rotating_pads")
        prior_only = _simulate("pad", "rotating_pads", calibrate=False)
        self.assertLess(calibrated[-1][0], prior_only[-1][0])
        self.assertLess(calibrated[-1][1], prior_only[-1][1])

    def test_single_abnormal_tank_does_not_move_a_learned_factor(self):
        window: list[float] = []
        for value in (1.30, 1.33, 1.31, 1.32):
            window, factor, accepted, _ = estimation.update_calibration(window, value)
            self.assertTrue(accepted)
        window, after, accepted, reason = estimation.update_calibration(window, 3.5)
        self.assertFalse(accepted)
        self.assertEqual(reason, "calibration_sample_outlier")
        self.assertAlmostEqual(after, factor, places=6)


if __name__ == "__main__":
    unittest.main()
