"""Private estimates from nominal full-to-empty reservoirs and mopping time.

This is reservoir depletion per active floor-mopping minute, not a measured
floor-water flow. Nominal capacity and the residual assumption remain explicit;
repeatability cannot establish physical accuracy. Dock washing and vacuum-only
activity must be passed as ``active=False``. Any dock water used is implicitly
part of the reservoir depletion, so wash settings belong in the context.

Every operation returns a new JSON-serializable dictionary. Store this dictionary
under a dedicated device-state key. Times are milliseconds, as in tick.py.
``active`` describes the interval *after* the observation: a transition to idle
charges the preceding active interval; a transition from idle starts a baseline.
Call on transitions as well as ticks, including the empty event. Missing usage
coefficients do not make observation unavailable. Unknown activity does.

The caller supplies the complete stable context: device_id, reservoir, settings
and relevant firmware/integration/model identity. Comparison is exact, including
extra fields; missing/None values never act as wildcards. Observed settings must
not be replaced by a different value just because the robot goes idle. Remove
volatile reporting metadata before calling; do not remove consumption settings.

Promotion requires three consecutive compatible tanks, max(rate)/min(rate)
<=1.25. This organizational repeatability gate reduces promotion on a single
odd refill; it is a policy, not an empirically established accuracy bound.
After activation, a sample must agree with the latest accepted pair before it
can update their median. Outliers do not evict accepted samples.
History is bounded to eight accepted/candidate tanks per context and 32 most
recently completed contexts. Switching contexts does not erase previous samples;
only the documented global retention limit may evict an old context.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from statistics import median
from typing import Any

MAX_ACTIVE_INTERVAL_MS = 180_000
SAMPLE_LIMIT = 8
CONTEXT_LIMIT = 32
AGREEMENT_RATIO = 1.25
DEFAULT_RESIDUAL_PERCENT = 5.0


def _number(value: Any, *, zero: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and (value >= 0 if zero else value > 0)
    except (ValueError, OverflowError):
        return False


def _context_key(context: Any) -> str | None:
    if not isinstance(context, dict):
        return None
    if not all(isinstance(context.get(key), str) and context[key].strip()
               for key in ("device_id", "reservoir")):
        return None
    if not isinstance(context.get("settings"), dict) or not context["settings"]:
        return None

    def json_values(value: Any) -> bool:
        if isinstance(value, dict):
            return all(isinstance(key, str) and key and json_values(item)
                       for key, item in value.items())
        if isinstance(value, list):
            return all(json_values(item) for item in value)
        if value is None or isinstance(value, (str, bool)):
            return True
        return isinstance(value, (int, float)) and _number(abs(value), zero=True)

    try:
        if not json_values(context):
            return None
        return json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None


def _residual(value: Any) -> bool:
    return _number(value, zero=True) and value < 100


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("version", 1) != 1:
        return {"version": 1, "cycle": None, "contexts": [], "last_reason": "invalid_state"}
    return {"version": 1, "cycle": deepcopy(state.get("cycle")),
            "contexts": deepcopy(state.get("contexts")) if isinstance(state.get("contexts"), list) else [],
            "last_reason": state.get("last_reason")}


def invalidate(state: dict[str, Any], reason: str) -> dict[str, Any]:
    """Discard only the open tank; retain every context's completed samples."""
    updated = _snapshot(state)
    updated.update(cycle=None, last_reason=reason if isinstance(reason, str) and reason else "invalidated")
    return updated


