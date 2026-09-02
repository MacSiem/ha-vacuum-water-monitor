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
    def __init__(self, values, *, length_unit="km"):
        self.states = _States(values)
        self.config = types.SimpleNamespace(
            units=types.SimpleNamespace(length_unit=length_unit)
        )


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
    def test_matter_vacuum_without_area_sensor_estimates_mopping_by_active_time(self):
        state, dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.status": _State("running"),
                    "select.clean_mode": _State("Auto, Vacuum and Mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "cleaning_mode_entity": "select.clean_mode",
                "rate_signal": "cleaning_mode",
                "mop_evidence_required": True,
                "usage_ml_per_active_minute": {"auto_vacuum_and_mop": 6},
                "accounting_evidence": "cross_model_estimate",
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_tick_ts": 1_000_000,
                "last_status": "running",
            },
            now_ts=1_060_000,
        )

        self.assertTrue(dirty)
        self.assertEqual(state["used_ml"], 106)
        self.assertEqual(state["last_accounting_source"], "active_time")
        self.assertEqual(state["last_accounting_evidence"], "cross_model_estimate")

    def test_time_fallback_does_not_count_vacuum_only_mode(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.status": _State("running"),
                    "select.clean_mode": _State("Auto, Vacuum only"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "cleaning_mode_entity": "select.clean_mode",
                "rate_signal": "cleaning_mode",
                "mop_evidence_required": True,
                "usage_ml_per_active_minute": {"auto_vacuum_and_mop": 6},
            },
            {"used_ml": 100, "initialized": True, "last_tick_ts": 1_000_000},
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "mop_inactive")

    def test_matter_time_estimate_requires_a_real_clean_mode_signal(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.status": _State("running"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "rate_signal": "cleaning_mode",
                "mop_evidence_required": True,
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "mop_inactive")

    def test_duration_sensor_is_preferred_over_wall_clock_when_area_is_absent(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.cleaning_time": _State(
                        "120", {"unit_of_measurement": "s"}
                    ),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "duration_sensor": "sensor.cleaning_time",
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_duration_seconds": 60,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_090_000,
        )

        self.assertEqual(state["used_ml"], 106)
        self.assertEqual(state["last_duration_seconds"], 120)
        self.assertEqual(state["last_accounting_source"], "active_time")

    def test_duration_sensor_with_unknown_explicit_unit_fails_closed(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.cleaning_time": _State(
                        "120", {"unit_of_measurement": "ticks"}
                    ),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "duration_sensor": "sensor.cleaning_time",
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "last_duration_seconds": 60,
                "last_status": "cleaning",
            },
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_duration_seconds"], 60)

    def test_valetudo_square_centimetres_are_normalized_before_accounting(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State(
                        "20000", {"unit_of_measurement": "cm²"}
                    ),
                    "select.mode": _State("vacuum_and_mop"),
                    "select.water": _State("medium"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "cleaning_mode_entity": "select.mode",
                "mop_intensity_entity": "select.water",
                "mop_evidence_required": True,
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"medium": 6},
            },
            {"used_ml": 100, "initialized": True, "last_area": 1},
        )

        self.assertEqual(state["last_area"], 2)
        self.assertEqual(state["used_ml"], 106)

    def test_explicit_unknown_area_unit_fails_closed(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State(
                        "20000", {"unit_of_measurement": "vendor_ticks"}
                    ),
                    "select.mode": _State("mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "cleaning_mode_entity": "select.mode",
                "mop_evidence_required": True,
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 100, "initialized": True, "last_area": 1},
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "area_unavailable")

    def test_known_adapter_without_mop_evidence_does_not_consume(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("2", {"unit_of_measurement": "m²"}),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "mop_evidence_required": True,
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 100, "initialized": True, "last_area": 1},
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "mop_off")

    def test_roomba_imperial_area_attribute_is_converted_to_square_metres(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State(
                        "cleaning",
                        {
                            "cleaned_area": 21.5278208,
                            "tank_present": True,
                            "fan_speed": "Standard-2",
                        },
                    ),
                },
                length_unit="mi",
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_attribute": "cleaned_area",
                "area_attribute_unit": "ha_unit_system",
                "mop_intensity_attribute": "fan_speed",
                "water_box_attached_attribute": "tank_present",
                "mop_evidence_required": True,
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"medium": 8},
            },
            {"used_ml": 100, "initialized": True, "last_area": 1},
        )

        self.assertAlmostEqual(state["last_area"], 2, places=6)
        self.assertAlmostEqual(state["used_ml"], 108, places=5)

    def test_roomba_documented_vacuum_attributes_feed_area_and_mode_accounting(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State(
                        "cleaning",
                        {
                            "cleaned_area": 10,
                            "cleaning_time": 20,
                            "tank_present": True,
                            "fan_speed": "Standard-2",
                        },
                    ),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_attribute": "cleaned_area",
                "duration_attribute": "cleaning_time",
                "duration_attribute_unit": "min",
                "mop_intensity_attribute": "fan_speed",
                "water_box_attached_attribute": "tank_present",
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"low": 4, "medium": 8, "high": 12},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_area": 9,
                "last_duration_seconds": 1140,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 108)
        self.assertEqual(state["last_area"], 10)
        self.assertEqual(state["last_duration_seconds"], 1200)
        self.assertEqual(state["last_accounting_source"], "area")

    def test_roomba_spray_suffix_selects_rate_independently_of_cleaning_pattern(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State(
                        "cleaning",
                        {"cleaned_area": 11, "tank_present": True, "fan_speed": "Deep-3"},
                    ),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_attribute": "cleaned_area",
                "mop_intensity_attribute": "fan_speed",
                "water_box_attached_attribute": "tank_present",
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"low": 4, "medium": 8, "high": 12},
            },
            {"used_ml": 100, "initialized": True, "last_area": 10},
        )

        self.assertEqual(state["used_ml"], 112)
        self.assertEqual(state["last_accounting_rate_ml"], 12)

    def test_ecovacs_station_wash_state_counts_one_wash_cycle(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.station": _State("washing_mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "dock_status_sensor": "sensor.station",
                "wash_volume_ml": 160,
            },
            {"used_ml": 20, "initialized": True, "last_status": "docked"},
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 180)
        self.assertTrue(state["wash_sequence_active"])
        self.assertEqual(state["last_dock_status"], "washing_mop")

    def test_generic_dock_cleaning_state_is_not_a_mop_wash_cycle(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.station": _State("cleaning"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "dock_status_sensor": "sensor.station",
                "wash_volume_ml": 160,
            },
            {"used_ml": 20, "initialized": True, "last_status": "docked"},
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 20)
        self.assertFalse(state.get("wash_sequence_active", False))

    def test_explicit_cleaning_binary_sensor_enables_time_fallback(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("idle"),
                    "binary_sensor.in_cleaning": _State("on"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "cleaning_active_sensor": "binary_sensor.in_cleaning",
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 106)

    def test_detached_water_box_stops_automatic_mop_accounting(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "binary_sensor.water_box": _State("off"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "water_box_attached_sensor": "binary_sensor.water_box",
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "mop_inactive")

    def test_inverted_detached_tank_signal_stops_mop_accounting(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "binary_sensor.tank_detached": _State("on"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "water_box_detached_sensor": "binary_sensor.tank_detached",
                "usage_ml_per_active_minute": {"default": 6},
            },
            {
                "used_ml": 100,
                "initialized": True,
                "last_tick_ts": 1_000_000,
            },
            now_ts=1_060_000,
        )

        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "mop_inactive")

    def test_low_water_status_anchors_and_calibrates_the_model_estimate_once(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "water_shortage_sensor": "binary_sensor.shortage",
            "tracked_capacity_ml": 5000,
        }
        initial = {
            "used_ml": 4000,
            "initialized": True,
            "last_tick_ts": 1_000_000,
            "water_empty_active": False,
            "calibration_factor": 1.0,
            "calibration_samples": 0,
        }
        candidate, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("on"),
                }
            ),
            device,
            initial,
            now_ts=1_060_000,
        )
        confirmed, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("on"),
                }
            ),
            device,
            candidate,
            now_ts=1_120_000,
        )
        repeated, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("on"),
                }
            ),
            device,
            confirmed,
            now_ts=1_180_000,
        )

        self.assertEqual(candidate["used_ml"], 4000)
        self.assertFalse(candidate["water_empty_active"])
        self.assertEqual(candidate["calibration_samples"], 0)
        self.assertEqual(candidate["water_anchor_candidate_source"], "water_shortage")
        self.assertEqual(confirmed["used_ml"], 4500)
        self.assertEqual(confirmed["calibration_factor"], 1.125)
        self.assertEqual(confirmed["calibration_samples"], 1)
        self.assertEqual(confirmed["water_anchor_kind"], "shortage")
        self.assertEqual(confirmed["water_anchor_confidence"], "estimated")
        self.assertEqual(confirmed["last_accounting_reason"], "low_water_calibrated")
        self.assertEqual(repeated["calibration_samples"], 1)
        self.assertEqual(repeated["calibration_factor"], 1.125)

    def test_dock_water_shortage_is_debounced_as_a_threshold_not_exact_empty(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "dock_error_sensor": "sensor.dock_error",
            "tracked_capacity_ml": 5000,
        }
        initial = {
            "used_ml": 4000,
            "initialized": True,
            "last_tick_ts": 1_000_000,
            "water_empty_active": False,
            "calibration_factor": 1.0,
            "calibration_samples": 0,
        }
        candidate, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.dock_error": _State("water_shortage"),
                }
            ),
            device,
            initial,
            now_ts=1_060_000,
        )
        confirmed, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.dock_error": _State("water_shortage"),
                }
            ),
            device,
            candidate,
            now_ts=1_120_000,
        )

        self.assertEqual(candidate["used_ml"], 4000)
        self.assertFalse(candidate["water_empty_active"])
        self.assertEqual(candidate["water_anchor_candidate_source"], "dock_error")
        self.assertEqual(confirmed["used_ml"], 4500)
        self.assertEqual(confirmed["water_anchor_kind"], "shortage")
        self.assertEqual(confirmed["water_anchor_confidence"], "estimated")

    def test_early_low_water_alert_is_rejected_without_rewriting_counter(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "water_shortage_sensor": "binary_sensor.shortage",
            "tracked_capacity_ml": 5000,
        }
        initial = {
            "used_ml": 100,
            "initialized": True,
            "last_tick_ts": 1_000_000,
            "water_empty_active": False,
            "calibration_factor": 1.0,
            "calibration_samples": 0,
        }
        candidate, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("on"),
                }
            ),
            device,
            initial,
            now_ts=1_060_000,
        )
        rejected, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("on"),
                }
            ),
            device,
            candidate,
            now_ts=1_120_000,
        )

        self.assertEqual(rejected["used_ml"], 100)
        self.assertFalse(rejected["water_empty_active"])
        self.assertEqual(rejected["calibration_factor"], 1.0)
        self.assertEqual(rejected["calibration_samples"], 0)
        self.assertEqual(
            rejected["last_accounting_reason"],
            "low_water_rejected_insufficient_usage",
        )

    def test_cleared_low_water_status_marks_a_refill_and_keeps_learning(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("off"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "water_shortage_sensor": "binary_sensor.shortage",
                "tracked_capacity_ml": 5000,
            },
            {
                "used_ml": 4500,
                "initialized": True,
                "water_empty_active": True,
                "water_anchor_source": "water_shortage",
                "water_anchor_kind": "shortage",
                "calibration_factor": 1.125,
                "calibration_samples": 1,
                "last_reset_ts": 0,
            },
            now_ts=2_000_000,
        )

        self.assertEqual(state["used_ml"], 0)
        self.assertFalse(state["water_empty_active"])
        self.assertEqual(state["calibration_factor"], 1.125)
        self.assertEqual(state["calibration_samples"], 1)
        self.assertEqual(state["last_accounting_reason"], "refill_detected")

    def test_unavailable_low_water_signal_does_not_create_a_false_refill(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "binary_sensor.shortage": _State("unavailable"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "water_shortage_sensor": "binary_sensor.shortage",
                "tracked_capacity_ml": 5000,
            },
            {
                "used_ml": 4500,
                "initialized": True,
                "water_empty_active": True,
                "water_anchor_source": "water_shortage",
                "water_anchor_kind": "shortage",
                "calibration_factor": 1.125,
                "calibration_samples": 1,
                "last_reset_ts": 0,
            },
            now_ts=2_000_000,
        )

        self.assertEqual(state["used_ml"], 4500)
        self.assertTrue(state["water_empty_active"])
        self.assertEqual(state["calibration_samples"], 1)

    def test_valetudo_exact_empty_state_is_an_anchor_but_missing_is_not(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "dock_clean_water_sensor": "sensor.freshwater",
            "tracked_capacity_ml": 4000,
        }
        initial = {
            "used_ml": 3200,
            "initialized": True,
            "water_empty_active": False,
            "calibration_factor": 1,
            "calibration_samples": 0,
        }
        missing, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.freshwater": _State("missing"),
                }
            ),
            device,
            initial,
            now_ts=2_000_000,
        )
        empty, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.freshwater": _State("empty"),
                }
            ),
            device,
            initial,
            now_ts=2_000_000,
        )

        self.assertEqual(missing["used_ml"], 3200)
        self.assertFalse(missing["water_empty_active"])
        self.assertEqual(missing["calibration_samples"], 0)
        self.assertEqual(empty["used_ml"], 4000)
        self.assertTrue(empty["water_empty_active"])
        self.assertEqual(empty["water_anchor_source"], "dock_clean_water")
        self.assertEqual(empty["water_anchor_kind"], "empty")

    def test_matter_machine_readable_water_tank_empty_error_is_an_anchor(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("error"),
                    "sensor.water_error": _State("water_tank_empty"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "water_error_sensor": "sensor.water_error",
                "tracked_capacity_ml": 5000,
            },
            {
                "used_ml": 4500,
                "initialized": True,
                "water_empty_active": False,
                "calibration_factor": 1,
                "calibration_samples": 0,
            },
            now_ts=2_000_000,
        )

        self.assertEqual(state["used_ml"], 5000)
        self.assertTrue(state["water_empty_active"])
        self.assertEqual(state["water_anchor_source"], "water_error")
        self.assertEqual(state["water_anchor_kind"], "empty")

    def test_transient_clean_box_empty_does_not_masquerade_as_dock_tank_empty(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "binary_sensor.clean_box_empty": _State("on"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "dock_clean_water_sensor": "binary_sensor.clean_box_empty",
                "tracked_capacity_ml": 3000,
            },
            {
                "used_ml": 500,
                "initialized": True,
                "water_empty_active": False,
                "calibration_samples": 0,
            },
            now_ts=2_000_000,
        )

        self.assertEqual(state["used_ml"], 500)
        self.assertFalse(state["water_empty_active"])
        self.assertEqual(state["calibration_samples"], 0)

    def test_localized_mop_wash_status_is_normalized_before_transition_accounting(self):
        result = _run(
            "docked",
            "Lavage de la serpillere",
            {"wash_volume_ml": 160},
        )

        self.assertEqual(result["used_ml"], 160)
        self.assertTrue(result["wash_sequence_active"])

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

    def test_transient_status_does_not_end_persisted_wash_sequence(self):
        rate = {"wash_volume_ml": 150}

        def step(state, status):
            hass = _Hass(
                {
                    "vacuum.test": _State("docked", {"status": status}),
                    "sensor.status": _State(status),
                }
            )
            return tick.tick_device(
                hass,
                {
                    "vacuum_entity": "vacuum.test",
                    "status_sensor": "sensor.status",
                    **rate,
                },
                state,
            )[0]

        first = step({"used_ml": 0, "last_status": "docked"}, "washing_the_mop")
        transient = step(first, "unavailable")
        unknown = step(transient, "unknown")
        empty = step(unknown, "")
        resumed = step(empty, "washing_the_mop")
        exited = step(resumed, "cleaning")
        next_wash = step(exited, "washing_the_mop")

        self.assertEqual(first["used_ml"], 150)
        self.assertEqual(transient["used_ml"], 150)
        self.assertEqual(unknown["used_ml"], 150)
        self.assertEqual(empty["used_ml"], 150)
        self.assertEqual(resumed["used_ml"], 150)
        self.assertEqual(next_wash["used_ml"], 300)

    def test_legacy_wash_status_without_latch_does_not_charge_after_restart(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked", {"status": "washing_the_mop"}),
                    "sensor.status": _State("washing_the_mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "wash_volume_ml": 150,
            },
            {
                "used_ml": 150,
                "last_status": "washing_the_mop",
                "wash_sequence_active": False,
            },
        )

        self.assertEqual(state["used_ml"], 150)
        self.assertTrue(state["wash_sequence_active"])

    def test_missing_configured_status_signal_keeps_wash_latch_active(self):
        state, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("docked", {"status": "docked"})}),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.missing_status",
                "wash_volume_ml": 150,
            },
            {
                "used_ml": 150,
                "last_status": "washing_the_mop",
                "wash_sequence_active": True,
            },
        )

        self.assertTrue(state["wash_sequence_active"])
        self.assertEqual(state["used_ml"], 150)
        self.assertEqual(state["last_accounting_reason"], "status_unavailable")

    def test_missing_configured_area_signal_records_reason_before_baseline(self):
        state, dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning")}),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.missing_area",
                "usage_ml_per_m2": {"default": 5},
            },
            {"used_ml": 0, "last_area": None, "last_status": "cleaning"},
        )

        self.assertTrue(dirty)
        self.assertTrue(state["area_gap"])
        self.assertEqual(state["last_accounting_reason"], "area_unavailable")

    def test_generic_device_without_user_rate_never_consumes(self):
        state, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("12"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "brand_profile": "generic",
            },
            {"used_ml": 10, "last_area": 10, "last_status": "cleaning"},
        )

        self.assertEqual(state["used_ml"], 10)
        self.assertEqual(state["last_accounting_reason"], "missing_area_rate")

    def test_literal_tenth_square_meter_doses_but_smaller_delta_does_not(self):
        device = {
            "vacuum_entity": "vacuum.test",
            "area_sensor": "sensor.area",
            "usage_ml_per_m2": {"default": 5},
        }

        at_threshold, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("10.1")}),
            device,
            {"used_ml": 10, "last_area": 10.0, "last_status": "cleaning"},
        )
        below_threshold, _dirty = tick.tick_device(
            _Hass({"vacuum.test": _State("cleaning"), "sensor.area": _State("10.099")}),
            device,
            {"used_ml": 10, "last_area": 10.0, "last_status": "cleaning"},
        )

        self.assertEqual(at_threshold["used_ml"], 10.5)
        self.assertEqual(below_threshold["used_ml"], 10)
        self.assertEqual(below_threshold["last_accounting_reason"], "area_delta_below_minimum")

    def test_tick_device_returns_new_state_without_mutating_caller_state(self):
        original = {"used_ml": 10, "last_status": "docked", "last_area": None}
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked", {"status": "washing_the_mop"}),
                    "sensor.status": _State("washing_the_mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "wash_volume_ml": 150,
            },
            original,
        )

        self.assertIsNot(result, original)
        self.assertEqual(original, {"used_ml": 10, "last_status": "docked", "last_area": None})
        self.assertEqual(result["used_ml"], 160)

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

    def test_profile_rate_axis_uses_mop_intensity_when_declared(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("11"),
                    "select.mode": _State("standard"),
                    "select.intensity": _State("high"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "mop_mode_entity": "select.mode",
                "mop_intensity_entity": "select.intensity",
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {
                    "low": 4,
                    "medium": 7.5,
                    "high": 11.5,
                    "default": 7.5,
                },
            },
            {"used_ml": 0, "last_area": 10, "last_status": "cleaning"},
        )

        self.assertEqual(result["used_ml"], 11.5)
        self.assertEqual(result["last_accounting_rate_ml"], 11.5)

    def test_five_level_water_control_interpolates_between_profile_bands(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("11"),
                    "select.intensity": _State("moderate_high"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "mop_intensity_entity": "select.intensity",
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"low": 4, "medium": 8, "high": 12},
            },
            {"used_ml": 0, "last_area": 10, "last_status": "cleaning"},
        )

        self.assertEqual(result["used_ml"], 10)
        self.assertEqual(result["last_accounting_rate_ml"], 10)

    def test_numeric_water_control_uses_its_entity_range_for_rate_band(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("11"),
                    "number.intensity": _State("80", {"min": 0, "max": 100}),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "mop_intensity_entity": "number.intensity",
                "rate_signal": "mop_intensity",
                "usage_ml_per_m2": {"low": 4, "medium": 8, "high": 12},
            },
            {"used_ml": 0, "last_area": 10, "last_status": "cleaning"},
        )

        self.assertEqual(result["used_ml"], 12)
        self.assertEqual(result["last_accounting_rate_ml"], 12)

    def test_vendor_segment_cleaning_status_counts_area_when_vacuum_state_lags(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.status": _State("segment_cleaning"),
                    "sensor.area": _State("4"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "area_sensor": "sensor.area",
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 0, "last_area": 3, "last_status": "docked"},
        )

        self.assertEqual(result["used_ml"], 6)

    def test_roborock_segment_mopping_status_counts_area_when_vacuum_state_lags(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("docked"),
                    "sensor.status": _State("segment_mopping"),
                    "sensor.area": _State("4", {"unit_of_measurement": "m²"}),
                    "select.mode": _State("mop"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "status_sensor": "sensor.status",
                "area_sensor": "sensor.area",
                "cleaning_mode_entity": "select.mode",
                "mop_evidence_required": True,
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 0, "last_area": 3, "last_status": "docked"},
        )

        self.assertEqual(result["used_ml"], 6)
        self.assertIsNone(result.get("last_accounting_reason"))

    def test_dreame_sweeping_mode_never_doses_with_tank_installed(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("4", {"unit_of_measurement": "m²"}),
                    "select.cleaning_mode": _State("sweeping"),
                    "sensor.water_tank": _State("installed"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "cleaning_mode_entity": "select.cleaning_mode",
                "water_box_attached_sensor": "sensor.water_tank",
                "mop_evidence_required": True,
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 0, "last_area": 3, "last_status": "cleaning"},
        )

        self.assertEqual(result["used_ml"], 0)
        self.assertEqual(result["last_accounting_reason"], "mop_off")

    def test_dreame_mop_installed_enum_is_affirmative_mop_evidence(self):
        result, _dirty = tick.tick_device(
            _Hass(
                {
                    "vacuum.test": _State("cleaning"),
                    "sensor.area": _State("4", {"unit_of_measurement": "m²"}),
                    "sensor.water_tank": _State("mop_installed"),
                }
            ),
            {
                "vacuum_entity": "vacuum.test",
                "area_sensor": "sensor.area",
                "water_box_attached_sensor": "sensor.water_tank",
                "mop_evidence_required": True,
                "usage_ml_per_m2": {"default": 6},
            },
            {"used_ml": 0, "last_area": 3, "last_status": "cleaning"},
        )

        self.assertEqual(result["used_ml"], 6)
        self.assertIsNone(result.get("last_accounting_reason"))

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

