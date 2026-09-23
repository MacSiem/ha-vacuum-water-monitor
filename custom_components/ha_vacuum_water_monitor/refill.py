"""Refill bookkeeping shared by the card, the HA service and the server tick.

Every way a user can report a refill (card button, service call, a bound
``input_button``, a tank-lid sensor) and the automatic dock-cleared signal end
in :func:`apply_refill`, so they record the same state, source and history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

REFILL_HISTORY_LIMIT = 20
REFILL_SOURCES = frozenset({"card", "service", "button", "lid", "dock_cleared", "legacy"})

# Fields that restart exposure accounting from the next observation.
_REBASELINE_FIELDS = {
    "last_area": None,
    "last_duration_seconds": None,
    "last_tick_ts": 0,
    "last_water_volume_ml": None,
    "area_gap": False,
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
) -> dict[str, Any]:
    """Mark the tracked reservoir full and return the history record.

    A refill reported by the user while the dock still shows its empty-water
    error acknowledges that error: the persisting error must not become a new
    empty anchor, and its later clearing must not reset the tank a second time.
    """
    used_before = state.get("used_ml")
    empty_active = bool(state.get("water_empty_active"))
    acknowledged = empty_active and source != "dock_cleared"
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
        accounting_incomplete=False,
        session_accounting_valid=False,
        initialized=True,
        last_reset_ts=now_ts,
        last_reset_iso=datetime.fromtimestamp(now_ts / 1000, tz=timezone.utc).isoformat(),
        last_reset_source=source,
        water_empty_active=acknowledged,
        water_empty_acknowledged=acknowledged,
        water_anchor_candidate_source=None,
        water_anchor_candidate_since_ts=0,
        last_wash_charged_ts=0,
        last_wash_charged_ml=0,
    )
    record = {
        "ts": now_ts,
        "source": source,
        "used_before_ml": round(float(used_before), 1) if isinstance(used_before, (int, float)) else None,
        "empty_acknowledged": acknowledged,
    }
    state["refill_history"] = [record, *(state.get("refill_history") or [])][:REFILL_HISTORY_LIMIT]
    return record