def start_full(
    state: dict[str, Any], *, context: dict[str, Any], capacity_ml: float,
    now_ts: int, residual_percent: float = DEFAULT_RESIDUAL_PERCENT,
) -> dict[str, Any]:
    """Start only after confirmed full refill, never on mere alarm clearing.

    A full refill in an open tank discards its partial sample and starts a new
    full anchor. Debouncing duplicate reports belongs to refill.py/the caller.
    """
    updated = _snapshot(state)
    if (_context_key(context) is None or not _number(capacity_ml)
            or not _number(now_ts) or not _residual(residual_percent)):
        return invalidate(updated, "invalid_full_anchor")
    updated["last_reason"] = "refill_during_cycle" if updated["cycle"] is not None else None
    updated["cycle"] = {
        "context": deepcopy(context), "capacity_ml": float(capacity_ml),
        "residual_percent": float(residual_percent), "started_ts": now_ts,
        "last_ts": now_ts, "last_active": False, "active_minutes": 0.0,
    }
    return updated


def observe(
    state: dict[str, Any], *, context: dict[str, Any], capacity_ml: float,
    now_ts: int, active: bool, available: bool = True,
    use_counter: bool = False, counter_minutes: float | None = None,
) -> dict[str, Any]:
    """Accumulate observable floor activity independently of ml/min availability.

    Invalidate unavailable/unknown observations, context or capacity changes,
    backward clocks, and gaps over 180 seconds after an active observation.
    Observed idle can last arbitrarily long without ending the full tank.
    ``use_counter`` replaces wall time with a session minute counter. Missing,
    decreasing active counters and implausible jumps invalidate the sample;
    idle resets establish a new baseline. Only intervals mopping at both ends
    add counter exposure. The caller includes the observation method in context.
    """
    updated = _snapshot(state)
    cycle = updated["cycle"]
    if cycle is None:
        return updated
    if available is not True or not isinstance(active, bool):
        return invalidate(updated, "time_observation_unavailable")
    if (not isinstance(cycle, dict) or not _number(cycle.get("last_ts"))
            or not _number(cycle.get("started_ts"))
            or not _number(cycle.get("active_minutes"), zero=True)
            or not isinstance(cycle.get("last_active"), bool)
            or not _number(cycle.get("capacity_ml"))
            or not _residual(cycle.get("residual_percent"))):
        return invalidate(updated, "invalid_cycle_state")
    if (not _number(now_ts) or now_ts < cycle["last_ts"]
            or not _number(now_ts - cycle["last_ts"], zero=True)):
        return invalidate(updated, "invalid_observation_time")
    key = _context_key(context)
    if key is None or key != _context_key(cycle.get("context")):
        return invalidate(updated, "time_context_changed")
    if not _number(capacity_ml) or capacity_ml != cycle["capacity_ml"]:
        return invalidate(updated, "time_capacity_changed")
    elapsed_ms = now_ts - cycle["last_ts"]
    if cycle["last_active"]:
        if elapsed_ms > MAX_ACTIVE_INTERVAL_MS:
            return invalidate(updated, "active_observation_gap")
        if not use_counter:
            cycle["active_minutes"] += elapsed_ms / 60_000
    if use_counter:
        if not _number(counter_minutes, zero=True):
            return invalidate(updated, "time_counter_unavailable")
        previous = cycle.get("counter_minutes")
        if previous is not None and cycle["last_active"]:
            delta = counter_minutes - previous
            if delta < 0 or delta > elapsed_ms / 60_000 + 1:
                return invalidate(updated, "time_counter_discontinuity")
            if active:
                cycle["active_minutes"] += delta
        cycle["counter_minutes"] = counter_minutes
    cycle.update(last_ts=now_ts, last_active=active)
    return updated


def _entry_matches(entry: Any, context: Any, capacity_ml: Any, residual: Any) -> bool:
    key = _context_key(context)
    return (isinstance(entry, dict) and key is not None
            and _context_key(entry.get("context")) == key
            and _number(capacity_ml) and _number(entry.get("capacity_ml"))
            and entry["capacity_ml"] == capacity_ml
            and _residual(residual) and _residual(entry.get("residual_percent"))
            and entry["residual_percent"] == residual)


