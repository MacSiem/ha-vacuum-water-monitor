"""Pure calculation tests for Vacuum Water Monitor sensors."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

HELPER_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "ha_vacuum_water_monitor"
    / "sensor_calculations.py"
)
spec = importlib.util.spec_from_file_location("sensor_calculations", HELPER_PATH)
assert spec and spec.loader
sensor_calculations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sensor_calculations)

build_vacuum_devices = sensor_calculations.build_vacuum_devices
estimate_water_state = sensor_calculations.estimate_water_state
apply_custom_calibration = sensor_calculations.apply_custom_calibration
filter_active_devices = sensor_calculations.filter_active_devices
next_maintenance_due = sensor_calculations.next_maintenance_due
parse_refill_datetime = sensor_calculations.parse_refill_datetime
vacuum_slug = sensor_calculations.vacuum_slug


class VacuumSensorCalculationTests(unittest.TestCase):
    """Verify Store-derived sensor helper behavior."""

    def test_unknown_sensor_states_explain_the_required_setup_action(self) -> None:
        guidance = getattr(sensor_calculations, "setup_guidance", None)
        self.assertIsNotNone(
            guidance,
            "unknown entity states need machine-readable setup guidance",
        )
        assert guidance is not None
        self.assertEqual(
            guidance("awaiting_refill"),
            {
                "state_reason": "awaiting_refill",
                "action_required": "press_refilled_with_full_reservoir",
            },
        )
        self.assertEqual(
            guidance("maintenance_not_configured"),
            {
                "state_reason": "maintenance_not_configured",
                "action_required": "configure_maintenance_schedule",
            },
        )
        self.assertEqual(guidance(None), {})

    def test_estimate_water_state_clamps_remaining_percent(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.roborock", "water_total_ml": 3000},
            {"used_ml": 450, "last_reset_ts": 1},
            {},
        )

        self.assertEqual(estimate["total_ml"], 3000)
        self.assertEqual(estimate["used_ml"], 450)
        self.assertEqual(estimate["remaining_ml"], 2550)
        self.assertEqual(estimate["remaining_percent"], 85)
        self.assertEqual(estimate["source"], "stored_estimate")

    def test_estimate_water_state_exposes_signal_contract_diagnostics(self) -> None:
        estimate = estimate_water_state(
            {
                "vacuum_entity": "vacuum.test",
                "water_total_ml": 1000,
                "integration_adapter": "dreame_vacuum",
                "signal_contract_version": 1,
                "mop_evidence_required": True,
            },
            {"used_ml": 100, "last_reset_ts": 1},
            {},
        )

        self.assertEqual(estimate["integration_adapter"], "dreame_vacuum")
        self.assertEqual(estimate["signal_contract_version"], 1)
        self.assertTrue(estimate["mop_evidence_required"])

    def test_estimate_water_state_uses_custom_calibration_capacity(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.custom", "brand_profile": "custom_profile"},
            {"used_ml": 1250, "last_reset_ts": 1},
            {"custom_calibration": {"custom_profile": {"tank_ml": 2500}}},
        )

        self.assertEqual(estimate["total_ml"], 2500)
        self.assertEqual(estimate["remaining_ml"], 1250)
        self.assertEqual(estimate["remaining_percent"], 50)

    def test_estimate_water_state_returns_unknown_without_capacity(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.unknown"},
            {"used_ml": 99, "last_reset_ts": 1},
            {},
        )

        self.assertIsNone(estimate["total_ml"])
        self.assertEqual(estimate["used_ml"], 99)
        self.assertIsNone(estimate["remaining_ml"])
        self.assertIsNone(estimate["remaining_percent"])
        self.assertEqual(estimate["source"], "unknown_capacity")

    def test_estimate_water_state_uses_model_database_via_entity_id(self) -> None:
        # No manual calibration, no stored capacity — capacity must come from the
        # model database, auto-detected from the vacuum entity id (the card's rule).
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.roborock_s8_maxv_ultra"},
            {"used_ml": 0, "last_reset_ts": 1},
            {"custom_calibration": {}},
        )

        self.assertEqual(estimate["total_ml"], 4000)
        self.assertEqual(estimate["remaining_ml"], 4000)
        self.assertEqual(estimate["remaining_percent"], 100)
        self.assertEqual(estimate["source"], "stored_estimate")

    def test_estimate_water_state_model_database_via_brand_profile(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.living_room", "brand_profile": "dreame_x40_ultra"},
            {"used_ml": 900, "last_reset_ts": 1},
            {},
        )

        self.assertEqual(estimate["total_ml"], 4500)
        self.assertEqual(estimate["remaining_ml"], 3600)
        self.assertEqual(estimate["remaining_percent"], 80)

    def test_estimate_water_state_resolves_reported_roborock_model_aliases(self) -> None:
        cases = (
            ({"vacuum_entity": "vacuum.a170"}, 4000),
            (
                {
                    "vacuum_entity": "vacuum.living_room",
                    "brand_profile": "roborock.vacuum.a170",
                },
                4000,
            ),
            ({"vacuum_entity": "vacuum.a245"}, 4000),
        )

        for device, expected_capacity in cases:
            with self.subTest(device=device):
                estimate = estimate_water_state(device, {"used_ml": 0, "last_reset_ts": 1}, {})
                self.assertEqual(estimate["total_ml"], expected_capacity)

    def test_estimate_water_state_resolves_verified_new_model_capacities(self) -> None:
        cases = (
            ("vacuum.xiaomi_h50", 4000),
            ("vacuum.xiaomi_robot_vacuum_h50_pro", 4000),
            ("vacuum.tapo_rv50_pro_omni", 5000),
        )

        for entity_id, expected_capacity in cases:
            with self.subTest(entity_id=entity_id):
                estimate = estimate_water_state(
                    {"vacuum_entity": entity_id}, {"used_ml": 0, "last_reset_ts": 1}, {}
                )
                self.assertEqual(estimate["total_ml"], expected_capacity)

    def test_issue_10_tapo_matter_becomes_known_after_refill_baseline(self) -> None:
        """The opaque Matter entity must use registry profile data, not its id."""
        descriptor = {
            "entity_id": "vacuum.opaque_matter_device",
            "model": "RV50 Pro Omni (1797)",
            "model_id": "1797",
            "profile_key": "tapo_rv50_pro_omni",
            "profile_source": "model_id",
            "profile_confidence": "high",
            "tracked_reservoir": "dock_clean",
            "tracked_capacity_ml": 5000,
            "signals": {
                "status_sensor": "sensor.opaque_operational_state",
                "cleaning_mode_entity": "select.opaque_clean_mode",
            },
        }
        tank_state = {
            "used_ml": 0,
            "initialized": True,
            "last_reset_iso": "2026-08-31T20:00:00+00:00",
            "last_reset_ts": 1_788_204_000_000,
        }

        devices = build_vacuum_devices(
            {}, {"vacuum.opaque_matter_device": tank_state}, [descriptor]
        )
        estimate = estimate_water_state(devices[0], tank_state, {})

        self.assertEqual(devices[0]["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(devices[0]["tracked_capacity_ml"], 5000)
        self.assertEqual(
            devices[0]["status_sensor"], "sensor.opaque_operational_state"
        )
        self.assertEqual(estimate["source"], "stored_estimate")
        self.assertEqual(estimate["used_ml"], 0)
        self.assertEqual(estimate["remaining_ml"], 5000)
        self.assertEqual(estimate["remaining_percent"], 100)
        self.assertIsNotNone(parse_refill_datetime(tank_state))

    def test_estimate_water_state_uses_discovered_model_before_entity_alias(self) -> None:
        estimate = estimate_water_state(
            {
                "vacuum_entity": "vacuum.opaque_matter_device",
                "model": "Xiaomi Robot Vacuum H50 Pro",
            },
            {"used_ml": 0, "last_reset_ts": 1},
            {},
        )

        self.assertEqual(estimate["total_ml"], 4000)

    def test_estimate_water_state_uses_entity_scoped_custom_calibration(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.living_room"},
            {"used_ml": 200, "last_reset_ts": 1},
            {
                "custom_calibration": {
                    "entity:vacuum.living_room": {"tank_ml": 4200}
                }
            },
        )

        self.assertEqual(estimate["total_ml"], 4200)
        self.assertEqual(estimate["remaining_ml"], 4000)

    def test_apply_custom_calibration_feeds_water_accounting(self) -> None:
        device = {
            "vacuum_entity": "vacuum.living_room",
            "usage_ml_per_m2": {"standard": 7},
        }
        settings = {
            "custom_calibration": {
                "entity:vacuum.living_room": {
                    "water_per_m2": {"standard": 5, "deep": 9},
                    "mop_wash_ml": 175,
                }
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertEqual(effective["usage_ml_per_m2"], {"standard": 7, "deep": 9})
        self.assertEqual(effective["wash_volume_ml"], 175)
        self.assertNotIn("wash_volume_ml", device)

        custom_only = apply_custom_calibration(
            {"vacuum_entity": "vacuum.living_room"}, settings
        )
        self.assertEqual(
            custom_only["usage_ml_per_m2"], {"standard": 5, "deep": 9}
        )
        self.assertEqual(custom_only["wash_volume_ml"], 175)

    def test_profile_area_rates_gain_a_bounded_active_time_fallback(self) -> None:
        effective = apply_custom_calibration(
            {
                "vacuum_entity": "vacuum.braava",
                "model": "iRobot Roomba Combo j7",
            },
            {},
        )

        self.assertEqual(effective["usage_ml_per_m2"]["default"], 4)
        self.assertEqual(
            effective["usage_ml_per_active_minute"],
            {"low": 1.6, "medium": 3.2, "high": 5.6, "default": 3.2},
        )
        self.assertEqual(effective["estimated_m2_per_active_minute"], 0.8)
        self.assertEqual(effective["time_accounting_evidence"], "derived_from_area_rate")
        self.assertGreaterEqual(effective["uncertainty_percent"], 65)

    def test_device_calibration_can_tune_the_active_time_area_speed(self) -> None:
        effective = apply_custom_calibration(
            {
                "vacuum_entity": "vacuum.braava",
                "model": "iRobot Roomba Combo j7",
            },
            {
                "custom_calibration": {
                    "entity:vacuum.braava": {
                        "estimated_m2_per_active_minute": 1.0,
                    }
                }
            },
        )

        self.assertEqual(effective["estimated_m2_per_active_minute"], 1.0)
        self.assertEqual(effective["usage_ml_per_active_minute"]["default"], 4)


    def test_estimate_water_state_unknown_model_stays_unknown(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.robotic_vacuum_cleaner"},
            {"used_ml": 50, "last_reset_ts": 1},
            {},
        )

        self.assertIsNone(estimate["total_ml"])
        self.assertEqual(estimate["source"], "unknown_capacity")

    def test_estimate_water_state_is_unknown_until_refill_initializes_it(self) -> None:
        before_refill = estimate_water_state(
            {"vacuum_entity": "vacuum.custom", "water_total_ml": 3000},
            {"used_ml": 0},
            {},
        )
        after_refill = estimate_water_state(
            {"vacuum_entity": "vacuum.custom", "water_total_ml": 3000},
            {"used_ml": 0, "last_reset_iso": "2026-08-30T10:00:00+00:00"},
            {},
        )

        self.assertFalse(before_refill["initialized"])
        self.assertEqual(before_refill["state_reason"], "awaiting_refill")
        self.assertIsNone(before_refill["used_ml"])
        self.assertIsNone(before_refill["remaining_percent"])
        self.assertTrue(after_refill["initialized"])
        self.assertEqual(after_refill["used_ml"], 0)
        self.assertEqual(after_refill["remaining_percent"], 100)

    def test_low_water_anchor_reports_estimated_reserve_with_learning_metadata(self) -> None:
        estimate = estimate_water_state(
            {
                "model_id": "1797",
                "vacuum_entity": "vacuum.tapo",
            },
            {
                "used_ml": 4500,
                "initialized": True,
                "water_empty_active": True,
                "water_anchor_kind": "shortage",
                "water_anchor_confidence": "estimated",
                "calibration_factor": 1.22,
                "calibration_samples": 2,
            },
            {},
        )

        self.assertEqual(estimate["source"], "low_water_anchor")
        self.assertEqual(estimate["used_ml"], 4500)
        self.assertEqual(estimate["remaining_ml"], 500)
        self.assertEqual(estimate["remaining_percent"], 10)
        self.assertEqual(estimate["state_reason"], "water_low")
        self.assertEqual(estimate["water_anchor_kind"], "shortage")
        self.assertEqual(estimate["water_anchor_confidence"], "estimated")
        self.assertEqual(estimate["calibration_factor"], 1.22)
        self.assertEqual(estimate["calibration_samples"], 2)
        self.assertEqual(estimate["uncertainty_percent"], 60)

    def test_exact_empty_anchor_reports_zero_remaining(self) -> None:
        estimate = estimate_water_state(
            {"model_id": "1797", "vacuum_entity": "vacuum.tapo"},
            {
                "used_ml": 5000,
                "initialized": True,
                "water_empty_active": True,
                "water_anchor_kind": "empty",
                "water_anchor_confidence": "exact",
            },
            {},
        )

        self.assertEqual(estimate["source"], "low_water_anchor")
        self.assertEqual(estimate["remaining_ml"], 0)
        self.assertEqual(estimate["remaining_percent"], 0)
        self.assertEqual(estimate["state_reason"], "water_empty")

    def test_custom_calibration_merges_entity_rates_and_tracked_capacity(self) -> None:
        device = {
            "vacuum_entity": "vacuum.living_room",
            "usage_ml_per_m2": {"standard": 7},
        }
        settings = {
            "custom_calibration": {
                "entity:vacuum.living_room": {
                    "tracked_capacity_ml": 4200,
                    "usage_ml_per_m2": {"deep": 9},
                    "wash_volume_ml": 175,
                    "low_water_anchor_remaining_percent": 15,
                }
            }
        }

        effective = apply_custom_calibration(device, settings)
        estimate = estimate_water_state(effective, {"last_reset_ts": 1, "used_ml": 200}, settings)

        self.assertEqual(effective["usage_ml_per_m2"], {"standard": 7, "deep": 9})
        self.assertEqual(effective["wash_volume_ml"], 175)
        self.assertEqual(effective["low_water_anchor_remaining_percent"], 15)
        self.assertEqual(estimate["total_ml"], 4200)

    def test_entity_alias_calibration_overrides_canonical_default_layer(self) -> None:
        effective = apply_custom_calibration(
            {"vacuum_entity": "vacuum.living_room"},
            {
                "custom_calibration": {
                    "default": {
                        "usage_ml_per_m2": {"standard": 4},
                        "wash_volume_ml": 150,
                        "tracked_capacity_ml": 3000,
                    },
                    "entity:vacuum.living_room": {
                        "water_per_m2": {"standard": 9},
                        "mop_wash_ml": 175,
                        "tank_ml": 4200,
                    },
                }
            },
        )

        self.assertEqual(effective["usage_ml_per_m2"], {"standard": 9})
        self.assertEqual(effective["wash_volume_ml"], 175)
        self.assertEqual(effective["tracked_capacity_ml"], 4200)
        self.assertEqual(effective["accounting_evidence"], "user_calibration")

    def test_entity_calibration_overrides_profile_rates_discovered_for_that_entity(self) -> None:
        discovered = build_vacuum_devices(
            {},
            {},
            [
                {
                    "entity_id": "vacuum.living_room",
                    "model": "Roborock S8 MaxV Ultra",
                    "usage_ml_per_m2": {"fast": 4, "standard": 6, "deep": 9},
                    "wash_volume_ml": 150,
                    "accounting_evidence": "maintainer_estimate",
                }
            ],
        )[0]
        effective = apply_custom_calibration(
            discovered,
            {
                "custom_calibration": {
                    "entity:vacuum.living_room": {
                        "usage_ml_per_m2": {"standard": 7.5},
                        "wash_volume_ml": 175,
                        "tracked_capacity_ml": 4200,
                    }
                }
            },
        )

        self.assertEqual(effective["usage_ml_per_m2"]["standard"], 7.5)
        self.assertEqual(effective["wash_volume_ml"], 175)
        self.assertEqual(effective["tracked_capacity_ml"], 4200)
        self.assertEqual(effective["accounting_evidence"], "user_calibration")

    def test_registry_profile_skips_different_unlocked_legacy_calibration_layer(self) -> None:
        effective = apply_custom_calibration(
            {
                "vacuum_entity": "vacuum.a170",
                "profile_key": "roborock_qrevo_5ae",
                "brand_profile": "roborock_s8_maxv_ultra",
                "profile_locked": False,
            },
            {
                "custom_calibration": {
                    "default": {"usage_ml_per_m2": {"standard": 1}},
                    "roborock_qrevo_5ae": {
                        "usage_ml_per_m2": {"standard": 2}
                    },
                    "roborock_s8_maxv_ultra": {
                        "usage_ml_per_m2": {"standard": 9}
                    },
                }
            },
        )

        self.assertEqual(effective["usage_ml_per_m2"]["standard"], 2)

    def test_explicit_yaml_rate_keeps_precedence_even_when_it_matches_profile(self) -> None:
        device = build_vacuum_devices(
            {
                "configured_devices": [
                    {
                        "vacuum_entity": "vacuum.living_room",
                        "usage_ml_per_m2": {"fast": 4, "standard": 6, "deep": 9},
                    }
                ]
            },
            {},
            [{"entity_id": "vacuum.living_room", "model": "Roborock S8 MaxV Ultra"}],
        )[0]
        effective = apply_custom_calibration(
            device,
            {
                "custom_calibration": {
                    "entity:vacuum.living_room": {
                        "usage_ml_per_m2": {"standard": 7.5}
                    }
                }
            },
        )

        self.assertEqual(effective["usage_ml_per_m2"]["standard"], 6)

    def test_legacy_robot_tank_calibration_is_metadata_not_clean_water_capacity(self) -> None:
        device = {"vacuum_entity": "vacuum.unknown"}
        settings = {
            "custom_calibration": {
                "entity:vacuum.unknown": {"robot_tank_ml": 350}
            }
        }

        effective = apply_custom_calibration(device, settings)
        estimate = estimate_water_state(effective, {"last_reset_ts": 1, "used_ml": 0}, settings)

        self.assertEqual(effective["legacy_robot_tank_ml"], 350)
        self.assertIsNone(estimate["total_ml"])

    def test_parse_refill_datetime_prefers_iso_and_falls_back_to_millis(self) -> None:
        parsed = parse_refill_datetime(
            {"last_reset_iso": "2026-06-12T08:30:00+00:00", "last_reset_ts": 1}
        )

        self.assertEqual(parsed, datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc))

        fallback = parse_refill_datetime({"last_reset_ts": 1781253000000})

        self.assertEqual(fallback, datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc))

    def test_next_maintenance_due_selects_most_urgent_scheduled_item(self) -> None:
        now_ms = 1781231400000
        items = [
            {
                "name": "Clean sensors",
                "intervalDays": 30,
                "lastDone": now_ms - 25 * 86400000,
            },
            {
                "name": "Wash mop",
                "intervalDays": 7,
                "lastDone": now_ms - 9 * 86400000,
            },
            {"name": "Unscheduled", "intervalDays": 14, "lastDone": None},
        ]

        due = next_maintenance_due(items, now_ms=now_ms)

        self.assertIsNotNone(due)
        assert due is not None
        self.assertEqual(due["name"], "Wash mop")
        self.assertEqual(due["days_left"], -2)
        self.assertEqual(due["days_overdue"], 2)
        self.assertTrue(due["overdue"])

    def test_build_vacuum_devices_merges_store_devices_tank_states_and_discovery(self) -> None:
        devices = build_vacuum_devices(
            {
                "configured_devices": [
                    {
                        "vacuum_entity": "vacuum.roborock",
                        "name": "YAML Roborock",
                        "water_total_ml": 3000,
                    }
                ],
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.roborock",
                        "name": "Card Roborock",
                        "water_total_ml": 3500,
                    }
                ],
            },
            {"vacuum.legacy": {"used_ml": 12}},
            [{"entity_id": "vacuum.discovered", "name": "Discovered"}],
        )

        by_entity = {device["vacuum_entity"]: device for device in devices}
        self.assertEqual(by_entity["vacuum.roborock"]["name"], "Card Roborock")
        self.assertEqual(by_entity["vacuum.roborock"]["water_total_ml"], 3500)
        self.assertEqual(by_entity["vacuum.legacy"]["name"], "vacuum.legacy")
        self.assertEqual(by_entity["vacuum.discovered"]["name"], "Discovered")

    def test_discovered_adapter_roles_are_flattened_for_accounting(self) -> None:
        device = build_vacuum_devices(
            {},
            {},
            [
                {
                    "entity_id": "vacuum.adapter_robot",
                    "integration_adapter": "valetudo",
                    "signals": {
                        "cleaning_active_sensor": "binary_sensor.robot_cleaning",
                        "duration_sensor": "sensor.robot_time",
                        "water_box_attached_sensor": "binary_sensor.robot_tank",
                        "dock_dirty_water_sensor": "sensor.robot_wastewater",
                        "water_error_sensor": "sensor.robot_water_error",
                        "dock_status_sensor": "sensor.robot_dock_status",
                        "tank_level_sensor": "sensor.robot_tank_level",
                        "dock_tank_level_sensor": "sensor.robot_dock_tank_level",
                    },
                }
            ],
        )[0]

        self.assertEqual(device["integration_adapter"], "valetudo")
        self.assertEqual(
            device["cleaning_active_sensor"], "binary_sensor.robot_cleaning"
        )
        self.assertEqual(device["duration_sensor"], "sensor.robot_time")
        self.assertEqual(
            device["water_box_attached_sensor"], "binary_sensor.robot_tank"
        )
        self.assertEqual(
            device["dock_dirty_water_sensor"], "sensor.robot_wastewater"
        )
        self.assertEqual(device["water_error_sensor"], "sensor.robot_water_error")
        self.assertEqual(device["dock_status_sensor"], "sensor.robot_dock_status")
        self.assertEqual(device["tank_level_sensor"], "sensor.robot_tank_level")
        self.assertEqual(
            device["dock_tank_level_sensor"], "sensor.robot_dock_tank_level"
        )

    def test_legacy_expanded_store_defaults_are_generated_and_registry_replaceable(self) -> None:
        devices = build_vacuum_devices(
            {
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.a170",
                        "brand_profile": "roborock_s8_maxv_ultra",
                        "water_total_ml": 3000,
                        "area_sensor": "sensor.roborock_s8_maxv_ultra_cleaning_area",
                        "mop_mode_entity": "select.roborock_s8_maxv_ultra_mop_mode",
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.a170",
                    "profile_key": "roborock_qrevo_5ae",
                    "profile_source": "model_id",
                    "tracked_capacity_ml": 4000,
                    "signals": {
                        "area_sensor": "sensor.a170_area",
                        "mop_mode_entity": "select.a170_mop_mode",
                    },
                }
            ],
        )

        device = devices[0]
        self.assertEqual(device["profile_key"], "roborock_qrevo_5ae")
        self.assertEqual(device["tracked_capacity_ml"], 4000)
        self.assertNotIn("water_total_ml", device)
        self.assertEqual(device["area_sensor"], "sensor.a170_area")
        self.assertEqual(device["mop_mode_entity"], "select.a170_mop_mode")
        self.assertNotIn("area_sensor", device["_explicit_fields"])

    def test_divergent_legacy_store_value_remains_explicit(self) -> None:
        devices = build_vacuum_devices(
            {
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.a170",
                        "brand_profile": "roborock_s8_maxv_ultra",
                        "water_total_ml": 3100,
                        "area_sensor": "sensor.user_selected_area",
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.a170",
                    "profile_key": "roborock_qrevo_5ae",
                    "tracked_capacity_ml": 4000,
                    "signals": {"area_sensor": "sensor.a170_area"},
                }
            ],
        )

        device = devices[0]
        self.assertEqual(device["water_total_ml"], 3100)
        self.assertEqual(device["area_sensor"], "sensor.user_selected_area")
        self.assertIn("water_total_ml", device["_explicit_fields"])
        self.assertIn("area_sensor", device["_explicit_fields"])

    def test_authored_provenance_preserves_even_profile_matching_yaml_values(self) -> None:
        devices = build_vacuum_devices(
            {
                "configured_devices": [
                    {
                        "vacuum_entity": "vacuum.a170",
                        "brand_profile": "roborock_s8_maxv_ultra",
                        "water_total_ml": 3000,
                        "signals": {},
                        "config_provenance": {
                            "authored_fields": [
                                "vacuum_entity",
                                "brand_profile",
                                "water_total_ml",
                                "signals",
                            ]
                        },
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.a170",
                    "profile_key": "roborock_qrevo_5ae",
                    "tracked_capacity_ml": 4000,
                    "signals": {"area_sensor": "sensor.a170_area"},
                }
            ],
        )

        device = devices[0]
        self.assertEqual(device["water_total_ml"], 3000)
        self.assertEqual(device["signals"], {})
        self.assertNotIn("area_sensor", device)

    def test_legacy_profile_lock_without_provenance_remains_authored(self) -> None:
        devices = build_vacuum_devices(
            {
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.a170",
                        "brand_profile": "roborock_s8_maxv_ultra",
                        "profile_locked": True,
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.a170",
                    "profile_key": "roborock_qrevo_5ae",
                    "tracked_capacity_ml": 4000,
                    "signals": {"status_sensor": "sensor.registry_status"},
                }
            ],
        )

        device = devices[0]
        self.assertTrue(device["profile_locked"])
        self.assertIn("profile_locked", device["_explicit_fields"])
        self.assertEqual(device["profile_key"], "roborock_s8_maxv_ultra")
        self.assertEqual(estimate_water_state(device, {"used_ml": 0, "initialized": True}, {})["total_ml"], 4000)

    def test_authored_falsey_direct_signal_role_blocks_registry_value(self) -> None:
        devices = build_vacuum_devices(
            {
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.a170",
                        "status_sensor": "",
                        "area_sensor": None,
                        "config_provenance": {
                            "authored_fields": [
                                "vacuum_entity",
                                "status_sensor",
                                "area_sensor",
                            ]
                        },
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.a170",
                    "profile_key": "roborock_qrevo_5ae",
                    "signals": {
                        "status_sensor": "sensor.registry_status",
                        "area_sensor": "sensor.registry_area",
                    },
                }
            ],
        )

        device = devices[0]
        self.assertEqual(device["status_sensor"], "")
        self.assertIsNone(device["area_sensor"])
        self.assertNotIn("status_sensor", device.get("signals", {}))
        self.assertNotIn("area_sensor", device.get("signals", {}))

    def test_vacuum_slug_is_stable_for_entity_ids(self) -> None:
        self.assertEqual(vacuum_slug("vacuum.Roborock S8 MaxV"), "vacuum_roborock_s8_maxv")

    def test_tank_state_entry_gets_friendly_name_from_discovery(self) -> None:
        """Issue #1: device seeded from tank_states must not stay named by id."""
        devices = build_vacuum_devices(
            {},
            {"vacuum.roborock_s7_maxv": {"used_ml": 40}},
            [{"entity_id": "vacuum.roborock_s7_maxv", "name": "Roborock S7 MaxV"}],
        )

        by_entity = {device["vacuum_entity"]: device for device in devices}
        self.assertEqual(
            by_entity["vacuum.roborock_s7_maxv"]["name"], "Roborock S7 MaxV"
        )

    def test_discovery_name_does_not_override_user_name(self) -> None:
        devices = build_vacuum_devices(
            {
                "configured_devices": [
                    {"vacuum_entity": "vacuum.roborock_s7_maxv", "name": "Salon robot"}
                ]
            },
            {},
            [{"entity_id": "vacuum.roborock_s7_maxv", "name": "Roborock S7 MaxV"}],
        )

        self.assertEqual(devices[0]["name"], "Salon robot")

    def test_explicit_empty_signal_configuration_disables_discovery(self) -> None:
        devices = build_vacuum_devices(
            {
                "user_devices": [
                    {
                        "vacuum_entity": "vacuum.kitchen",
                        "status_sensor": None,
                        "area_sensor": "",
                        "signals": {},
                    }
                ]
            },
            {},
            [
                {
                    "entity_id": "vacuum.kitchen",
                    "signals": {
                        "status_sensor": "sensor.kitchen_status",
                        "area_sensor": "sensor.kitchen_area",
                        "mop_mode_entity": "select.kitchen_mop_mode",
                    },
                }
            ],
        )

        self.assertIsNone(devices[0]["status_sensor"])
        self.assertEqual(devices[0]["area_sensor"], "")
        self.assertEqual(devices[0]["signals"], {})
        self.assertNotIn("mop_mode_entity", devices[0])

    def test_filter_active_devices_drops_ghosts(self) -> None:
        """Issue #1: phantom configured entity must not create an HA device."""
        devices = [
            {"vacuum_entity": "vacuum.roborock_s8_maxv_ultra", "name": "Vacuum"},
            {"vacuum_entity": "vacuum.roborock_s7_maxv", "name": "Roborock S7 MaxV"},
            {"vacuum_entity": "vacuum.offline_bot", "name": "Offline bot"},
            {"name": "no entity"},
        ]

        kept = filter_active_devices(
            devices,
            {"vacuum.roborock_s7_maxv"},
            {"vacuum.offline_bot": {"used_ml": 10}},
        )

        kept_entities = [device["vacuum_entity"] for device in kept]
        self.assertEqual(
            kept_entities, ["vacuum.roborock_s7_maxv", "vacuum.offline_bot"]
        )


