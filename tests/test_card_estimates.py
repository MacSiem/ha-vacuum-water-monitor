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
    ["unknown_basis", []], ["class_prior", [0.0, 0.9, -0.9, 0.5]], ["generic_prior", [0.3]],
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
const missingPayload = card._buildCalibrationSharePayload(device, { ...data,
  totalMl: null, calibrationFactor: null,
  calibrationHistory: [{ predicted_ml: null, target_ml: null, error_percent: null, accepted: false }]
});
const zeroPayload = card._buildCalibrationSharePayload(device, { ...data,
  calibrationHistory: [{ predicted_ml: 0, target_ml: 4000, error_percent: 0, accepted: true }]
});
const html = card._buildCalibrationSharingSection(device, data);
const url = card._calibrationShareUrl(payload);
const guidance = (uncertaintyPercent) => card._buildAccountingGuidance({
  capability: 'automatic_estimate', initialized: true, accountingSource: 'area', accountingRate: 6,
  stateReason: null, uncertaintyPercent, calibrationSamples: 0,
});
card._hass = { states: {} };
card._serverState.tank_states['vacuum.measured'] = {last_water_volume_ml:1250,last_accounting_source:'real_sensor'};
const measuredData = card._calcDeviceData({vacuum_entity:'vacuum.measured',profile_key:'roborock_s8_maxv_ultra',
  water_volume_sensor:'sensor.ml',estimate_basis:'owner_device',uncertainty_percent:20});
console.log(JSON.stringify({ u: cases.map(([b, f]) => card._estimateUncertainty(b, f)), payload, missingPayload, zeroPayload, html, url,
  measuredData,
  guidanceNull: guidance(null), guidance20: guidance(20),
  learnedGuidance: card._buildAccountingGuidance({initialized:true,capability:'automatic_estimate',
    uncertaintyPercent:5,uncertaintyKind:'calibration_spread',calibrationSamples:3,calibrationFactor:1.2}),
  fewGuidance: card._buildAccountingGuidance({initialized:true,capability:'automatic_estimate',
    uncertaintyPercent:50,uncertaintyKind:'prior_band',calibrationSamples:2,calibrationFactor:1.2}) }));
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

    def test_missing_uncertainty_is_not_rendered_as_zero_percent(self):
        self.assertNotIn("0%", self.result["guidanceNull"])
        self.assertIn("20%", self.result["guidance20"])

    def test_learned_spread_is_not_presented_as_verified_physical_accuracy(self):
        self.assertIn("between tank cycles", self.result["learnedGuidance"])
        self.assertIn("Physical accuracy is not verified", self.result["learnedGuidance"])
        self.assertIn("prior band", self.result["fewGuidance"])

    def test_measured_card_volume_does_not_show_prior_uncertainty(self):
        measured = self.result["measuredData"]
        self.assertEqual(measured["remainingL"], 1.25)
        self.assertIsNone(measured["estimateBasis"])
        self.assertIsNone(measured["uncertaintyPercent"])

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

    def test_share_payload_preserves_missing_measurements_and_genuine_zero(self):
        payload = self.result["missingPayload"]
        self.assertIsNone(payload["tracked_capacity_ml"])
        self.assertIsNone(payload["calibration_factor"])
        self.assertEqual(payload["tanks"][0], {
            "predicted_ml": None, "target_ml": None, "error_percent": None, "accepted": False
        })
        zero = self.result["zeroPayload"]["tanks"][0]
        self.assertEqual(zero["predicted_ml"], 0)
        self.assertEqual(zero["error_percent"], 0)

    def test_sharing_requires_explicit_opt_in_and_shows_the_exact_payload(self):
        self.assertIn('id="vwm-share-optin" checked', self.result["html"])
        self.assertIn("GitHub username is visible", self.result["html"])
        self.assertIn("roborock_qrevo_curv_2_flow", self.result["html"])
        self.assertTrue(self.result["url"].startswith("https://github.com/MacSiem/ha-vacuum-water-monitor/issues/new?template=calibration_share.yml"))
        self.assertNotIn("chappie", self.result["url"].lower())

    def test_share_link_prefills_form_and_plain_issue_without_ticking_consent(self):
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(self.result["url"]).query)
        self.assertEqual(json.loads(query["summary"][0]), self.result["payload"])
        body = query["body"][0]
        self.assertIn(json.dumps(self.result["payload"], separators=(",", ":")), body)
        self.assertIn("- [ ] I reviewed the summary", body)
        self.assertNotIn("[x]", body.lower())

    def test_sharing_is_off_by_default(self):
        source = (PKG / "www/ha-vacuum-water-monitor.js").read_text()
        self.assertIn("sharing.enabled === true", source)
        self.assertNotIn("callWS({ type: `${VWM_DOMAIN}/share", source)
        self.assertNotIn("fetch(", source.split("_buildCalibrationSharePayload", 1)[1].split("_buildSettingsTab", 1)[0])


