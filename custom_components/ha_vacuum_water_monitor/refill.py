"""Refill bookkeeping shared by the card, the HA service and the server tick.

Every way a user can report a refill (card button, service call, a bound
``input_button``, a tank-lid sensor) and the automatic dock-cleared signal end
in :func:`apply_refill`, so they record the same state, source and history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

REFILL_HISTORY_LIMIT = 20
# Two refill reports this close together describe one physical refill (a lid
# closed after the dock already cleared, a button pressed twice or as confirmation).
USER_REFILL_DEDUPE_SECONDS = 600
# "entity": the Refilled button entity of the robot; "repair": confirmed in Settings > Repairs.
FULL_CONFIRMATION_SOURCES = frozenset({"card", "service", "button", "entity", "repair"})
REFILL_SOURCES = frozenset({"card", "service", "button", "lid", "dock_cleared", "legacy", "entity", "repair"})

# Only dock-specific signals can inherit a dock reservoir automatically.
_INFERRED_ANCHOR_SCOPE = {"dock_error": "dock_clean", "dock_clean_water": "dock_clean"}


def anchor_scope_matches(device: dict[str, Any], source: str) -> bool:
    """Use the same reservoir contract for health readiness and accounting."""
    if source == "user_empty":
        return True
    reservoir = device.get("tracked_reservoir")
    return bool(reservoir and device.get("water_anchor_reservoir") == reservoir
                and (not device.get("water_anchor_reservoir_inferred")
                     or _INFERRED_ANCHOR_SCOPE.get(source) == reservoir))


# Fields that restart exposure accounting from the next observation.
_REBASELINE_FIELDS = {
    "last_area": None,
    "last_duration_seconds": None,
    "last_tick_ts": 0,
    "last_water_volume_ml": None,
    "area_gap": False,
    "area_time_fallback": False,
    "duration_gap": False,
    "session_exposure_complete": False,
    "verified_wash_active": False,
    "last_completed_wash_count": None,
    "gap_started_ts": None,
    "gap_exposure_possible": False,
}


def apply_refill(
    state: dict[str, Any],
    now_ts: int,
    source: str,
    *,
    rebaseline: bool,
    full_practice_confirmed: bool = False,
) -> dict[str, Any]:
    """Mark the tracked reservoir full and return the history record.

    A refill reported by the user while the dock still shows its empty-water
    error acknowledges that error: the persisting error must not become a new
    empty anchor, and its later clearing must not reset the tank a second time.
    """
    interruption = state.get("last_accounting_interruption")
    if isinstance(interruption, dict) and not interruption.get("resolved_ts"):
        state["last_accounting_interruption"] = {
            **interruption, "resolved_ts": now_ts, "refill_source": source,
        }
    learning = state.get("nominal_time_learning")
    if isinstance(learning, dict):
        state["nominal_time_learning"] = {**learning, "cycle": None,
            "last_reason": "refill_during_cycle" if learning.get("cycle") else learning.get("last_reason")}
    state.pop("nominal_time_cycle_rate", None)
    state.pop("nominal_time_rate_context", None)
    used_before = state.get("used_ml")
    empty_active = bool(state.get("water_empty_active"))
    # A "Tank empty" the user pressed ends with the refill; only a dock error
    # can still be showing afterwards.
    acknowledged = empty_active and source != "dock_cleared" and state.get("water_anchor_source") != "user_empty"
    # A refill during a run ends the clean measurement but not the session: the
    # water already counted moves into the start offset so the history keeps
    # the whole run.
    session_open = bool(state.get("session_start_ts")) and isinstance(used_before, (int, float))
    if session_open:
        start_used = state.get("session_start_used_ml")
        start_used = float(start_used) if isinstance(start_used, (int, float)) else 0.0
        state["session_start_used_ml"] = round(start_used - float(used_before), 2)
    if rebaseline:
        state.update(_REBASELINE_FIELDS)
    state.update(
        used_ml=0,
        cycle_action_totals={},
        accounting_incomplete=False,
        missing_usage_rate_reason=None,
        session_accounting_valid=False,
        initialized=True,
        last_reset_ts=now_ts,
        last_reset_iso=datetime.fromtimestamp(now_ts / 1000, tz=timezone.utc).isoformat(),
        last_reset_source=source,
        # Alarm clearing and opening the lid prove a change, not a full tank.
        # A user-facing full confirmation qualifies a relative balance cycle.
        cycle_full_confirmed=(source in FULL_CONFIRMATION_SOURCES
            or (full_practice_confirmed is True and source in {"lid", "dock_cleared"})),
        cycle_full_confirmation_source=(source if source in FULL_CONFIRMATION_SOURCES else
            "declared_full_refill_practice" if full_practice_confirmed is True else None),
        water_empty_active=acknowledged,
        water_empty_acknowledged=acknowledged,
        user_empty_active=False,
        water_anchor_candidate_source=None,
        water_anchor_candidate_since_ts=0,
        last_wash_charged_ts=0,
        last_wash_charged_ml=0,
    )
    state["nominal_time_start_pending"] = state["cycle_full_confirmed"]
    record = {
        "ts": now_ts,
        "source": source,
        "used_before_ml": round(float(used_before), 1) if isinstance(used_before, (int, float)) else None,
        "empty_acknowledged": acknowledged,
    }
    state["refill_history"] = [record, *(state.get("refill_history") or [])][:REFILL_HISTORY_LIMIT]
    return record


def confirm_same_refill(state: dict[str, Any], source: str) -> bool:
    """Enrich the same zero-use baseline without inventing a previous full level."""
    if (source not in FULL_CONFIRMATION_SOURCES or state.get("cycle_full_confirmed")
            or state.get("used_ml") != 0 or state.get("accounting_incomplete")
            or state.get("session_start_ts")):
        return False
    state["cycle_full_confirmed"] = True
    state["nominal_time_start_pending"] = True
    state["cycle_full_confirmation_source"] = source
    return True
