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

    def test_capacity_model_gets_a_labelled_estimate(self):
        """Decision 2026-09-15: a recognised model always gets a labelled estimate."""
        resolved = profiles.resolve_profile({"model_id": "a97"})
        self.assertEqual(resolved["tracked_capacity_ml"], 4000)
        self.assertEqual(resolved["capability"], "automatic_estimate")
        self.assertEqual(resolved["accounting_evidence"], "labeled_estimate")
        self.assertIn(resolved["estimate_basis"], profiles.estimation.ESTIMATE_BASES)
        self.assertTrue(resolved["usage_ml_per_m2"])

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

    def test_registry_manufacturer_forms_still_scope_to_the_known_vendor(self):
        """5.5.0 compared the registry manufacturer for whole-string equality.

        Home Assistant reports vendor-formatted values, so "Beijing Roborock
        Technology Co., Ltd." and "TP-Link Corporation Limited" scoped the
        catalogue to nothing and discarded an exact model_id match. Reported for
        the Qrevo Curv 2 Flow X (roborock.vacuum.a245) and the Tapo RV50 Pro
        Omni (Matter 1797).
        """
        cases = [
            ("Roborock", "roborock.vacuum.a245", "roborock_qrevo_curv_2_flow"),
            ("Roborock Technology Co., Ltd", "roborock.vacuum.a245", "roborock_qrevo_curv_2_flow"),
            ("Beijing Roborock Technology Co., Ltd.", "roborock.vacuum.a245", "roborock_qrevo_curv_2_flow"),
            ("Roborock", "roborock.vacuum.a170", "roborock_qrevo_5ae"),
            ("TP-Link", "1797", "tapo_rv50_pro_omni"),
            ("TP-Link Corporation Limited", "1797", "tapo_rv50_pro_omni"),
            ("Tapo", "1797", "tapo_rv50_pro_omni"),
        ]
        for manufacturer, model_id, expected in cases:
            with self.subTest(manufacturer=manufacturer, model_id=model_id):
                resolved = profiles.resolve_profile(
                    {"manufacturer": manufacturer, "model_id": model_id})
                self.assertEqual(resolved["profile_key"], expected)
                self.assertEqual(resolved["profile_source"], "model_id")

    def test_unrecognised_manufacturer_never_widens_back_to_the_full_catalogue(self):
        """A stated vendor scopes the search even when it is unknown."""
        for manufacturer in ("Unrelated manufacturer", "ACME Robotics GmbH", "Generic"):
            with self.subTest(manufacturer=manufacturer):
                resolved = profiles.resolve_profile(
                    {"manufacturer": manufacturer, "model_id": "1797"})
                self.assertIsNone(resolved["profile_key"])
                self.assertEqual(resolved["capability"], "unknown")

    def test_manufacturer_token_match_does_not_cross_brands(self):
        """Token matching must not turn one vendor's string into another's."""
        self.assertEqual(profiles._canonical_manufacturer("dreame", {"dreame", "roborock"}), "dreame")
        self.assertEqual(profiles._canonical_manufacturer("shenzhen_dreame_innovation", {"dreame"}), "dreame")
        self.assertEqual(profiles._canonical_manufacturer("dreamer_labs", {"dreame"}), "")
        self.assertEqual(profiles._canonical_manufacturer("predreame", {"dreame"}), "")
        self.assertEqual(profiles._canonical_manufacturer("", {"dreame"}), "")
