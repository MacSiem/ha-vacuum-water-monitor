"""Regression tests for water-accounting state transitions."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
import unittest

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _load_tick():
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    ha.core = core
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.core", core)

    pkg = types.ModuleType("vwmtickpkg")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["vwmtickpkg"] = pkg

    calculations = types.ModuleType("vwmtickpkg.sensor_calculations")
    calculations.apply_custom_calibration = lambda device, settings: dict(device)
    sys.modules["vwmtickpkg.sensor_calculations"] = calculations

    storage = types.ModuleType("vwmtickpkg.storage")

    class _Storage:
        @staticmethod
        def default_tank_state():
            return {}

    storage.VacuumWaterStorage = _Storage
    sys.modules["vwmtickpkg.storage"] = storage

    spec = importlib.util.spec_from_file_location("vwmtickpkg.tick", PKG_DIR / "tick.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vwmtickpkg.tick"] = module
    spec.loader.exec_module(module)
    return module


tick = _load_tick()


class _State:
    def __init__(self, state: str, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _States:
    def __init__(self, values):
        self._values = values

    def get(self, entity_id):
        return self._values.get(entity_id)


class _Hass:
    def __init__(self, values):
        self.states = _States(values)


def _run(previous_status: str, current_status: str, device=None, used_ml=0):
    hass = _Hass(
        {
            "vacuum.test": _State("docked", {"status": current_status}),
            "sensor.status": _State(current_status),
        }
    )
    effective = {
        "vacuum_entity": "vacuum.test",
        "status_sensor": "sensor.status",
        **(device or {}),
    }
    state = {
        "used_ml": used_ml,
        "last_status": previous_status,
        "last_area": None,
        "last_dock_err": None,
        "last_door": None,
        "last_reset_ts": 0,
    }
    return tick.tick_device(hass, effective, state)[0]


class WaterAccountingTransitionTests(unittest.TestCase):
    def test_wash_sequence_is_counted_only_once(self):
        first = _run("docked", "going_to_wash_the_mop")
        second = _run(
            "going_to_wash_the_mop", "washing_the_mop", used_ml=first["used_ml"]
        )

        self.assertEqual(first["used_ml"], 150)
        self.assertEqual(second["used_ml"], 150)

    def test_separate_wash_sequences_are_counted_separately(self):
        first = _run("docked", "washing_the_mop")
        left_wash = _run("washing_the_mop", "cleaning", used_ml=first["used_ml"])
        second = _run("cleaning", "going_to_wash_the_mop", used_ml=left_wash["used_ml"])

        self.assertEqual(first["used_ml"], 150)
        self.assertEqual(left_wash["used_ml"], 150)
        self.assertEqual(second["used_ml"], 300)

    def test_each_supported_wash_state_counts_on_entry(self):
        for wash_state in tick.MOP_WASH_STATES:
            with self.subTest(wash_state=wash_state):
                result = _run("docked", wash_state)
                self.assertEqual(result["used_ml"], 150)

if __name__ == "__main__":
    unittest.main(verbosity=2)
