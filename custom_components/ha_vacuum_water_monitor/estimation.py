"""Labelled consumption estimates and the empty-tank calibrator.

Policy (decision 2026-09-15): a recognised mopping robot always gets a usage
estimate. Every number carries the basis it came from and a deterministic
uncertainty, and the device learns a correction scale from the tracked
reservoir's own empty-tank signal. Physical sensors and user calibration keep
precedence over any estimate.

The calibrator was selected on an independent physics benchmark
(tests/test_estimation_benchmark.py): the median of recent per-tank factors
converges fastest when refills are full, and a wide outlier gate keeps a
single abnormal tank from dominating.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

LABELED_ESTIMATE = "labeled_estimate"

# Ordered from most to least specific. The uncertainty is a documented,
# deterministic property of the basis, never a per-record invented percentage.
BASIS_UNCERTAINTY_PERCENT: dict[str, int] = {
    "fleet_posterior": 15,
    "owner_device": 20,
    "manufacturer_declared": 20,
    "review_measured": 25,
    "family_transfer": 35,
    "class_prior": 50,
    "generic_prior": 65,
}
ESTIMATE_BASES = frozenset(BASIS_UNCERTAINTY_PERCENT)
MOP_SYSTEMS = frozenset({"pad", "rotating_pads", "roller", "unknown"})

_INTENSITY_FACTOR = {"low": 0.7, "medium": 1.0, "high": 1.3, "default": 1.0}

# Class priors. The pad prior is the owner-validated Roborock S8 MaxV Ultra DIY
# accounting (ml/m2 by route x water-level factor, 150 ml per dock wash); other
# classes scale it by their mopping mechanism and are labelled class_prior.
CLASS_PRIORS: dict[str, dict[str, Any]] = {
    "pad": {
        "rate_signal": "mop_mode",
        "usage_ml_per_m2": {"fast": 4, "standard": 6, "deep": 9, "deep_plus": 11, "default": 6},
        "intensity_factor": dict(_INTENSITY_FACTOR),
        "wash_volume_ml": 150,
    },
    "rotating_pads": {
        "rate_signal": "mop_mode",
        "usage_ml_per_m2": {"fast": 5, "standard": 7, "deep": 10, "deep_plus": 12, "default": 7},
        "intensity_factor": dict(_INTENSITY_FACTOR),
        "wash_volume_ml": 120,
    },
    "roller": {
        "rate_signal": "mop_mode",
        "usage_ml_per_m2": {"fast": 7, "standard": 10, "deep": 13, "deep_plus": 15, "default": 10},
        "intensity_factor": dict(_INTENSITY_FACTOR),
        "wash_volume_ml": 200,
    },
    "unknown": {
        "rate_signal": "mop_mode",
        "usage_ml_per_m2": {"default": 7},
        "intensity_factor": dict(_INTENSITY_FACTOR),
        "wash_volume_ml": 120,
    },
}

CALIBRATION_WINDOW = 8
# Unusable water left in a dock tank when it reports empty (pump intake height).
DEFAULT_EMPTY_RESIDUAL_PERCENT = 5.0
MIN_CALIBRATION_CYCLE_FRACTION = 0.3
OUTLIER_LOG_RATIO = math.log(2.0)
MIN_FACTOR = 0.25
MAX_FACTOR = 4.0


def estimate_for_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return the labelled estimate a catalogue record supports, if any."""
    mop_system = record.get("mop_system")
    if mop_system == "none":
        return None
    explicit = record.get("estimate")
    if isinstance(explicit, dict):
        basis = explicit["basis"]
        return {
            "estimate_basis": basis,
            "mop_system": mop_system or "unknown",
            "rate_signal": explicit.get("rate_signal", "mop_mode"),
            "usage_ml_per_m2": dict(explicit["usage_ml_per_m2"]),
            "intensity_factor": dict(explicit.get("intensity_factor") or _INTENSITY_FACTOR),
            "wash_volume_ml": explicit.get("wash_volume_ml"),
            "uncertainty_percent": BASIS_UNCERTAINTY_PERCENT[basis],
            "estimate_sources": list(explicit.get("sources") or []),
        }
    system = mop_system if mop_system in CLASS_PRIORS else "unknown"
    prior = CLASS_PRIORS[system]
    basis = "class_prior" if system != "unknown" else "generic_prior"
    return {
        "estimate_basis": basis,
        "mop_system": system,
        "rate_signal": prior["rate_signal"],
        "usage_ml_per_m2": dict(prior["usage_ml_per_m2"]),
        "intensity_factor": dict(prior["intensity_factor"]),
        "wash_volume_ml": prior["wash_volume_ml"],
        "uncertainty_percent": BASIS_UNCERTAINTY_PERCENT[basis],
        "estimate_sources": [],
    }


