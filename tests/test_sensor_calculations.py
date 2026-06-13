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
next_maintenance_due = sensor_calculations.next_maintenance_due
parse_refill_datetime = sensor_calculations.parse_refill_datetime
vacuum_slug = sensor_calculations.vacuum_slug


class VacuumSensorCalculationTests(unittest.TestCase):
    """Verify Store-derived sensor helper behavior."""

    def test_estimate_water_state_clamps_remaining_percent(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.roborock", "water_total_ml": 3000},
            {"used_ml": 450},
            {},
        )

        self.assertEqual(estimate["total_ml"], 3000)
        self.assertEqual(estimate["used_ml"], 450)
        self.assertEqual(estimate["remaining_ml"], 2550)
        self.assertEqual(estimate["remaining_percent"], 85)
        self.assertEqual(estimate["source"], "stored_estimate")

    def test_estimate_water_state_uses_custom_calibration_capacity(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.custom", "brand_profile": "custom_profile"},
            {"used_ml": 1250},
            {"custom_calibration": {"custom_profile": {"tank_ml": 2500}}},
        )

        self.assertEqual(estimate["total_ml"], 2500)
        self.assertEqual(estimate["remaining_ml"], 1250)
        self.assertEqual(estimate["remaining_percent"], 50)

    def test_estimate_water_state_returns_unknown_without_capacity(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.unknown"},
            {"used_ml": 99},
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
            {"used_ml": 0},
            {"custom_calibration": {}},
        )

        self.assertEqual(estimate["total_ml"], 3000)
        self.assertEqual(estimate["remaining_ml"], 3000)
        self.assertEqual(estimate["remaining_percent"], 100)
        self.assertEqual(estimate["source"], "stored_estimate")

    def test_estimate_water_state_model_database_via_brand_profile(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.living_room", "brand_profile": "dreame_x40_ultra"},
            {"used_ml": 900},
            {},
        )

        self.assertEqual(estimate["total_ml"], 4500)
        self.assertEqual(estimate["remaining_ml"], 3600)
        self.assertEqual(estimate["remaining_percent"], 80)

    def test_estimate_water_state_unknown_model_stays_unknown(self) -> None:
        estimate = estimate_water_state(
            {"vacuum_entity": "vacuum.robotic_vacuum_cleaner"},
            {"used_ml": 50},
            {},
        )

        self.assertIsNone(estimate["total_ml"])
        self.assertEqual(estimate["source"], "unknown_capacity")

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

    def test_vacuum_slug_is_stable_for_entity_ids(self) -> None:
        self.assertEqual(vacuum_slug("vacuum.Roborock S8 MaxV"), "vacuum_roborock_s8_maxv")


if __name__ == "__main__":
    unittest.main()