FOOTER_SCRIPT = SCRIPT.split("const cases =")[0] + r"""
card.setConfig({type:'custom:ha-vacuum-water-monitor', language:'en', show_dock_status:false});
card._hass={states:{},locale:{language:'en'}};
const device=card._decorateLegacyProfile({vacuum_entity:'vacuum.robot', profile_key:'roborock_s7_maxv', brand_profile:'roborock_s7_maxv', capability:'automatic_estimate', config_provenance:{authored_fields:['vacuum_entity']}});
card._discoveredVacuums=[device];
card._serverState={settings:{custom_calibration:{'entity:vacuum.robot':{usage_ml_per_m2:{standard:10},calibration_scope:'floor_only'}}},tank_states:{'vacuum.robot':{initialized:true,used_ml:40}}};
const data=card._calcDeviceData(device);data.totalMl=1234;
const configured=card._buildWaterTab(device,data);
const authored=card._decorateLegacyProfile({...device,usage_ml_per_m2:{standard:12},config_provenance:{authored_fields:['vacuum_entity','usage_ml_per_m2']}});
const explicit=card._buildWaterTab(authored,{...data});
card._serverState.settings.custom_calibration={'entity:vacuum.robot':{tracked_capacity_ml:1234}};
const prior=card._buildWaterTab(device,card._calcDeviceData(device));
console.log(JSON.stringify({configured,explicit,prior}));
"""

class EffectiveRatePresentationTests(unittest.TestCase):
    def test_sparse_locked_model_keeps_all_metadata_from_selected_profile(self):
        script = SCRIPT.split("const cases =")[0] + r"""
card._hass={states:{}};
card._discoveredVacuums=[{entity_id:'vacuum.robot',profile_key:'roborock_s8_maxv_ultra',
 estimate_basis:'owner_device',estimate_sources:[{url:'https://wrong.example'}],mop_system:'pad',
 tracked_reservoir:'dock_clean',tracked_capacity_ml:4000,uncertainty_percent:20,
 calibration_scope:'wrong_scope',water_anchor_reservoir:'dock_clean',refill_on_clear:true,
 sources:['wrong'],provenance:[{url:'https://wrong.example'}],signals:{area_sensor:'sensor.area'}}];
const sparse={vacuum_entity:'vacuum.robot',brand_profile:'tapo_rv50_pro_omni',profile_locked:true,
 config_provenance:{authored_fields:['vacuum_entity','brand_profile','profile_locked']}};
const merged=card._withBackendDescriptor(card._decorateLegacyProfile(sparse));
const data=card._calcDeviceData(merged);
const authored=card._withBackendDescriptor(card._decorateLegacyProfile({...sparse,
 calibration_scope:'floor_only',usage_ml_per_m2:{default:12},
 config_provenance:{authored_fields:[...sparse.config_provenance.authored_fields,'calibration_scope','usage_ml_per_m2']}}));
const legacy=card._withBackendDescriptor(card._decorateLegacyProfile({...sparse,brand_profile:'roborock_s7_maxv',
 tracked_capacity_ml:1,usage_ml_per_m2:{default:1},intensity_factor:{default:1},calibration_scope:'old_generated'}));
console.log(JSON.stringify({merged,data,authored,legacy}));
"""
        out = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        expected = __import__('runpy').run_path(str(PKG / 'profiles.py'))['resolve_profile']({
            'brand_profile': 'tapo_rv50_pro_omni', 'profile_locked': True})
        for field in ('profile_key', 'estimate_basis', 'estimate_sources', 'mop_system',
                      'tracked_reservoir', 'tracked_capacity_ml', 'calibration_scope',
                      'sources', 'provenance', 'water_anchor_reservoir', 'refill_on_clear'):
            self.assertEqual(result['merged'].get(field), expected.get(field), field)
        self.assertEqual(result['data']['estimateBasis'], 'class_prior')
        self.assertEqual(result['data']['uncertaintyPercent'], 50)
        self.assertEqual(result['data']['mopSystem'], 'rotating_pads')
        self.assertEqual(result['authored']['calibration_scope'], 'floor_only')
        self.assertEqual(result['authored']['usage_ml_per_m2'], {'default': 12})
        self.assertEqual(result['merged']['area_sensor'], 'sensor.area')
        legacy = __import__('runpy').run_path(str(PKG / 'profiles.py'))['resolve_profile']({
            'brand_profile': 'roborock_s7_maxv', 'profile_locked': True})
        for field in ('tracked_capacity_ml', 'usage_ml_per_m2', 'intensity_factor', 'calibration_scope'):
            self.assertEqual(result['legacy'].get(field), legacy.get(field), field)

    def test_water_footer_matches_saved_rate_and_preserves_model_reference_without_rate(self):
        out = subprocess.run(["node", "-e", FOOTER_SCRIPT], cwd=ROOT, check=True, capture_output=True, text=True)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertIn("10 ml/m²", result["configured"])
        self.assertIn("~123 m²", result["configured"])
        self.assertNotIn("6 ml/m²", result["configured"])
        self.assertNotIn("±50%", result["configured"])
        self.assertIn("12 ml/m²", result["explicit"])
        self.assertNotIn("10 ml/m²", result["explicit"])
        self.assertIn("6 ml/m²", result["prior"])


if __name__ == "__main__":
    unittest.main()
