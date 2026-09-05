"""Release-facing claims must match the fail-closed accounting contract."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readme_does_not_claim_an_unconfigured_area_to_time_fallback(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("0.8 m²/min", readme)
        self.assertIn("Unknown remains unknown.", readme)

    def test_release_version_is_consistent_across_all_public_surfaces(self):
        version = "5.5.0"
        self.assertIn(f'"version": "{version}"',
                      (ROOT / "custom_components/ha_vacuum_water_monitor/manifest.json").read_text(encoding="utf-8"))
        self.assertIn(f'VERSION = "{version}"',
                      (ROOT / "custom_components/ha_vacuum_water_monitor/const.py").read_text(encoding="utf-8"))
        self.assertIn(f'v{version}',
                      (ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn(f'"version": "{version}"',
                      (ROOT / "package.json").read_text(encoding="utf-8"))

    def test_sanitized_intake_names_required_context_and_private_data_to_remove(self):
        guide = (ROOT / "docs/diagnostics-and-calibration.md").read_text(encoding="utf-8")
        for field in ("integration version", "model/SKU", "firmware", "entity domain", "attributes"):
            self.assertIn(field, guide)
        for forbidden in ("tokens", "serials", "MAC/IP", "room names", "maps"):
            self.assertIn(forbidden, guide)

    def test_support_matrix_explains_all_evidence_tiers_and_partial_sessions(self):
        matrix = (ROOT / "docs/model-support-matrix.md").read_text(encoding="utf-8")
        for tier in ("Measured", "Manufacturer data", "Derived estimate", "Unknown"):
            self.assertIn(tier, matrix)
        for field in ("model", "integration", "settings", "area", "duration", "mop washes"):
            self.assertIn(field, matrix)
        self.assertIn("capacity is not consumption", matrix)
