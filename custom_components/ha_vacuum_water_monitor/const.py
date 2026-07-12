"""Constants for Vacuum Water Monitor."""

from __future__ import annotations

DOMAIN = "ha_vacuum_water_monitor"
VERSION = "5.1.7"
MANUFACTURER = "HA Tools"
MODEL = "Vacuum Water Monitor"

EVENT_STATE_CHANGED = f"{DOMAIN}_state_changed"

CONF_WARNING_THRESHOLD = "warning_threshold"
CONF_CRITICAL_THRESHOLD = "critical_threshold"

DEFAULT_WARNING_THRESHOLD = 20
DEFAULT_CRITICAL_THRESHOLD = 10
DEFAULT_TICK_INTERVAL_SECONDS = 60

DATA_FRONTEND_REGISTERED = "_frontend_registered"
DATA_STORAGE = "storage"
DATA_TICK_UNSUB = "tick_unsub"
DATA_TICK_TASK = "tick_task"
DATA_WS_REGISTERED = "_ws_registered"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1


def signal_vacuum_water_updated(entry_id: str) -> str:
    """Return the dispatcher signal for Store-backed sensor refreshes."""
    return f"{DOMAIN}_{entry_id}_updated"
