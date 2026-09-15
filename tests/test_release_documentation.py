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
        version = "5.7.0-beta.1"
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


class ShippedArtefactProvenanceTests(unittest.TestCase):
    """A published build must be reproducible from published inputs.

    5.6.0 shipped a consumption snapshot compiled from an uncommitted working
    tree ("...-dirty") of the data repository, while the published dataset was
    still an older revision. Nobody could rebuild the shipped artefact.
    """

    SNAPSHOT = ROOT / "custom_components/ha_vacuum_water_monitor/consumption_snapshot.json"

    def _snapshot(self):
        import json
        return json.loads(self.SNAPSHOT.read_text(encoding="utf-8"))

    def test_snapshot_is_built_from_a_committed_revision(self):
        revision = self._snapshot().get("source_revision")
        self.assertIsInstance(revision, str)
        self.assertNotIn("-dirty", revision,
                         "snapshot was compiled from an uncommitted data-repo tree")
        self.assertNotEqual(revision, "uncommitted")
        self.assertRegex(revision, r"^[0-9a-f]{40}$",
                         "source_revision must be a full commit sha")

    def test_snapshot_declares_the_supported_contract_and_its_payload_hash(self):
        snapshot = self._snapshot()
        self.assertEqual(snapshot.get("schema_version"), 2)
        self.assertRegex(str(snapshot.get("source_payload_sha256")), r"^[0-9a-f]{64}$")
        self.assertIsInstance(snapshot.get("dataset_version"), str)
        self.assertTrue(snapshot["dataset_version"])
        self.assertIsInstance(snapshot.get("profiles"), list)
        self.assertIsInstance(snapshot.get("estimates"), list)

    def test_bundled_card_is_identical_to_the_repository_card(self):
        """HACS serves the bundled copy; a drifted copy ships a stale card."""
        source = (ROOT / "ha-vacuum-water-monitor.js").read_bytes()
        bundled = (ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js").read_bytes()
        self.assertEqual(source, bundled,
                         "root card and bundled www copy have diverged")
