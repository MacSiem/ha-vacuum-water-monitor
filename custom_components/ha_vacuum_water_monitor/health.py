"""One health report per robot, shared by the card and Home Assistant Repairs.

The report answers the user's questions in order: which robot is this, how big
is its tank and where that number comes from, how accurate the estimate is, how
a refill is recognised, and what (if anything) needs the user. It is computed on
the server from the same inputs the engine uses, so the card, the Repairs
dashboard and the diagnostics download never disagree.

Pure module: no Home Assistant imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import time
from typing import Any

try:
    from .forecast import estimate_track_record, supply_forecast
except ImportError:  # direct-file loading in the pure tests
    _spec = importlib.util.spec_from_file_location("vwm_standalone_forecast", Path(__file__).with_name("forecast.py"))
    assert _spec and _spec.loader
    _forecast = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_forecast)
    estimate_track_record, supply_forecast = _forecast.estimate_track_record, _forecast.supply_forecast

# Checks the user can fix in one step (card button or Repairs flow).
FIX_CONFIRM_FULL = "confirm_full"
FIX_SET_CAPACITY = "set_capacity"
FIX_RESOLVE_DUPLICATE = "resolve_duplicate"
FIX_MAP_SIGNAL = "map_signal"  # card only: needs an entity picker

# Checks raised as Home Assistant Repairs issues (the rest are card-only hints).
REPAIR_CHECKS = frozenset({"awaiting_refill", "accounting_paused", "unknown_capacity",
                           "possible_duplicate", "mop_signal_unbound"})

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

_EMPTY_ANCHOR_KEYS = ("dock_error_sensor", "dock_clean_water_sensor", "water_error_sensor",
                      "water_shortage_sensor", "water_volume_sensor")
# Entities that exist only on mopping robots. Attribute names an adapter maps
# (for example Roomba's water-box attributes) are evidence only when the robot's
# state actually carries them; the caller checks that (``mop_attribute_present``).
_MOP_KEYS = ("mop_attached_sensor", "mop_mode_entity", "cleaning_mode_entity", "water_box_attached_sensor",
             "water_box_detached_sensor", "mop_intensity_entity", "mop_drying_sensor", "dock_clean_water_sensor")
MOP_ATTRIBUTE_KEYS = ("water_box_attached_attribute", "mop_intensity_attribute")


def refill_method(effective: dict[str, Any]) -> str:
    """How a refill is recognised: ``measured``, ``dock_auto``, ``button``, ``lid`` or ``manual``."""
    if effective.get("water_volume_sensor"):
        return "measured"
    if effective.get("refill_on_dock_clear") is not False and effective.get("refill_on_clear") and any(
            effective.get(key) for key in ("dock_error_sensor", "dock_clean_water_sensor", "water_error_sensor")):
        return "dock_auto"
    if effective.get("refill_button_entity"):
        return "button"
    if effective.get("reset_door_sensor"):
        return "lid"
    return "manual"


def has_empty_signal(effective: dict[str, Any]) -> bool:
    """The robot or dock reports an empty tank itself (no Tank empty button needed)."""
    return any(effective.get(key) for key in _EMPTY_ANCHOR_KEYS)


def supports_auto_refill(effective: dict[str, Any]) -> bool:
    """The dock can report that its clean tank was refilled."""
    return bool(effective.get("refill_on_clear")) and any(
        effective.get(key) for key in ("dock_error_sensor", "dock_clean_water_sensor", "water_error_sensor"))


def tracks_water(device: dict[str, Any], effective: dict[str, Any], estimate: dict[str, Any],
                 mop_attribute_present: bool = False) -> bool:
    """The robot mops (or the user said it has a tank), so water tracking applies."""
    if mop_attribute_present or device.get("capacity_option_ml"):
        return True
    if estimate.get("total_ml") or estimate.get("estimate_basis") or effective.get("tracked_reservoir"):
        return True
    if estimate.get("capability") not in (None, "", "unknown"):
        return True
    return any(effective.get(key) or device.get(key) for key in _MOP_KEYS + _EMPTY_ANCHOR_KEYS)


def robot_health(
    device: dict[str, Any],
    effective: dict[str, Any],
    tank_state: dict[str, Any],
    estimate: dict[str, Any],
    *,
    capacity_source: str | None = None,
    model_capacity_ml: float | None = None,
    duplicate_of: str | None = None,
    duplicate_of_name: str | None = None,
    mop_attribute_present: bool = False,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Build one robot's report; ``checks`` is ordered most important first."""
    device = device if isinstance(device, dict) else {}
    effective = effective if isinstance(effective, dict) else {}
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    estimate = estimate if isinstance(estimate, dict) else {}
    tracked = tracks_water(device, effective, estimate, mop_attribute_present)
    method = refill_method(effective)
    samples = int(estimate.get("calibration_samples") or 0)
    can_calibrate = has_empty_signal(effective)
    checks: list[dict[str, Any]] = []

    def add(check_id: str, severity: str, fix: str | None = None, **params: Any) -> None:
        checks.append({"id": check_id, "severity": severity, "fix": fix,
                       "repair": check_id in REPAIR_CHECKS, "params": params})

    if duplicate_of:
        add("possible_duplicate", "warning", FIX_RESOLVE_DUPLICATE, target=duplicate_of,
            target_name=duplicate_of_name or duplicate_of)
    reason = estimate.get("state_reason")
    if duplicate_of:
        # Until the user decides, a suspected copy raises only that question.
        pass
    elif tracked:
        if estimate.get("total_ml") is None and estimate.get("source") != "physical_event_stream":
            add("unknown_capacity", "error", FIX_SET_CAPACITY)
        if reason == "mop_signal_unbound":
            add("mop_signal_unbound", "warning", FIX_MAP_SIGNAL)
        if not estimate.get("initialized") and estimate.get("source") == "uninitialized":
            add("awaiting_refill", "warning", FIX_CONFIRM_FULL, auto_refill=method == "dock_auto")
        elif reason == "accounting_incomplete":
            add("accounting_paused", "warning", FIX_CONFIRM_FULL, auto_refill=method == "dock_auto")
        elif reason in {"vacuum_unavailable", "status_unavailable", "area_unavailable", "duration_unavailable",
                        "real_sensor_unavailable"}:
            add("signal_unavailable", "info", None, reason=reason)
        if method == "manual":
            add("manual_refill", "info", None)
        if not can_calibrate:
            add("no_empty_signal", "info", None)
    else:
        add("not_tracked", "info", FIX_SET_CAPACITY)

    checks.sort(key=lambda check: _SEVERITY_ORDER.get(check["severity"], 3))
    blocking = [check for check in checks if check["severity"] in {"error", "warning"}]
    return {
        "vacuum_entity": device.get("vacuum_entity"),
        "name": device.get("name") or device.get("vacuum_entity"),
        "manufacturer": device.get("manufacturer"),
        "model": device.get("model") or device.get("model_id"),
        "profile_key": estimate.get("profile_key"),
        "integration": effective.get("integration_adapter") or device.get("integration_adapter"),
        "tracks_water": tracked,
        "capacity_ml": estimate.get("total_ml"),
        "capacity_source": capacity_source,
        "model_capacity_ml": model_capacity_ml,
        "estimate_basis": estimate.get("estimate_basis"),
        "uncertainty_percent": estimate.get("uncertainty_percent"),
        "calibration_samples": samples,
        "calibration_factor": estimate.get("calibration_factor"),
        "can_calibrate": can_calibrate,
        "refill_method": method,
        "auto_refill_supported": supports_auto_refill(effective),
        "auto_refill": method == "dock_auto",
        "initialized": bool(estimate.get("initialized")),
        "tank_empty": bool(tank_state.get("water_empty_active")),
        "remaining_percent": estimate.get("remaining_percent"),
        "supply": supply_forecast(tank_state, estimate.get("remaining_ml"),
                                  now_ts if now_ts is not None else int(time.time() * 1000)),
        **estimate_track_record(tank_state),
        "status": "action_needed" if blocking else "ok",
        "checks": checks,
    }
