"""Event-driven accounting with a heartbeat.

A vacuum is ticked shortly after any entity it is bound to changes, so short
states (a mop wash, a flickering dock error, the last area before returning)
are observed as they happen instead of once a minute. The heartbeat keeps
running as a fallback and refreshes the bindings. Ticks never overlap.

This module has no Home Assistant imports; the entry point injects the timer,
task and tick functions so the behaviour is unit-testable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

EVENT_DEBOUNCE_SECONDS = 2.0
# Event-driven ticks coalesce disk writes; Home Assistant flushes delayed
# writes on shutdown, and the in-memory Store is always current.
EVENT_SAVE_DELAY_SECONDS = 30.0

# Maintenance and history entities never change water accounting.
_IGNORED_FIELDS = frozenset({
    "main_brush_sensor", "side_brush_sensor", "filter_sensor", "filter_time_sensor",
    "sensor_dirty_sensor", "dock_brush_sensor", "dock_strainer_sensor", "charge_sensor",
    "last_session_sensor", "mop_drying_sensor", "last_reset_entity", "water_used_sensor",
    "accounting_event_sensor",
})


def bound_entities(device: dict[str, Any]) -> set[str]:
    """Entities whose changes can alter a vacuum's water accounting."""
    entities: set[str] = set()
    for key, value in device.items():
        if key in _IGNORED_FIELDS:
            continue
        if key == "vacuum_entity" or key.endswith("_sensor") or key.endswith("_entity"):
            if isinstance(value, str) and "." in value:
                entities.add(value)
    signals = device.get("signals")
    if isinstance(signals, dict):
        entities.update(v for v in signals.values() if isinstance(v, str) and "." in v)
    for value in (device.get("reservoir_volume_sensors") or {}).values() if isinstance(
            device.get("reservoir_volume_sensors"), dict) else ():
        if isinstance(value, str) and "." in value:
            entities.add(value)
    return entities


def is_meaningful_change(entity_id: str, old_state: Any, new_state: Any) -> bool:
    """A state string change, or a vacuum's activity status attribute change."""
    if new_state is None:
        return False
    if old_state is None:
        return True
    if getattr(old_state, "state", None) != getattr(new_state, "state", None):
        return True
    if entity_id.startswith("vacuum."):
        old_attributes = getattr(old_state, "attributes", {}) or {}
        new_attributes = getattr(new_state, "attributes", {}) or {}
        return old_attributes.get("status") != new_attributes.get("status")
    return False


class EventTicker:
    """Coalesce entity changes into per-vacuum ticks that never overlap."""

    def __init__(
        self,
        run_tick: Callable[[set[str] | None], Awaitable[Any]],
        schedule: Callable[[float, Callable[[Any], None]], Callable[[], None]],
        create_task: Callable[[Awaitable[Any]], Any],
        debounce_seconds: float = EVENT_DEBOUNCE_SECONDS,
    ) -> None:
        self._run_tick = run_tick
        self._schedule = schedule
        self._create_task = create_task
        self._debounce = debounce_seconds
        self._lock = asyncio.Lock()
        self._pending: set[str] = set()
        self._cancel: Callable[[], None] | None = None
        self._entity_map: dict[str, set[str]] = {}

    @property
    def entities(self) -> set[str]:
        return set(self._entity_map)

    def update_bindings(self, devices: Iterable[dict[str, Any]]) -> bool:
        """Rebuild entity -> vacuum bindings; return True when the entity set changed."""
        mapping: dict[str, set[str]] = {}
        for device in devices:
            vacuum = device.get("vacuum_entity")
            if not isinstance(vacuum, str) or not vacuum:
                continue
            for entity in bound_entities(device):
                mapping.setdefault(entity, set()).add(vacuum)
        changed = set(mapping) != set(self._entity_map)
        self._entity_map = mapping
        return changed

    def handle_change(self, entity_id: str, old_state: Any, new_state: Any) -> bool:
        """Queue a tick for the vacuums bound to this entity; return True if queued."""
        vacuums = self._entity_map.get(entity_id)
        if not vacuums or not is_meaningful_change(entity_id, old_state, new_state):
            return False
        self._pending.update(vacuums)
        if self._cancel is None:
            self._cancel = self._schedule(self._debounce, self._flush)
        return True

    async def run(self, vacuums: set[str] | None = None) -> Any:
        async with self._lock:
            return await self._run_tick(vacuums)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None
        self._pending.clear()

    def _flush(self, _now: Any = None) -> None:
        self._cancel = None
        vacuums, self._pending = self._pending, set()
        if vacuums:
            self._create_task(self.run(vacuums))
