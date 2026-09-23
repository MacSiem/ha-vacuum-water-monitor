"""5.7.0-beta.2 card: refill options, diagnostics and backend parity."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/ha_vacuum_water_monitor"
_spec = importlib.util.spec_from_file_location("vwm_card_refill_estimation", PKG / "estimation.py")
estimation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(estimation)

WINDOW_CASES = [
    {"calibration_log_factors": [0.3, 0.31, 0.29], "calibration_samples": 0, "calibration_factor": 1},
    {"calibration_log_factors": [0.3, 0.31], "calibration_samples": 2, "calibration_factor": 1.36},
    {"calibration_log_factors": [0.1, 0.2, 0.3], "calibration_samples": 2, "calibration_factor": 1.1},
    {"calibration_log_factors": [0.1, 0.2, 0.3]},
    {"calibration_samples": 2, "calibration_factor": 1.2},
]

SCRIPT = r"""
const fs = require('fs'); const vm = require('vm'); const classes = {};
const elements = {};
const element = (id, props = {}) => (elements[id] = { id, value: '', checked: false, disabled: false, textContent: '', style: {}, options: [], add(o) { this.options.push(o); }, ...props });
global.HTMLElement = class { constructor() { this.tagName = 'HA-VACUUM-WATER-MONITOR'; } attachShadow() { this.shadowRoot = { querySelector(sel) { return elements[sel.replace('#', '')] || null; }, querySelectorAll() { return []; }, getElementById(id) { return elements[id] || null; } }; } };
global.customElements = { get(n) { return classes[n]; }, define(n, c) { classes[n] = c; } };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} }; global.location = { pathname: '/' }; global.window = global; global.CustomEvent = class {};
global.Option = class { constructor(text, value) { this.text = text; this.value = value; } };
vm.runInThisContext(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js', 'utf8'));
const Card = classes['ha-vacuum-water-monitor'];
(async () => {
  const out = {};
  const calls = [];
  const card = new Card();
  card._hass = {
    states: {
      'input_button.dock_refilled': { entity_id: 'input_button.dock_refilled', state: '2026-09-01T10:00:00+00:00', attributes: { friendly_name: 'Dock refilled' } },
      'button.zigbee_refill': { entity_id: 'button.zigbee_refill', state: 'unknown', attributes: { friendly_name: 'Zigbee refill' } },
      'binary_sensor.dock_lid': { entity_id: 'binary_sensor.dock_lid', state: 'off', attributes: { friendly_name: 'Dock lid', device_class: 'opening' } },
    },
    callWS: async (msg) => { calls.push(msg); return { settings: { refill_config: JSON.parse(JSON.stringify(card._refillConfig)), user_devices: JSON.parse(JSON.stringify(card._userDevices)), refill_settings: { 'vacuum.robot': { auto_refill: msg.auto_refill, button_entity: msg.button_entity } } } }; },
    callApi: async (method, path) => { calls.push({ method, path }); return {}; },
  };
  card._serverState = { settings: { refill_settings: {} }, tank_states: {} };
  card._refillConfig = { robot: { sensorEntity: 'binary_sensor.dock_lid', sensorAutoId: 'vwm_refill_robot_sensor' } };
  card._userDevices = [{ vacuum_entity: 'vacuum.robot', reset_door_sensor: 'binary_sensor.dock_lid' }];
  card._saveServerSettings = async (patch) => { calls.push({ saveSettings: patch }); return { ok: true }; };
  card._saveUserDevices = () => calls.push({ saveUserDevices: JSON.parse(JSON.stringify(card._userDevices)) });
  card._render = () => {};
  const dock = { vacuum_entity: 'vacuum.robot', dock_error_sensor: 'sensor.robot_dock_error', refill_on_clear: true, refill_on_clear_inferred: true };
  const data = { refillHistory: [{ ts: Date.now() - 2 * 3600000, source: 'dock_cleared', used_before_ml: 3800 }] };
  out.dockHtml = card._buildRefillMethodCard(dock, data);
  out.robotOnlyHtml = card._buildRefillMethodCard({ vacuum_entity: 'vacuum.robot' }, {});
  card._serverState.settings.refill_settings = { 'vacuum.robot': { auto_refill: false, button_entity: 'button.zigbee_refill' } };
  out.storedHtml = card._buildRefillMethodCard(dock, {});
  element('vwm-refill-status'); element('vwm-refill-auto', { checked: false });
  element('vwm-refill-button', { value: 'input_button.dock_refilled' }); element('vwm-refill-lid', { value: '' });
  out.saved = await card._saveRefillChoices(dock);
  out.legacyAfterSave = card._refillConfig.robot;
  await card._removeLegacyRefillAutomations(dock);
  out.legacyAfterRemove = card._refillConfig.robot;
  out.calls = calls;
  out.windows = JSON.parse(process.argv[1]).map(state => card._storedCalibrationWindow(state));
  const diag = card._buildDiagnostics({ estimateBasis: 'owner_device', calibrationHistory: [{ error_percent: -60.5, accepted: false, reason: 'calibration_sample_unconfirmed' }],
    calibrationPending: true, intensityUnmapped: 'smart_mode', bridgedGaps: 2, refillHistory: [{ ts: Date.now(), source: 'lid' }] });
  out.diagnostics = diag;
  out.source = fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js', 'utf8').includes("callApi('POST', `config/automation/config/");
  console.log(JSON.stringify(out));
})().catch(err => { console.error(err); process.exit(1); });
"""


class CardRefillOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["node", "-e", SCRIPT, json.dumps(WINDOW_CASES)], cwd=ROOT, check=True,
                                capture_output=True, text=True)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_all_five_refill_options_are_offered(self):
        html = self.out["dockHtml"]
        for label in ("Refilled button in this card", "Automatic from the dock", "Dashboard or physical button",
                      "Tank lid or door sensor", "Automation, script or NFC tag"):
            self.assertIn(label, html)
        self.assertIn("ha_vacuum_water_monitor.mark_refilled", html)
        self.assertIn("entity_id: vacuum.robot", html)
        self.assertIn('id="vwm-refill-auto" checked', html)
        self.assertIn("button.zigbee_refill", html, "button entities are offered, not only input_button")
        self.assertIn('value="binary_sensor.dock_lid" selected', html, "a pre-5.7 lid binding is shown")
        self.assertIn("Recent refills", html)
        self.assertIn("dock reported refilled", html)
        self.assertIn("automation.vwm_refill_robot_sensor", html)

    def test_automatic_refill_needs_a_dock_signal(self):
        html = self.out["robotOnlyHtml"]
        self.assertIn("not available for this robot", html)
        self.assertRegex(html, r'id="vwm-refill-auto"\s+disabled>')

    def test_stored_choices_win(self):
        html = self.out["storedHtml"]
        self.assertNotIn('id="vwm-refill-auto" checked', html)
        self.assertIn('value="button.zigbee_refill" selected', html)

    def test_save_sends_the_choices_and_retires_legacy_bindings(self):
        self.assertTrue(self.out["saved"])
        ws = [c for c in self.out["calls"] if c.get("type") == "ha_vacuum_water_monitor/set_refill_settings"]
        self.assertEqual(ws, [{"type": "ha_vacuum_water_monitor/set_refill_settings", "vacuum_entity": "vacuum.robot",
                               "auto_refill": False, "button_entity": "input_button.dock_refilled", "lid_entity": None}])
        self.assertNotIn("sensorEntity", self.out["legacyAfterSave"])
        cleared = [c for c in self.out["calls"] if "saveUserDevices" in c]
        self.assertTrue(cleared and cleared[-1]["saveUserDevices"][0]["reset_door_sensor"] is None)

    def test_old_generated_automation_can_be_removed(self):
        self.assertIn({"method": "DELETE", "path": "config/automation/config/vwm_refill_robot_sensor"}, self.out["calls"])
        self.assertNotIn("sensorAutoId", self.out["legacyAfterRemove"])

    def test_card_no_longer_generates_refill_automations(self):
        self.assertFalse(self.out["source"])

    def test_stale_calibration_window_parity(self):
        expected = [estimation._stored_window(case) for case in WINDOW_CASES]
        self.assertEqual(self.out["windows"], expected)

    def test_diagnostics_explain_pending_unmapped_and_refills(self):
        diag = self.out["diagnostics"]
        self.assertIn("waiting for the next tank", diag)
        self.assertIn("An unusual tank result waits for the next tank to confirm it", diag)
        self.assertIn("smart_mode", diag)
        self.assertIn("Signal gaps bridged", diag)
        self.assertIn("tank lid", diag)


if __name__ == "__main__":
    unittest.main()