class ManualSignalOverrideTests(unittest.TestCase):
    """A hand-assigned entity is the most recent human decision about a device."""

    def test_override_binds_a_role_discovery_left_unresolved(self) -> None:
        device = {
            "vacuum_entity": "vacuum.h50_pro",
            "signals": {"status_sensor": "sensor.h50_status"},
        }
        settings = {
            "signal_overrides": {
                "vacuum.h50_pro": {"area_sensor": "sensor.h50_cleaning_area"}
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertEqual(effective["area_sensor"], "sensor.h50_cleaning_area")
        self.assertEqual(
            effective["signals"]["area_sensor"], "sensor.h50_cleaning_area"
        )
        self.assertEqual(
            effective["signals"]["status_sensor"],
            "sensor.h50_status",
            "an override must not discard the roles discovery did resolve",
        )

    def test_override_replaces_a_wrong_automatic_binding(self) -> None:
        device = {
            "vacuum_entity": "vacuum.h50_pro",
            "area_sensor": "sensor.total_area",
            "signals": {"area_sensor": "sensor.total_area"},
        }
        settings = {
            "signal_overrides": {
                "vacuum.h50_pro": {"area_sensor": "sensor.current_area"}
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertEqual(effective["area_sensor"], "sensor.current_area")
        self.assertEqual(effective["signals"]["area_sensor"], "sensor.current_area")

    def test_override_is_scoped_to_its_own_vacuum(self) -> None:
        device = {"vacuum_entity": "vacuum.other", "signals": {}}
        settings = {
            "signal_overrides": {
                "vacuum.h50_pro": {"area_sensor": "sensor.h50_cleaning_area"}
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertNotIn("area_sensor", effective.get("signals", {}))

    def test_entity_from_another_device_is_refused(self) -> None:
        """Binding a foreign entity would make two vacuums share one counter."""
        device = {
            "vacuum_entity": "vacuum.h50_pro",
            "signals": {},
            "sibling_entities": [
                {"entity_id": "sensor.h50_cleaning_area"},
                {"entity_id": "sensor.h50_cleaning_time"},
            ],
        }
        settings = {
            "signal_overrides": {
                "vacuum.h50_pro": {
                    "area_sensor": "sensor.other_robot_area",
                    "duration_sensor": "sensor.h50_cleaning_time",
                }
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertNotIn("area_sensor", effective.get("signals", {}))
        self.assertEqual(
            effective["signals"]["duration_sensor"], "sensor.h50_cleaning_time"
        )
        self.assertEqual(effective["signal_overrides_applied"], ["duration_sensor"])

    def test_blank_and_unknown_roles_are_ignored(self) -> None:
        device = {"vacuum_entity": "vacuum.h50_pro", "signals": {}}
        settings = {
            "signal_overrides": {
                "vacuum.h50_pro": {
                    "area_sensor": "   ",
                    "not_a_role": "sensor.nope",
                    "duration_sensor": "sensor.h50_cleaning_time",
                }
            }
        }

        effective = apply_custom_calibration(device, settings)

        self.assertNotIn("area_sensor", effective.get("signals", {}))
        self.assertNotIn("not_a_role", effective)
        self.assertEqual(
            effective["signals"]["duration_sensor"], "sensor.h50_cleaning_time"
        )
        self.assertEqual(effective["signal_overrides_applied"], ["duration_sensor"])


if __name__ == "__main__":
    unittest.main()
