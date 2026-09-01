"""Behavior tests for the backend-owned vacuum profile catalog."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _load_profiles():
    path = PKG_DIR / "profiles.py"
    if not path.is_file():
        return None
    package = types.ModuleType("vwmprofiles")
    package.__path__ = [str(PKG_DIR)]
    sys.modules["vwmprofiles"] = package
    spec = importlib.util.spec_from_file_location("vwmprofiles.profiles", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vwmprofiles.profiles"] = module
    spec.loader.exec_module(module)
    return module


class ModelProfileTests(unittest.TestCase):
    """The catalog resolves registry identifiers without entity-name guesses."""

    def test_target_model_fixtures_resolve_to_canonical_tracked_capacity(self) -> None:
        # A wrong alias, capacity, or reservoir must break this table.
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        cases = (
            ({"model_id": "roborock.vacuum.a97"}, "roborock_s8_maxv_ultra", "dock_clean", 4000),
            ({"model_id": "a170"}, "roborock_qrevo_5ae", "dock_clean", 4000),
            ({"model_id": "a245"}, "roborock_qrevo_curv_2_flow", "dock_clean", 4000),
            ({"model": "Xiaomi Robot Vacuum H50 Pro"}, "xiaomi_h50_pro", "dock_clean", 4000),
            ({"model": "RV50 Pro Omni (1797)"}, "tapo_rv50_pro_omni", "dock_clean", 5000),
        )

        for device, key, reservoir, capacity in cases:
            with self.subTest(device=device):
                resolved = profiles.resolve_profile(device)
                self.assertEqual(resolved["profile_key"], key)
                self.assertEqual(resolved["tracked_reservoir"], reservoir)
                self.assertEqual(resolved["tracked_capacity_ml"], capacity)

    def test_locked_profile_override_precedes_registry_model(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        resolved = profiles.resolve_profile(
            {
                "profile_override": "dreame_x40_ultra",
                "profile_locked": True,
                "model_id": "a170",
            }
        )

        self.assertEqual(resolved["profile_key"], "dreame_x40_ultra")
        self.assertEqual(resolved["profile_source"], "locked_override")
        self.assertEqual(resolved["tracked_capacity_ml"], 4500)

    def test_models_without_native_water_telemetry_use_cross_model_estimator_seeds(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        cases = (
            ("1797", "tapo_rv50_pro_omni", 7.5, 6.0, 160),
            ("a170", "roborock_qrevo_5ae", 7.5, 6.0, 160),
            ("a245", "roborock_qrevo_curv_2_flow", 9.0, 7.2, 180),
        )

        for model_id, profile_key, area_rate, minute_rate, wash_ml in cases:
            with self.subTest(model_id=model_id):
                resolved = profiles.resolve_profile({"model_id": model_id})
                self.assertEqual(resolved["profile_key"], profile_key)
                self.assertEqual(resolved["capability"], "automatic_estimate")
                self.assertEqual(resolved["usage_ml_per_m2"]["default"], area_rate)
                self.assertEqual(
                    resolved["usage_ml_per_active_minute"]["default"], minute_rate
                )
                self.assertEqual(resolved["wash_volume_ml"], wash_ml)
                self.assertEqual(resolved["accounting_evidence"], "cross_model_estimate")
                self.assertGreaterEqual(resolved["uncertainty_percent"], 40)

    def test_vendor_profiles_select_rates_from_their_water_control_axis(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None

        for model in (
            "Ecovacs T20 Omni",
            "Dreame L20 Ultra",
            "iRobot Roomba Combo j7",
            "Samsung Jet Bot Combo",
            "Xiaomi Robot Vacuum X20 Pro",
        ):
            with self.subTest(model=model):
                resolved = profiles.resolve_profile({"model": model})
                self.assertEqual(resolved["rate_signal"], "mop_intensity")

    def test_tapo_matter_profile_uses_the_exposed_clean_mode_axis(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None

        resolved = profiles.resolve_profile({"model_id": "1797"})

        self.assertEqual(resolved["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(resolved["capability"], "automatic_estimate")
        self.assertEqual(resolved["rate_signal"], "cleaning_mode")

    def test_generic_profile_is_legacy_catalog_only_and_never_supplies_accounting(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None

        resolved = profiles.resolve_profile({"brand_profile": "generic"})

        self.assertEqual(resolved["profile_key"], "generic")
        self.assertEqual(resolved["capability"], "manual_only")
        self.assertEqual(resolved["usage_ml_per_m2"], {})
        self.assertIsNone(resolved["wash_volume_ml"])
        self.assertIsNone(resolved["tracked_capacity_ml"])
        self.assertEqual(
            profiles.CATALOG["generic"]["legacy_calibration"]["tank_ml"], 300
        )

    def test_invalid_catalog_record_fails_closed(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        invalid = {
            "profiles": {
                "bad": {
                    "identifiers": ["bad"],
                    "reservoirs_ml": {
                        "dock_clean": 10,
                        "dock_dirty": None,
                        "robot_clean": None,
                        "robot_dirty": None,
                    },
                    "tracked_reservoir": "dock_clean",
                    "tracked_capacity_ml": 0,
                    "accounting": {
                        "usage_ml_per_m2": {},
                        "wash_volume_ml": None,
                        "evidence": "not_published",
                    },
                    "capability": "manual_only",
                    "evidence": "manufacturer_specifications",
                    "sources": [],
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "profiles.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(profiles.CatalogValidationError, "tracked_capacity_ml"):
                profiles.load_catalog(path)

    def test_catalog_preserves_representative_legacy_accounting_and_ambiguity(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None

        catalog = profiles.CATALOG
        self.assertEqual(catalog["ecovacs_x2_omni"]["tracked_capacity_ml"], 4000)
        self.assertEqual(catalog["ecovacs_x2_omni"]["legacy_robot_tank_ml"], 180)
        self.assertIsNone(catalog["ecovacs_x2_omni"]["reservoirs_ml"]["robot_clean"])
        self.assertEqual(catalog["ecovacs_x2_omni"]["accounting"]["usage_ml_per_m2"], {"low": 4.5, "medium": 8, "high": 12.5})
        self.assertEqual(catalog["ecovacs_x2_omni"]["accounting"]["wash_volume_ml"], 170)
        self.assertEqual(catalog["dreame_l10s_ultra"]["accounting"]["usage_ml_per_m2"]["medium"], 7.5)
        self.assertEqual(catalog["dreame_l10s_ultra"]["accounting"]["wash_volume_ml"], 140)
        self.assertEqual(catalog["dreame_d10_plus"]["accounting"]["usage_ml_per_m2"], {"low": 2, "medium": 4, "high": 6})

    def test_catalog_legacy_payload_matches_executed_card_catalog(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        script = """
const fs = require('fs');
const source = fs.readFileSync('ha-vacuum-water-monitor.js', 'utf8');
const match = source.match(/const CALIBRATION_DATA = (\\{[\\s\\S]*?\\n\\});\\n\\n\\/\\/ Published/);
if (!match) process.exit(2);
process.stdout.write(JSON.stringify(Function('return (' + match[1] + ')')()));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=PKG_DIR.parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        card_catalog = json.loads(result.stdout)

        self.assertEqual(set(profiles.CATALOG), set(card_catalog))
        for key, legacy in card_catalog.items():
            with self.subTest(profile=key):
                self.assertEqual(profiles.CATALOG[key]["legacy_calibration"], legacy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
