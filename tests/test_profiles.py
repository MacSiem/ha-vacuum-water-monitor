"""Regression tests for the evidence-gated model catalogue."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).parents[1] / "custom_components/ha_vacuum_water_monitor/profiles.py"
SPEC = importlib.util.spec_from_file_location("vwm_profiles", PATH)
assert SPEC and SPEC.loader
profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles)


class ModelProfileTests(unittest.TestCase):
    def test_every_record_has_provenance_and_no_shipped_rate(self):
        for record in profiles.CATALOG.values():
            self.assertTrue(record["provenance"])
            self.assertEqual(record["accounting"]["usage_ml_per_m2"], {})
            self.assertEqual(record["accounting"]["usage_ml_per_active_minute"], {})
            self.assertIsNone(record["accounting"]["wash_volume_ml"])

    def test_capacity_needs_calibration(self):
        resolved = profiles.resolve_profile({"model_id": "a97"})
        self.assertEqual(resolved["tracked_capacity_ml"], 4000)
        self.assertEqual(resolved["capability"], "calibration_required")
        self.assertEqual(resolved["usage_ml_per_m2"], {})

    def test_unknown_model_fails_closed(self):
        resolved = profiles.resolve_profile({"model": "unlisted model"})
        self.assertEqual(resolved["capability"], "unknown")
        self.assertIsNone(resolved["tracked_capacity_ml"])

    def test_malformed_rate_is_rejected(self):
        payload = json.loads(PATH.with_name("model_profiles.json").read_text())
        payload["profiles"]["roborock_s8_maxv_ultra"]["accounting"]["usage_ml_per_m2"] = {"default": 1}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as handle:
            json.dump(payload, handle); handle.flush()
            with self.assertRaises(profiles.CatalogValidationError):
                profiles.load_catalog(handle.name)

    def test_required_metadata_and_invalid_dates_are_rejected(self):
        for field,value in [('last_verified','2026-99-55'),('regional_skus',None),('sample_count',-1),('model_ids',None),('unsupported_unknowns',None)]:
            with self.subTest(field=field):
                payload=json.loads(PATH.with_name('model_profiles.json').read_text())
                payload['profiles']['roborock_s8_maxv_ultra'][field]=value
                with tempfile.NamedTemporaryFile(mode='w') as h:
                    json.dump(payload,h);h.flush()
                    with self.assertRaises(profiles.CatalogValidationError):profiles.load_catalog(h.name)

    def test_matter_product_id_is_not_global_across_manufacturers(self):
        r=profiles.resolve_profile({'manufacturer':'Unrelated manufacturer','model_id':'1797'})
        self.assertEqual(r['capability'],'unknown')
