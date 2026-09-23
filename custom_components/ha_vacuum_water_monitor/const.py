"""Constants for Vacuum Water Monitor."""

from __future__ import annotations

DOMAIN = "ha_vacuum_water_monitor"
VERSION = "5.7.0-beta.6"
MANUFACTURER = "HA Tools"
MODEL = "Vacuum Water Monitor"

EVENT_STATE_CHANGED = f"{DOMAIN}_state_changed"
# Tank fields that are history or diagnostics, not the live balance. They stay
# out of bus events: the recorder stores every event (32 KB cap per event) and
# the card reads them with get_state.
EVENT_HEAVY_TANK_FIELDS = frozenset({
    "automatic_sessions", "refill_history", "calibration_history", "calibration_log_factors",
    "session_context", "session_resolution", "consumption_resolution", "reservoir_levels",
    "accounting_context", "accounting_interval_context", "accounting_calibration_context",
    "accounting_v2", "wash_resolution",
})


def event_tank_states(changed: dict) -> dict:
    """Compact per-vacuum tank states for the state-changed bus event."""
    return {
        vacuum: {key: value for key, value in (state or {}).items() if key not in EVENT_HEAVY_TANK_FIELDS}
        for vacuum, state in (changed or {}).items()
    }
SERVICE_MARK_REFILLED = "mark_refilled"

CONF_WARNING_THRESHOLD = "warning_threshold"
CONF_CRITICAL_THRESHOLD = "critical_threshold"

DEFAULT_WARNING_THRESHOLD = 20
DEFAULT_CRITICAL_THRESHOLD = 10
DEFAULT_TICK_INTERVAL_SECONDS = 60

DATA_FRONTEND_REGISTERED = "_frontend_registered"
DATA_STORAGE = "storage"
DATA_TICK_UNSUB = "tick_unsub"
DATA_TICK_TASK = "tick_task"
DATA_TICKER = "ticker"
DATA_WS_REGISTERED = "_ws_registered"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1


def signal_vacuum_water_updated(entry_id: str) -> str:
    """Return the dispatcher signal for Store-backed sensor refreshes."""
    return f"{DOMAIN}_{entry_id}_updated"
