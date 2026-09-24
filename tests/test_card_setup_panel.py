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
  out.unknown = card._buildSetupPanel(device, reports.unknown);
  out.duplicateOnly = card._buildSetupPanel(device, reports.duplicate);
  // A tank size chosen in Home Assistant wins in the card's own numbers.
  card._serverState = { settings: { device_options: { 'vacuum.robot': { capacity_ml: 3000 } } }, tank_states: { 'vacuum.robot': { initialized: true, used_ml: 1500 } } };
  card._config = { devices: [] };
  const data = card._calcDeviceData({ vacuum_entity: 'vacuum.robot', water_total_ml: 4000, config_provenance: { authored_fields: ['vacuum_entity', 'water_total_ml'] } });
  out.totalMl = data.totalMl; out.percent = data.percentRemaining;
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
    "fresh": {**BASE, "status": "action_needed", "checks": [
        {"id": "awaiting_refill", "severity": "warning", "fix": "confirm_full", "params": {"auto_refill": True}}]},
    "ok": {**BASE, "status": "ok", "calibration_samples": 2, "checks": []},
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

    def test_polish(self):
        html = self.out["freshPl"]
        self.assertIn("Czy zbiornik czystej wody jest teraz pełny?", html)
        self.assertIn("Tak, zbiornik jest pełny", html)
        self.assertIn("baza modeli", html)

    def test_ok_robot_collapses_to_everything_is_working(self):
        html = self.out["ok"]
        self.assertTrue(html.startswith("<details"))
        self.assertIn("Everything is working", html)
        self.assertIn("Calibrated on 2 empty tanks", html)
        self.assertNotIn("confirm-full", html)

    def test_unknown_tank_size_opens_the_editor(self):
        html = self.out["unknown"]
        self.assertIn('id="vwm-capacity-input"', html)
        self.assertIn('data-setup="save-capacity"', html)

    def test_duplicate_question_is_left_to_its_banner(self):
        self.assertNotIn("vwm-step", self.out["duplicateOnly"])

    def test_tank_size_option_wins_in_card_numbers(self):
        self.assertEqual(self.out["totalMl"], 3000)
        self.assertEqual(self.out["percent"], 50)

    def test_health_is_loaded_and_throttled(self):
        self.assertEqual(self.out["healthLoaded"], ["vacuum.robot"])
        self.assertTrue(self.out["throttled"])
        self.assertTrue(self.out["trailingScheduled"])
        self.assertEqual(self.out["calls"], ["ha_vacuum_water_monitor/health"])


if __name__ == "__main__":
    unittest.main()
