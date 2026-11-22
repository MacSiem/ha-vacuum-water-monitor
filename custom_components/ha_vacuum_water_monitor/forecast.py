"""How long the water lasts, and how good the last estimates were.

Pure module: uses only the stored run history and calibration history.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

MIN_RUN_WATER_ML = 20  # a vacuum-only run or a single wash is not a cleaning's water use
MIN_RUNS = 3
RUNS_WINDOW = 10
DAYS_WINDOW = 28
MIN_SPAN_DAYS = 7
MS_PER_DAY = 86_400_000


def _stable_observation(value: Any) -> Any:
    """Compare registry identity and settings, not a renameable ACL locator."""
    if isinstance(value, list):
        return [_stable_observation(item) for item in value]
    if isinstance(value, dict):
        is_observation = "source_entity" in value and "source" in value and "value" in value
        return {key: _stable_observation(item) for key, item in value.items()
                if not (is_observation and key == "source_entity")}
    return value


def _same_forecast_context(current: Any, previous: Any) -> bool:
    if not isinstance(current, dict) or not current:
        return True  # Legacy history without a current fingerprint.
    settings = current.get("settings") if isinstance(current.get("settings"), dict) else {}
    observed = current.get("observed_settings") if isinstance(current.get("observed_settings"), dict) else {}
    sources = current.get("field_sources") if isinstance(current.get("field_sources"), dict) else {}
    if any(value == "unavailable" for value in sources.values()):
        return False
    if not isinstance(previous, dict):
        return False
    for key in ("model_id", "sku", "dock_variant", "firmware", "integration_id", "integration_version", "reservoir"):
        if current.get(key) is not None and current.get(key) != previous.get(key):
            return False
    old_settings = previous.get("settings") if isinstance(previous.get("settings"), dict) else {}
    if any(settings.get(key) != old_settings.get(key)
           for key in settings.keys() | old_settings.keys()):
        return False
    old_observed = previous.get("observed_settings") if isinstance(previous.get("observed_settings"), dict) else {}
    if observed.keys() != old_observed.keys():
        return False
    for key, value in observed.items():
        if not isinstance(value, dict) or value.get("value") is None:
            return False
        if _stable_observation(value) != _stable_observation(old_observed.get(key)):
            return False
    return True


def _runs(tank_state: dict[str, Any]) -> list[dict[str, Any]]:
    runs = []
    for record in tank_state.get("automatic_sessions") or []:
        water = record.get("water") if isinstance(record, dict) else None
        if isinstance(water, (int, float)) and not isinstance(water, bool) and math.isfinite(water) \
                and water >= MIN_RUN_WATER_ML and isinstance(record.get("ts"), (int, float)):
            runs.append(record)
    return runs


def supply_forecast(tank_state: dict[str, Any] | None, remaining_ml: Any, now_ts: int) -> dict[str, Any]:
    """Cleanings and days left at the robot's usual use; ``None`` until 3 mopping runs."""
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    all_runs = _runs(tank_state)
    runs = []
    context_changed = False
    current_context = tank_state.get("last_consumption_context")
    # Forecast only from the newest uninterrupted block of compatible runs.
    # Past runs remain untouched and cannot silently describe a new setting.
    for run in all_runs:
        if not _same_forecast_context(current_context, run.get("context")):
            context_changed = True
            break
        if run.get("accounting_valid") is False or run.get("exposure_complete") is False or (run.get("segments") is not None and run.get("segments") != 1):
            continue
        runs.append(run)
    result: dict[str, Any] = {"cleanings_left": None, "days_left": None, "water_per_cleaning_ml": None,
                              "water_per_day_ml": None, "basis_runs": len(runs), "context_changed": context_changed}
    if len(runs) < MIN_RUNS:
        return result
    per_run = median(float(run["water"]) for run in runs[:RUNS_WINDOW])
    result["water_per_cleaning_ml"] = round(per_run, 1)
    recent = [run for run in runs if now_ts - run["ts"] <= DAYS_WINDOW * MS_PER_DAY]
    if len(recent) >= MIN_RUNS:
        oldest = min(run.get("started_ts") or run["ts"] for run in recent)
        span_days = (now_ts - oldest) / MS_PER_DAY
        # Daily use needs a week of history; a first busy week would mislead.
        if span_days >= MIN_SPAN_DAYS:
            result["water_per_day_ml"] = round(sum(float(run["water"]) for run in recent) / span_days, 1)
    if not isinstance(remaining_ml, (int, float)) or isinstance(remaining_ml, bool) or remaining_ml < 0:
        return result
    result["cleanings_left"] = int(remaining_ml // per_run) if per_run > 0 else None
    if result["water_per_day_ml"]:
        result["days_left"] = round(remaining_ml / result["water_per_day_ml"], 1)
    return result


def estimate_track_record(tank_state: dict[str, Any] | None, limit: int = 5) -> dict[str, Any]:
    """The last empty tanks: how far the estimate was before it learned from each."""
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    tanks = [record for record in tank_state.get("calibration_history") or [] if isinstance(record, dict)]
    errors = [float(record["error_percent"]) for record in tanks
              if isinstance(record.get("error_percent"), (int, float)) and record.get("accepted")]
    last = tanks[0] if tanks else None
    return {
        "last_tank": {key: last.get(key) for key in ("ts", "error_percent", "accepted", "reason",
                                                     "predicted_ml", "target_ml")} if last else None,
        "recent_errors_percent": [record.get("error_percent") for record in tanks[:limit]],
        "typical_error_percent": round(median(abs(value) for value in errors[:limit]), 1) if errors else None,
    }