def validate_estimate(key: str, estimate: Any) -> str | None:
    """Return an error message for an invalid explicit estimate block."""
    if not isinstance(estimate, dict):
        return f"Profile {key!r} estimate must be an object"
    if estimate.get("basis") not in ESTIMATE_BASES:
        return f"Profile {key!r} estimate has invalid basis"
    rates = estimate.get("usage_ml_per_m2")
    if not isinstance(rates, dict) or not rates or not all(_positive(v) for v in rates.values()):
        return f"Profile {key!r} estimate requires positive usage_ml_per_m2"
    factors = estimate.get("intensity_factor", {})
    if not isinstance(factors, dict) or not all(_positive(v) for v in factors.values()):
        return f"Profile {key!r} estimate has invalid intensity_factor"
    wash = estimate.get("wash_volume_ml")
    if wash is not None and not _positive(wash):
        return f"Profile {key!r} estimate has invalid wash_volume_ml"
    if estimate.get("rate_signal", "mop_mode") not in {"mop_mode", "mop_intensity", "cleaning_mode"}:
        return f"Profile {key!r} estimate has invalid rate_signal"
    sources = estimate.get("sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and s for s in sources):
        return f"Profile {key!r} estimate requires sources"
    return None


def seed_log_factors(state: dict[str, Any]) -> list[float]:
    """Return the stored factor window, migrating 5.x mean-based state."""
    stored = state.get("calibration_log_factors")
    if isinstance(stored, list) and all(isinstance(v, (int, float)) and math.isfinite(v) for v in stored):
        return [float(v) for v in stored][-CALIBRATION_WINDOW:]
    samples = int(state.get("calibration_samples") or 0)
    factor = state.get("calibration_factor")
    if samples > 0 and _positive(factor):
        return [math.log(float(factor))] * min(samples, 3)
    return []


def uncertainty_log_factors(state: dict[str, Any]) -> list[float]:
    """Factors that describe spread: the real window, or one migrated 5.x factor."""
    stored = state.get("calibration_log_factors")
    if isinstance(stored, list):
        return [float(v) for v in stored if isinstance(v, (int, float)) and math.isfinite(v)][-CALIBRATION_WINDOW:]
    samples = int(state.get("calibration_samples") or 0)
    factor = state.get("calibration_factor")
    if samples > 0 and _positive(factor):
        return [math.log(float(factor))]
    return []


def update_calibration(
    log_factors: list[float],
    observed_factor: float,
) -> tuple[list[float], float, bool, str | None]:
    """Add one tank's observed total factor; return window, factor, accepted, reason."""
    observed = min(max(observed_factor, MIN_FACTOR), MAX_FACTOR)
    value = math.log(observed)
    if len(log_factors) >= 3 and abs(value - median(log_factors)) > OUTLIER_LOG_RATIO:
        return list(log_factors), math.exp(median(log_factors)), False, "calibration_sample_outlier"
    window = (list(log_factors) + [value])[-CALIBRATION_WINDOW:]
    return window, math.exp(median(window)), True, None


def uncertainty_percent(basis: Any, log_factors: Any) -> int | None:
    """Deterministic uncertainty: basis before calibration, tank spread after."""
    base = BASIS_UNCERTAINTY_PERCENT.get(str(basis)) if basis else None
    factors = [float(v) for v in log_factors] if isinstance(log_factors, list) else []
    if not factors:
        return base
    n = len(factors)
    if n < 3:
        start = base if base is not None else 50
        return max(8, round(start / (n + 1)))
    center = median(factors)
    mad = median(abs(v - center) for v in factors) * 1.4826
    return max(5, min(50, round((math.exp(mad * 1.25) - 1) * 100 + 3)))


def _positive(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)