def _samples(entry: dict[str, Any]) -> list[dict[str, Any]]:
    samples = entry.get("samples")
    if not isinstance(samples, list):
        return []
    valid = []
    for sample in samples[-SAMPLE_LIMIT:]:
        if not isinstance(sample, dict) or not all(_number(sample.get(key)) for key in (
                "rate_ml_per_minute", "active_minutes", "finished_ts")):
            continue
        nominal_rate = entry["capacity_ml"] * (1 - entry["residual_percent"] / 100) / sample["active_minutes"]
        if _number(nominal_rate) and math.isclose(nominal_rate, sample["rate_ml_per_minute"], rel_tol=1e-9):
            valid.append(sample)
    return valid


def _agree(samples: list[dict[str, Any]]) -> bool:
    if len(samples) < 3:
        return False
    rates = [sample["rate_ml_per_minute"] for sample in samples[-3:]]
    return max(rates) / min(rates) <= AGREEMENT_RATIO


def finish_empty(
    state: dict[str, Any], *, context: dict[str, Any], capacity_ml: float,
    now_ts: int, available: bool = True,
) -> dict[str, Any]:
    """Finish on a valid empty anchor for the same tracked reservoir, once."""
    cycle_before = state.get("cycle") or {}
    updated = observe(state, context=context, capacity_ml=capacity_ml,
                      now_ts=now_ts, active=False, available=available,
                      use_counter="counter_minutes" in cycle_before,
                      counter_minutes=cycle_before.get("counter_minutes"))
    cycle = updated["cycle"]
    if cycle is None:
        return updated
    minutes = cycle["active_minutes"]
    if not _number(minutes):
        return invalidate(updated, "no_active_mopping_time")
    rate = cycle["capacity_ml"] * (1 - cycle["residual_percent"] / 100) / minutes
    if not _number(rate):
        return invalidate(updated, "invalid_time_sample")
    entries = updated["contexts"]
    entry = next((item for item in entries if _entry_matches(
        item, context, capacity_ml, cycle["residual_percent"])), None)
    if entry is None:
        entry = {"context": deepcopy(context), "capacity_ml": float(capacity_ml),
                 "residual_percent": cycle["residual_percent"], "samples": []}
    else:
        entries.remove(entry)
    samples = _samples(entry)
    sample = {"active_minutes": minutes, "rate_ml_per_minute": rate, "finished_ts": now_ts}
    candidate = [*samples, sample][-SAMPLE_LIMIT:]
    if _agree(samples) and not _agree(candidate):
        # Keep the established triple, even after many rejected empty anchors.
        updated["last_reason"] = "time_sample_outlier"
    else:
        samples = candidate
        updated["last_reason"] = None
    entry["samples"] = samples
    entries.append(entry)
    updated["contexts"] = entries[-CONTEXT_LIMIT:]
    updated["cycle"] = None
    return updated


def resolve(
    state: dict[str, Any], *, context: dict[str, Any], capacity_ml: float,
    residual_percent: float = DEFAULT_RESIDUAL_PERCENT,
) -> dict[str, Any]:
    """Expose a coefficient only after three compatible full nominal tanks.

    Caller keeps verified physical/user coefficients ahead of this private
    nominal estimate. This module never writes shared consumption records.
    """
    updated = _snapshot(state)
    entry = next((item for item in reversed(updated["contexts"]) if _entry_matches(
        item, context, capacity_ml, residual_percent)), None)
    samples = _samples(entry) if entry is not None else []
    active = _agree(samples)
    return {
        "status": "active" if active else "provisional" if samples else "unavailable",
        "usage_ml_per_active_minute": median(
            sample["rate_ml_per_minute"] for sample in samples[-3:]) if active else None,
        "sample_count": len(samples), "basis": "nominal_full_to_empty_time",
        "scope": "private_device", "accuracy": "not_established",
        "nominal_capacity_ml": float(capacity_ml) if _number(capacity_ml) else None,
        "residual_assumed_percent": float(residual_percent) if _residual(residual_percent) else None,
    }
