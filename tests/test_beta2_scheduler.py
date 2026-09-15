"""5.7.0-beta.2: event-driven ticks with a heartbeat (pure scheduler logic)."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"
_pkg = types.ModuleType("vwmschedpkg")
_pkg.__path__ = [str(PKG)]
sys.modules["vwmschedpkg"] = _pkg
scheduler = importlib.import_module("vwmschedpkg.scheduler")


class _S:
    def __init__(self, state, attributes=None):
        self.state, self.attributes = state, attributes or {}


DEVICE = {
    "vacuum_entity": "vacuum.robot",
    "status_sensor": "sensor.robot_status",
    "area_sensor": "sensor.robot_area",
    "dock_error_sensor": "sensor.robot_dock_error",
    "mop_intensity_entity": "select.robot_mop_intensity",
    "refill_button_entity": "input_button.refilled",
    "reset_door_sensor": "binary_sensor.lid",
    "main_brush_sensor": "sensor.robot_main_brush_left",
    "signals": {"cleaning_active_sensor": "binary_sensor.robot_cleaning"},
    "usage_ml_per_m2": {"default": 6},
}


class BindingTests(unittest.TestCase):
    def test_accounting_entities_are_bound_and_maintenance_is_not(self):
        entities = scheduler.bound_entities(DEVICE)
        for entity in ("vacuum.robot", "sensor.robot_status", "sensor.robot_area", "sensor.robot_dock_error",
                       "select.robot_mop_intensity", "input_button.refilled", "binary_sensor.lid",
                       "binary_sensor.robot_cleaning"):
            self.assertIn(entity, entities)
        self.assertNotIn("sensor.robot_main_brush_left", entities)

    def test_meaningful_changes(self):
        self.assertTrue(scheduler.is_meaningful_change("sensor.robot_area", _S("1.0"), _S("1.2")))
        self.assertFalse(scheduler.is_meaningful_change("sensor.robot_area", _S("1.2", {"a": 1}), _S("1.2", {"a": 2})))
        self.assertTrue(scheduler.is_meaningful_change("vacuum.robot", _S("cleaning", {"status": "cleaning"}),
                                                       _S("cleaning", {"status": "going_to_wash_the_mop"})))
        self.assertFalse(scheduler.is_meaningful_change("vacuum.robot", _S("cleaning", {"battery_level": 80}),
                                                        _S("cleaning", {"battery_level": 79})))
        self.assertFalse(scheduler.is_meaningful_change("sensor.robot_area", _S("1"), None))


class TickerTests(unittest.TestCase):
    def test_changes_are_coalesced_into_one_tick_for_the_bound_vacuum(self):
        async def scenario():
            calls, timers = [], []
            ticker = scheduler.EventTicker(
                run_tick=lambda vacuums: _record(calls, vacuums),
                schedule=lambda delay, action: (timers.append((delay, action)), lambda: None)[1],
                create_task=asyncio.ensure_future,
            )
            self.assertTrue(ticker.update_bindings([DEVICE, {"vacuum_entity": "vacuum.other", "area_sensor": "sensor.other_area"}]))
            self.assertFalse(ticker.update_bindings([DEVICE, {"vacuum_entity": "vacuum.other", "area_sensor": "sensor.other_area"}]))
            self.assertTrue(ticker.handle_change("sensor.robot_area", _S("1"), _S("2")))
            self.assertTrue(ticker.handle_change("sensor.robot_status", _S("cleaning"), _S("going_to_wash_the_mop")))
            self.assertFalse(ticker.handle_change("sensor.unrelated", _S("1"), _S("2")))
            self.assertEqual(len(timers), 1, "one debounce timer for a burst of changes")
            self.assertEqual(timers[0][0], scheduler.EVENT_DEBOUNCE_SECONDS)
            timers[0][1](None)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return calls

        async def _record(calls, vacuums):
            calls.append(vacuums)

        self.assertEqual(asyncio.run(scenario()), [{"vacuum.robot"}])

    def test_ticks_never_overlap(self):
        async def scenario():
            order = []

            async def slow(vacuums):
                order.append(("start", vacuums))
                await asyncio.sleep(0.01)
                order.append(("end", vacuums))

            ticker = scheduler.EventTicker(slow, lambda d, a: (lambda: None), asyncio.ensure_future)
            await asyncio.gather(ticker.run(None), ticker.run({"vacuum.robot"}))
            return order

        order = asyncio.run(scenario())
        self.assertEqual([step for step, _ in order], ["start", "end", "start", "end"])

    def test_cancel_drops_pending_work(self):
        cancelled = []
        ticker = scheduler.EventTicker(lambda v: None, lambda d, a: (lambda: cancelled.append(True)), lambda c: None)
        ticker.update_bindings([DEVICE])
        ticker.handle_change("sensor.robot_area", _S("1"), _S("2"))
        ticker.cancel()
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
