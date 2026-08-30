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


def _run(previous_status: str | None, current_status: str, device=None, used_ml=0):
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
        first = _run("docked", "going_to_wash_the_mop", {"wash_volume_ml": 150})
        second = _run(
            "going_to_wash_the_mop",
            "washing_the_mop",
            {"wash_volume_ml": 150},
            used_ml=first["used_ml"],
        )

        self.assertEqual(first["used_ml"], 150)
        self.assertEqual(second["used_ml"], 150)

    def test_separate_wash_sequences_are_counted_separately(self):
        rate = {"wash_volume_ml": 150}
        first = _run("docked", "washing_the_mop", rate)
        left_wash = _run("washing_the_mop", "cleaning", rate, used_ml=first["used_ml"])
        second = _run("cleaning", "going_to_wash_the_mop", rate, used_ml=left_wash["used_ml"])

        self.assertEqual(first["used_ml"], 150)
        self.assertEqual(left_wash["used_ml"], 150)
        self.assertEqual(second["used_ml"], 300)

    def test_each_supported_wash_state_counts_on_entry(self):
        for wash_state in tick.MOP_WASH_STATES:
            with self.subTest(wash_state=wash_state):
                result = _run("docked", wash_state, {"wash_volume_ml": 150})
                self.assertEqual(result["used_ml"], 150)

    def test_missing_wash_rate_never_consumes_water(self):
        result = _run("docked", "washing_the_mop", used_ml=10)

        self.assertEqual(result["used_ml"], 10)
        self.assertEqual(result["last_accounting_reason"], "missing_wash_rate")

    def test_explicit_wash_rate_is_accounted_once_and_restart_while_washing_is_deduplicated(self):
        rate = {"wash_volume_ml": 123, "accounting_evidence": "user_calibration"}
        first = _run("docked", "washing_the_mop", rate, used_ml=10)
        restarted = _run("washing_the_mop", "washing_the_mop_2", rate, used_ml=first["used_ml"])

        self.assertEqual(first["used_ml"], 133)
        self.assertEqual(first["last_accounting_rate_ml"], 123)
        self.assertEqual(restarted["used_ml"], 133)
        self.assertEqual(restarted["last_accounting_reason"], "wash_already_active")

    def test_area_without_explicit_rate_never_consumes_water(self):
        hass = _Hass(
            {
                "vacuum.test": _State("cleaning"),
                "sensor.area": _State("12"),
            }
        )
        state = {"used_ml": 10, "last_area": 10, "last_status": "cleaning"}

        result, _dirty = tick.tick_device(
            hass,
            {"vacuum_entity": "vacuum.test", "area_sensor": "sensor.area"},
            state,
        )

        self.assertEqual(result["used_ml"], 10)
        self.assertEqual(result["last_accounting_reason"], "missing_area_rate")

    def test_area_valid_delta_uses_explicit_mode_rate(self):
        hass = _Hass(
            {
                "vacuum.test": _State("cleaning"),
                "sensor.area": _State("12.5"),
                "select.mode": _State("moderate"),
            }
        )
        state = {"used_ml": 10, "last_area": 10, "last_status": "cleaning"}

        result, _dirty = tick.tick_device(
            hass,
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "mop_mode_entity": "select.mode",
                "usage_ml_per_m2": {"moderate": 5.3},
                "accounting_evidence": "maintainer_estimate",
            },
            state,
        )

        self.assertEqual(result["used_ml"], 23.25)
        self.assertEqual(result["last_accounting_source"], "area")
        self.assertEqual(result["last_accounting_rate_ml"], 5.3)

    def test_area_reset_decrease_gap_and_anomaly_only_rebaseline(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "area_sensor": "sensor.area",
            "usage_ml_per_m2": {"standard": 6},
            "area_anomaly_ceiling_m2": 5,
        }

        decreased, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("8")}),
            device,
            {"used_ml": 10, "last_area": 10, "last_status": "cleaning"},
        )
        gap, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("unavailable")}),
            device,
            {"used_ml": 10, "last_area": 8, "last_status": "cleaning"},
        )
        after_gap, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("12")}),
            device,
            {**gap, "last_area": 8},
        )
        anomalous, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("30")}),
            device,
            {"used_ml": 10, "last_area": 12, "last_status": "cleaning"},
        )

        self.assertEqual((decreased["used_ml"], decreased["last_area"]), (10, 8))
        self.assertEqual(decreased["last_accounting_reason"], "area_reset")
        self.assertEqual(gap["used_ml"], 10)
        self.assertTrue(gap["area_gap"])
        self.assertEqual((after_gap["used_ml"], after_gap["last_area"]), (10, 12))
        self.assertEqual(after_gap["last_accounting_reason"], "area_gap")
        self.assertEqual((anomalous["used_ml"], anomalous["last_area"]), (10, 30))
        self.assertEqual(anomalous["last_accounting_reason"], "area_anomaly")

if __name__ == "__main__":
    unittest.main(verbosity=2)
