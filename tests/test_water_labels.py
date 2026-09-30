"""Polish primary water labels render in both distributed card copies."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class WaterLabelTests(unittest.TestCase):
    def test_polish_and_english_primary_labels(self):
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
  const device = {vacuum_entity:'vacuum.demo', profile_key:'tapo_rv50_pro_omni'};
  const data = {totalMl:5000, remainingL:4, usedMl:1000, percentRemaining:80, initialized:true, lastReset:new Date().toISOString(), charge:null, profileKey:'tapo_rv50_pro_omni', integrationAdapter:'matter'};
  for (const [lang,labels] of [['pl',['Pozostało','Zużyto','Ostatnie dolanie','Diagnostyka']],['en',['Remaining','Used','Last refill','Diagnostics']]]) {
    card._lang = lang;
    const html = card._buildWaterTab(device,data);
    const container = dom.window.document.createElement('div');
    container.innerHTML = html;
    for (const label of labels) assert.ok(container.textContent.includes(label), `${file} ${lang}: missing ${label}`);
    if (lang === 'pl') for (const label of ['Remaining','Last refill','Diagnostics']) assert.ok(!container.textContent.includes(label), `${file}: English label ${label}`);
  }
  dom.window.close();
}
"""
        result = subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
