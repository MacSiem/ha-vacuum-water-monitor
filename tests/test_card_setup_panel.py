"""5.8.0 card: the setup wizard and "Is everything working?" panel come from the server report."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r"""
const fs = require('fs'); const vm = require('vm'); const classes = {};
const elements = {};
global.HTMLElement = class { constructor() { this.tagName = 'HA-VACUUM-WATER-MONITOR'; } attachShadow() { this.shadowRoot = { querySelector(sel) { return elements[sel.replace('#', '')] || null; }, querySelectorAll() { return []; }, getElementById(id) { return elements[id] || null; } }; } dispatchEvent(e) { (global.toasts = global.toasts || []).push(e); } };
global.customElements = { get(n) { return classes[n]; }, define(n, c) { classes[n] = c; } };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} }; global.location = { pathname: '/' }; global.window = global;
global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
vm.runInThisContext(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js', 'utf8'));
const Card = classes['ha-vacuum-water-monitor'];
const reports = JSON.parse(process.argv[1]);
(async () => {
  const out = {};
  const calls = [];
  const card = new Card();
  card._render = () => {};
  card._hass = { states: {}, callWS: async (msg) => { calls.push(msg); if (msg.type.endsWith('/health')) return { robots: [reports.fresh] }; return { settings: { device_options: { 'vacuum.robot': { capacity_ml: 3000 } } } }; } };
  await card._refreshHealth(true);
  out.healthLoaded = Object.keys(card._health);
  const device = { vacuum_entity: 'vacuum.robot' };
  card._lang = 'pl';
  out.freshPl = card._buildSetupPanel(device, reports.fresh);
  card._lang = 'en';
  out.freshEn = card._buildSetupPanel(device, reports.fresh);
  out.ok = card._buildSetupPanel(device, reports.ok);
  out.partial = card._buildSetupPanel(device, reports.partial);
  for (const lang of ['en', 'pl']) {
    card._lang = lang;
    out['missingRate' + lang] = card._buildSetupPanel(device, reports.missingRate);
    out['missingLastError' + lang] = card._buildSetupPanel(device, {
      ...reports.partial, last_tank: { error_percent: null, accepted: false }
    });
    out['zeroLastError' + lang] = card._buildSetupPanel(device, {
      ...reports.ok, last_tank: { error_percent: 0, accepted: true }
    });
    out['rejectedLastError' + lang] = card._buildSetupPanel(device, {
      ...reports.partial, last_tank: { error_percent: 5, accepted: false, reason: 'legacy_unknown_reason' }
    });
    out['missingDiagnostics' + lang] = card._buildDiagnostics({
      calibrationHistory: [{ error_percent: null, accepted: false }]
    });
    out['zeroDiagnostics' + lang] = card._buildDiagnostics({
      calibrationHistory: [{ error_percent: 0, accepted: true }]
    });
  }
  card._lang = 'pl';
  out.okPl = card._buildSetupPanel(device, reports.ok);
  card._lang = 'en';
  out.unknown = card._buildSetupPanel(device, reports.unknown);
  out.notTrackedEn = card._buildSetupPanel(device, reports.notTracked);
  card._lang = 'pl';
  out.notTrackedPl = card._buildSetupPanel(device, reports.notTracked);
  card._lang = 'en';
  out.duplicateOnly = card._buildSetupPanel(device, reports.duplicate);
  // A tank size chosen in Home Assistant wins in the card's own numbers.
  card._serverState = { settings: { device_options: { 'vacuum.robot': { capacity_ml: 3000 } } }, tank_states: { 'vacuum.robot': { initialized: true, used_ml: 1500 } } };
  card._config = { devices: [] };
  const data = card._calcDeviceData({ vacuum_entity: 'vacuum.robot', water_total_ml: 4000, config_provenance: { authored_fields: ['vacuum_entity', 'water_total_ml'] } });
  out.totalMl = data.totalMl; out.percent = data.percentRemaining;
  out.waterTab = card._buildWaterTab({ vacuum_entity: 'vacuum.robot', brand_profile: 'roborock_s8_maxv_ultra' }, data);
  card._serverState.settings = { configured_devices: [{ vacuum_entity: 'vacuum.robot', water_total_ml: 3000 }] };
  const fromServer = card._calcDeviceData({ vacuum_entity: 'vacuum.robot', water_total_ml: 4000, config_provenance: { authored_fields: ['vacuum_entity', 'water_total_ml'] }, brand_profile: 'roborock_s8_maxv_ultra' });
  out.configuredTotalMl = fromServer.totalMl;
  out.configuredWaterTab = card._buildWaterTab({ vacuum_entity: 'vacuum.robot', brand_profile: 'roborock_s8_maxv_ultra' }, fromServer);
  out.invalidBatteries = [undefined, null, 'unknown', 'unavailable', '', ' ', -1, 101, '21foo', false, {}].map(value => card._buildBatteryBar(value));
  out.zeroBattery = card._buildBatteryBar(0);
  card._serverState = { settings: {}, tank_states: {} };
  card._discoveredVacuums = [{ entity_id: 'vacuum.robot', manufacturer: 'Roborock', model: 'a27', profile_key: 'roborock_s7_maxv', tracked_capacity_ml: null, capability: 'automatic_estimate', mop_system: 'pad' }];
  card._health['vacuum.robot'] = reports.unknown;
  const s7 = { vacuum_entity: 'vacuum.robot' };
  const unknownDock = card._calcDeviceData(s7);
  out.unknownDockStatus = card._getStatus(unknownDock, {}).label;
  out.emptyUnknownDockStatus = card._getStatus({ ...unknownDock, waterEmpty: true }, {}).label;
  out.unknownDockWater = card._buildWaterTab(s7, unknownDock);
  card._discoveredVacuums = [{ entity_id: 'vacuum.robot', manufacturer: 'QA synthetic', model: '1797', profile_key: null, tracked_capacity_ml: null, capability: 'unknown' }];
  card._health['vacuum.robot'] = reports.notTracked;
  card._lang = 'pl';
  out.unknownVendorPl = card._buildWaterTab(s7, card._calcDeviceData(s7));
  for (const lang of ['en', 'pl']) {
    card._lang = lang;
    out['noCapacity' + lang] = card._buildWaterTab(s7, card._calcDeviceData(s7));
    card._health['vacuum.robot'] = { ...reports.notTracked, capacity_ml: 1987, status: 'ok', checks: [] };
    for (const initialized of [false, true]) {
      card._serverState = { settings: { device_options: { 'vacuum.robot': { capacity_ml: 1987 } } },
        tank_states: { 'vacuum.robot': { initialized, used_ml: 0 } } };
      const saved = card._calcDeviceData(s7);
      out['savedCapacity' + lang + initialized] = card._buildWaterTab(s7, saved);
      out['savedPercent' + lang + initialized] = saved.percentRemaining;
    }
    card._serverState.settings.custom_calibration = { 'entity:vacuum.robot': { usage_ml_per_active_minute: { default: 2.3 } } };
    out['savedMinuteRate' + lang] = card._buildWaterTab(s7, card._calcDeviceData(s7));
    card._serverState = { settings: {}, tank_states: {} };
    card._health['vacuum.robot'] = reports.notTracked;
  }
  out.throttled = card._refreshHealth(false) === null;
  out.trailingScheduled = Boolean(card._healthTimer);
  clearTimeout(card._healthTimer);
  out.calls = calls.map(c => c.type);
  console.log(JSON.stringify(out));
})().catch(err => { console.error(err); process.exit(1); });
"""

BASE = {"vacuum_entity": "vacuum.robot", "name": "Robot S8", "model": "roborock.vacuum.a70", "capacity_ml": 4000,
        "capacity_source": "model", "model_capacity_ml": 4000, "uncertainty_percent": 20, "calibration_samples": 0,
        "can_calibrate": True, "refill_method": "dock_auto", "tracks_water": True}
REPORTS = {
    "missingRate": {**BASE, "status": "action_needed", "checks": [
        {"id": "missing_usage_rate", "severity": "warning", "fix": None, "params": {"reason": "missing_time_rate"}}]},
    "notTracked": {**BASE, "tracks_water": False, "capacity_ml": None, "model_capacity_ml": None,
                   "status": "ok", "checks": [{"id": "not_tracked", "severity": "info", "params": {}}]},
    "fresh": {**BASE, "status": "action_needed", "checks": [
        {"id": "awaiting_refill", "severity": "warning", "fix": "confirm_full", "params": {"auto_refill": True}}]},
    "ok": {**BASE, "status": "ok", "calibration_samples": 3, "checks": [], "typical_error_percent": 4.2,
           "supply": {"cleanings_left": 4, "days_left": 6.5},
           "last_tank": {"error_percent": 7.4, "accepted": True, "reason": None}},
    "partial": {**BASE, "status": "ok", "initialized": True, "checks": [{"id": "no_empty_signal", "severity": "info", "params": {}}],
                "last_tank": {"error_percent": 38.0, "accepted": False, "reason": "calibration_sample_outlier"}},
    "unknown": {**BASE, "capacity_ml": None, "capacity_source": None, "model_capacity_ml": None, "status": "action_needed",
                "checks": [{"id": "unknown_capacity", "severity": "error", "fix": "set_capacity", "params": {}}]},
    "duplicate": {**BASE, "status": "action_needed", "checks": [
        {"id": "possible_duplicate", "severity": "warning", "fix": "resolve_duplicate", "params": {"target": "vacuum.s8"}}]},
}


class CardSetupPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["node", "-e", SCRIPT, json.dumps(REPORTS)], cwd=ROOT, capture_output=True, text=True,
                                timeout=60, check=False)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_a_new_robot_gets_one_question_with_the_facts(self):
        html = self.out["freshEn"]
        self.assertIn("Set up water tracking: Robot S8", html)
        self.assertIn("Is the clean-water tank full now?", html)
        self.assertIn('data-setup="confirm-full"', html)
        self.assertIn("4,000 ml", html)
        self.assertIn("model database", html)
        self.assertIn("±20%", html)
        self.assertIn("tracking starts by itself after the next refill at the dock", html)

    def test_missing_rate_explains_calibration_without_a_refill_button(self):
        for lang, title, hint in [("en", "Missing water-use rate", "Confirming a full tank cannot supply this rate"),
                                  ("pl", "Brak tempa zużycia wody", "Potwierdzenie pełnego zbiornika nie ustali tego tempa")]:
            with self.subTest(language=lang):
                html = self.out["missingRate" + lang]
                self.assertIn(title, html)
                self.assertIn(hint, html)
                self.assertNotIn('data-setup="confirm-full"', html)
                self.assertNotIn("Signals are ready", html)

    def test_polish(self):
        html = self.out["freshPl"]
        self.assertIn("Czy zbiornik czystej wody jest teraz pełny?", html)
        self.assertIn("Tak, zbiornik jest pełny", html)
        self.assertIn("baza modeli", html)

    def test_ok_robot_collapses_to_signals_ready(self):
        html = self.out["ok"]
        self.assertTrue(html.startswith("<details"))
        self.assertIn("Signals are ready", html)
        self.assertIn("Calibrated on 3 empty tanks", html)
        self.assertIn("Enough for about 4 cleanings (about 6.5 days)", html)
        self.assertIn("Last empty tank: the estimate was +7.4% off, then learned", html)
        self.assertIn("Typical error of recent tanks: \u00b14.2%", html)
        self.assertIn("Wystarczy na ok. 4 sprzątania (ok. 6.5 dni)", self.out["okPl"])

    def test_partial_fill_and_tank_empty_button(self):
        html = self.out["partial"]
        self.assertIn("for example a partly filled tank", html)
        self.assertIn('data-setup="mark-empty"', html)
        self.assertNotIn("confirm-full", html)

    def test_missing_last_tank_error_is_not_reported_as_zero(self):
        for lang, label in [("en", "Last empty tank:"), ("pl", "Ostatni pusty zbiornik:")]:
            with self.subTest(language=lang):
                self.assertNotIn(label, self.out["missingLastError" + lang])
                self.assertIn(label, self.out["zeroLastError" + lang])
                self.assertIn("0%", self.out["zeroLastError" + lang])

    def test_missing_diagnostic_error_is_unknown_and_real_zero_is_kept(self):
        for lang in ("en", "pl"):
            with self.subTest(language=lang):
                self.assertNotIn("0%", self.out["missingDiagnostics" + lang])
                self.assertIn("?", self.out["missingDiagnostics" + lang])
                self.assertIn("0%", self.out["zeroDiagnostics" + lang])

    def test_rejected_tank_with_unknown_reason_never_claims_learning(self):
        for lang, learned, skipped in [("en", "then learned", "not learned"),
                                       ("pl", "potem nauczony", "nienauczony")]:
            with self.subTest(language=lang):
                html = self.out["rejectedLastError" + lang]
                self.assertNotIn(learned, html)
                self.assertIn(skipped, html)

    def test_unknown_tank_size_opens_the_editor(self):
        html = self.out["unknown"]
        self.assertIn('id="vwm-capacity-input"', html)
        self.assertIn('data-setup="save-capacity"', html)

    def test_untracked_robot_does_not_claim_ready_signals(self):
        for key, ready, pending in [("notTrackedEn", "Signals are ready", "Water tracking is not configured"),
                                    ("notTrackedPl", "Sygnały są gotowe", "Śledzenie wody nie jest skonfigurowane")]:
            with self.subTest(language=key):
                html = self.out[key]
                self.assertNotIn(ready, html)
                self.assertIn(pending, html)
                self.assertNotIn("✅", html)
                self.assertIn('id="vwm-capacity-input"', html)

    def test_duplicate_question_is_left_to_its_banner(self):
        self.assertNotIn("vwm-step", self.out["duplicateOnly"])

    def test_missing_or_invalid_battery_is_not_a_zero_percent_measurement(self):
        self.assertTrue(all(html == "" for html in self.out["invalidBatteries"]))
        self.assertIn("0%", self.out["zeroBattery"])

    def test_known_mopping_robot_with_unknown_tank_keeps_unknown_water(self):
        self.assertEqual(self.out["unknownDockStatus"], "Unknown")
        self.assertNotIn("This device doesn't track water levels", self.out["unknownDockWater"])
        self.assertNotIn('class="battery-bar"', self.out["unknownDockWater"])

    def test_verified_empty_signal_wins_over_unknown_capacity(self):
        self.assertEqual(self.out["emptyUnknownDockStatus"], "EMPTY")

    def test_polish_unknown_device_fallbacks_are_localized(self):
        html = self.out["unknownVendorPl"]
        self.assertIn("Nieznany model", html)
        self.assertIn("nieznany", html)
        for text in ["Unknown model", "No estimate for this model yet", "This device doesn't track water levels", "<b>unknown</b>"]:
            self.assertNotIn(text, html)

    def test_saved_unknown_model_capacity_is_not_requested_again(self):
        for lang, prompt, saved, estimate in [
            ('en', 'set the tank capacity', 'Tank capacity saved.', 'No built-in consumption estimate for this model.'),
            ('pl', 'ustaw pojemność', 'Pojemność zbiornika zapisana.', 'Brak wbudowanego oszacowania zużycia dla tego modelu.'),
        ]:
            self.assertIn(prompt, self.out['noCapacity' + lang].lower())
            for initialized in (False, True):
                with self.subTest(language=lang, initialized=initialized):
                    key = lang + str(initialized).lower()
                    html = self.out['savedCapacity' + key]
                    self.assertIn('1,987 ml', html)
                    self.assertNotIn(prompt, html.lower())
                    self.assertIn(saved, html)
                    self.assertIn(estimate, html)
                    self.assertEqual(self.out['savedPercent' + key], 100 if initialized else None)
            self.assertNotIn(prompt, self.out['savedMinuteRate' + lang].lower())
            self.assertIn(estimate, self.out['savedMinuteRate' + lang])

    def test_tank_size_option_wins_in_card_numbers(self):
        self.assertEqual(self.out["totalMl"], 3000)
        self.assertEqual(self.out["percent"], 50)

    def test_calibration_panel_distinguishes_tracked_capacity_from_model_reference(self):
        html = self.out["configuredWaterTab"]
        self.assertEqual(self.out["configuredTotalMl"], 3000)
        self.assertIn("Tracked tank: <b>3,000 ml</b>", html)
        self.assertIn("Model reference: <b>4,000 ml</b>", html)

    def test_health_is_loaded_and_throttled(self):
        self.assertEqual(self.out["healthLoaded"], ["vacuum.robot"])
        self.assertTrue(self.out["throttled"])
        self.assertTrue(self.out["trailingScheduled"])
        self.assertEqual(self.out["calls"], ["ha_vacuum_water_monitor/health"])

    def test_successful_setup_checks_do_not_claim_verified_usage_signals(self):
        for key, label, old in [('ok', 'Setup checks passed', 'Signals are ready'),
                                 ('okPl', 'Sprawdzenia konfiguracji zakończone', 'Sygnały są gotowe')]:
            with self.subTest(language=key):
                self.assertIn(label, self.out[key])
                self.assertNotIn(old, self.out[key])


if __name__ == "__main__":
    unittest.main()
