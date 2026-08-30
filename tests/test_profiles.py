"""Behavior tests for the backend-owned vacuum profile catalog."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
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

    def test_matter_capacity_without_explicit_rates_is_manual_only(self) -> None:
        profiles = _load_profiles()
        self.assertIsNotNone(profiles, "profiles module must exist")
        assert profiles is not None
        resolved = profiles.resolve_profile({"model_id": "1797"})

        self.assertEqual(resolved["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(resolved["capability"], "manual_only")
        self.assertIsNone(resolved["wash_volume_ml"])
        self.assertEqual(resolved["usage_ml_per_m2"], {})

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
