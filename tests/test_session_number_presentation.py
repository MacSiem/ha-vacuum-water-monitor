"""A real History read exposed binary float tails in recorded water amounts."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SessionNumberPresentationTests(unittest.TestCase):
    def test_session_water_is_readable_without_changing_records(self):
        script = r"""
const { JSDOM } = require('jsdom');
const fs = require('fs');
const assert = require('node:assert/strict');
for (const file of ['ha-vacuum-water-monitor.js', 'custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']) {
  const dom = new JSDOM('<!doctype html>', {url:'http://localhost/', runScripts:'outside-only'});
  dom.window.matchMedia = () => ({matches:false, addEventListener(){}, removeEventListener(){}});
  dom.window.eval(fs.readFileSync(file,'utf8'));
  const card = dom.window.document.createElement('ha-vacuum-water-monitor');
  card._config = {show_dock_status:false};
  const device = {vacuum_entity:'vacuum.demo'};
  const sessions = [905.1500000000001, 674.0500000000001, 146.92999999999984, 821.5000000000002].map((water, i) => ({ts:Date.now()-i*3600000, water, area:20, duration:60, evidence:'labeled_estimate'}));
  const before = JSON.stringify(sessions);
  card._getSessionsFromStorage = () => sessions;
  const data = {totalMl:3000, remainingL:3, usedMl:0, percentRemaining:100, initialized:true, vacState:'cleaning', isCleaning:true, areaCleaned:20, sessionMl:905.1500000000001};
  for (const lang of ['en','pl']) {
    card._lang = lang;
    const history = dom.window.document.createElement('div');
    history.innerHTML = card._buildHistoryTab(device, data);
    for (const amount of ['905.15 ml','674.05 ml','146.93 ml','821.5 ml']) {
      assert.ok(history.textContent.includes(amount), `${file} ${lang}: missing readable ${amount}`);
    }
    for (const record of sessions) assert.ok(!history.textContent.includes(String(record.water)), 'binary float tail must not reach History');
    assert.ok(history.textContent.includes('~905.15 ml'), 'estimate marker must remain');
    const current = history.querySelector('.current-session-card');
    assert.ok(current.textContent.includes('905.15 ml'), 'active session uses the same readable format');
    const water = dom.window.document.createElement('div');
    water.innerHTML = card._buildWaterTab(device, data);
    assert.ok(water.textContent.includes('905.15 ml'), 'last session uses the same readable format');
    assert.ok(!water.textContent.includes(String(data.sessionMl)), 'last session must not leak binary precision');
    assert.equal(data.sessionMl, 905.1500000000001, 'formatting must not round stored input');
    const zero = {...data, sessionMl:0};
    water.innerHTML = card._buildWaterTab(device, zero);
    assert.ok(water.textContent.includes('0 ml'), 'known zero remains zero in last session');
    const unknown = {...data, sessionMl:null};
    water.innerHTML = card._buildWaterTab(device, unknown);
    assert.ok(!water.textContent.includes(lang==='pl'?'Ostatnia sesja':'Last session'), 'unknown must not become zero');
    assert.equal(JSON.stringify(sessions), before, 'rendering must preserve original accounting records');
  }
  dom.window.close();
}
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
