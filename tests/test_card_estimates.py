"""Card parity with backend uncertainty and privacy of the opt-in share payload."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/ha_vacuum_water_monitor"
_spec = importlib.util.spec_from_file_location("vwm_card_estimation", PKG / "estimation.py")
estimation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(estimation)

CASES = [
    ["owner_device", []], ["class_prior", [0.2]], ["generic_prior", [0.1, 0.12]],
    ["class_prior", [0.29, 0.28, 0.3]], ["family_transfer", [0.1, 0.4, -0.2, 0.3, 0.05]],
    ["unknown_basis", []], ["class_prior", [0.0, 0.9, -0.9, 0.5]],
]

SCRIPT = r"""
const fs = require('fs'); const vm = require('vm'); const classes = {};
global.HTMLElement = class { constructor() { this.tagName = 'HA-VACUUM-WATER-MONITOR'; } attachShadow() { this.shadowRoot = { querySelector() { return null; }, querySelectorAll() { return []; }, getElementById() { return null; } }; } };
global.customElements = { get(n) { return classes[n]; }, define(n, c) { classes[n] = c; } };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} }; global.location = { pathname: '/' }; global.window = global; global.CustomEvent = class {};
vm.runInThisContext(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js', 'utf8'));
const Card = classes['ha-vacuum-water-monitor']; const card = new Card();
card._serverState = { settings: { calibration_sharing: { enabled: true } }, tank_states: {} };
const cases = JSON.parse(process.argv[1]);
const device = { vacuum_entity: 'vacuum.living_room_chappie', name: 'Chappie Salon', device_id: 'abc123', area_sensor: 'sensor.chappie_surface' };
const data = { profileKey: 'roborock_qrevo_curv_2_flow', mopSystem: 'roller', integrationAdapter: 'roborock', estimateBasis: 'class_prior',
  trackedReservoir: 'dock_clean', totalMl: 4000, calibrationFactor: 1.2345, calibrationSamples: 2,
  calibrationHistory: [{ ts: 1757955764335, predicted_ml: 3012.4, target_ml: 4000, error_percent: -24.69, accepted: true, reason: null, factor_before: 1 }],
  areaCleaned: '45.5', lastCleanStart: '2026-09-15T17:42:44Z' };
const payload = card._buildCalibrationSharePayload(device, data);
const html = card._buildCalibrationSharingSection(device, data);
const url = card._calibrationShareUrl(payload);
console.log(JSON.stringify({ u: cases.map(([b, f]) => card._estimateUncertainty(b, f)), payload, html, url }));
"""


class CardEstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", "-e", SCRIPT, json.dumps(CASES)], cwd=ROOT, check=True,
                             capture_output=True, text=True)
        cls.result = json.loads(out.stdout.strip().splitlines()[-1])

    def test_card_uncertainty_matches_backend(self):
        expected = [estimation.uncertainty_percent(basis, factors) for basis, factors in CASES]
        self.assertEqual(self.result["u"], expected)

    def test_share_payload_contains_no_identifiers_or_timestamps(self):
        payload = self.result["payload"]
        text = json.dumps(payload)
        for forbidden in ("vacuum.", "sensor.", "Chappie", "chappie", "abc123", "living_room", "ts", "2026-", "1757955764335",
                          "45.5", "factor_before", "reason"):
            self.assertNotIn(forbidden, text if forbidden != "ts" else list(payload["tanks"][0].keys()))
        self.assertEqual(payload["schema"], "vwm-calibration-share/1")
        self.assertEqual(payload["tanks"][0], {"predicted_ml": 3010, "target_ml": 4000, "error_percent": -24.7, "accepted": True})
        self.assertEqual(set(payload), {"schema", "integration_version", "profile_key", "mop_system", "integration_adapter",
                                        "estimate_basis", "tracked_reservoir", "tracked_capacity_ml", "calibration_factor",
                                        "calibrated_tanks", "tanks"})

    def test_sharing_requires_explicit_opt_in_and_shows_the_exact_payload(self):
        self.assertIn('id="vwm-share-optin" checked', self.result["html"])
        self.assertIn("GitHub username is visible", self.result["html"])
        self.assertIn("roborock_qrevo_curv_2_flow", self.result["html"])
        self.assertTrue(self.result["url"].startswith("https://github.com/MacSiem/ha-vacuum-water-monitor/issues/new?template=calibration_share.yml"))
        self.assertNotIn("chappie", self.result["url"].lower())

    def test_sharing_is_off_by_default(self):
        source = (PKG / "www/ha-vacuum-water-monitor.js").read_text()
        self.assertIn("sharing.enabled === true", source)
        self.assertNotIn("callWS({ type: `${VWM_DOMAIN}/share", source)
        self.assertNotIn("fetch(", source.split("_buildCalibrationSharePayload", 1)[1].split("_buildSettingsTab", 1)[0])


if __name__ == "__main__":
    unittest.main()