class MopEvidenceFromWaterOutputTests(unittest.TestCase):
    """Water-output level is direct mop evidence for MIoT-style integrations.

    Xiaomi H50 / H50 Pro via ``xiaomi_home`` expose ``mop-water-output-level``
    but no mop-mode or mop-attachment entity.  Without this, the evidence gate
    rejected every run and the vacuum could never accrue usage (issue #11).
    """

    def test_non_zero_water_output_level_counts_as_evidence(self) -> None:
        self.assertTrue(
            tick._is_mop_active(
                None,
                None,
                None,
                None,
                mop_intensity="2",
                intensity_is_evidence=True,
                require_evidence=True,
            )
        )

    def test_zero_water_output_level_ends_mopping(self) -> None:
        for level in ("0", "0_0", "off", "close"):
            with self.subTest(level=level):
                self.assertFalse(
                    tick._is_mop_active(
                        None,
                        None,
                        None,
                        None,
                        mop_intensity=level,
                        intensity_is_evidence=True,
                        require_evidence=True,
                    )
                )

    def test_absent_water_output_level_still_fails_closed(self) -> None:
        self.assertFalse(
            tick._is_mop_active(
                None, None, None, None, intensity_is_evidence=True,
                require_evidence=True,
            )
        )

    def test_zero_level_overrides_a_mop_mode_label(self) -> None:
        self.assertFalse(
            tick._is_mop_active(
                "mop", "standard", True, True, mop_intensity="off",
                intensity_is_evidence=True, require_evidence=True,
            )
        )

    def test_detached_mop_still_wins_over_a_stale_water_level(self) -> None:
        self.assertFalse(
            tick._is_mop_active(
                None, None, False, None, mop_intensity="3",
                intensity_is_evidence=True, require_evidence=True,
            )
        )

    def test_localized_level_token_is_not_read_as_evidence(self) -> None:
        """``ha_xiaomi_home`` renders enum options in the user's HA language.

        Treating unrecognized text as "water flowing" would bill a translated
        "off" as mopping, so an unknown token must prove nothing either way.
        """
        for token in ("wyaczony", "ausgeschaltet", "arret"):
            with self.subTest(token=token):
                self.assertFalse(
                    tick._is_mop_active(
                        None,
                        None,
                        None,
                        None,
                        mop_intensity=token,
                        intensity_is_evidence=True,
                        require_evidence=True,
                    )
                )

    def test_level_is_ignored_for_adapters_that_do_not_declare_it(self) -> None:
        """Roomba binds this role to ``fan_speed``; Ecovacs has no "off" level.

        Without the adapter gate a plain vacuuming run on those integrations
        would be billed as mopping, which is a regression for users whose
        counters are currently correct.
        """
        for level in ("automatic", "medium", "high"):
            with self.subTest(level=level):
                self.assertFalse(
                    tick._is_mop_active(
                        None,
                        None,
                        None,
                        None,
                        mop_intensity=level,
                        require_evidence=True,
                    )
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
