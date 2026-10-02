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
  card._config = {show_dock_status:true};
  const device = {vacuum_entity:'vacuum.demo', dock_clean_water_sensor:'sensor.clean_water', profile_key:'tapo_rv50_pro_omni'};
  const data = {totalMl:5000, remainingL:4, usedMl:1000, percentRemaining:80, initialized:true, vacState:'cleaning', isCleaning:true, lastResetSource:'card', accountingSource:'active_time', accountingRate:7, estimatedM2PerActiveMinute:2, estimateBasis:'generic_prior', uncertaintyPercent:65, calibrationSamples:1, lastReset:new Date().toISOString(), charge:null, profileKey:'tapo_rv50_pro_omni', integrationAdapter:'matter'};
  for (const [lang,labels] of [['pl',['Pozostało','Zużyto','Ostatnie dolanie','Diagnostyka','Sprzątanie','Metoda zużycia','Poziom dowodów','Adapter integracji','Profil','Rozliczanie','Przelicznik czasu pracy','Szacowana dokładność','Kalibracja robota','Stan stacji','Zbiornik czystej wody','Kalibracja','przycisk Dolane']],['en',['Remaining','Used','Last refill','Diagnostics','Cleaning','Consumption method','Evidence tier','Integration adapter','Profile','Accounting','Active-time conversion','Estimated accuracy','Device calibration','Dock Status','Clean Water Box','Calibration','Refilled button']]]) {
    card._lang = lang;
    for (const code of ['__proto__','constructor','matter','active_time']) assert.equal(card._waterText(code), code);
    const html = card._buildWaterTab(device,data);
    const container = dom.window.document.createElement('div');
    container.innerHTML = html;
    for (const label of labels) assert.ok(container.textContent.includes(label), `${file} ${lang}: missing ${label}`);
    if (lang === 'pl') for (const label of ['Remaining','Last refill','Diagnostics','Cleaning','Consumption method','Evidence tier','Integration adapter','Active-time conversion','Estimated accuracy','Device calibration']) assert.ok(!container.textContent.includes(label), `${file}: English label ${label}`);
  }

  // Reproduce the live case: the server counter advances while the full
  // reservoir balance remains incomplete. Never present it as a full total.
  const tracked = {vacuum_entity:'vacuum.demo', water_total_ml:3000};
  card._hass = {states:{'vacuum.demo':{state:'cleaning',attributes:{}}}};
  card._serverState = {settings:{configured_devices:[tracked]},tank_states:{
    'vacuum.demo':{initialized:true,used_ml:512.91,accounting_incomplete:true,last_reset_iso:'2026-10-01T00:00:00Z'}
  }};
  for (const [lang,label,guidance] of [
    ['en','Recorded estimate (incomplete)','Consumption from available signals is still recorded.'],
    ['pl','Zapisane oszacowanie (niepełne)','Zużycie z dostępnych sygnałów jest nadal zapisywane.']
  ]) {
    card._lang = lang;
    const partial = card._calcDeviceData(tracked);
    assert.equal(partial.usedMl,null,'incomplete total must stay unknown');
    assert.equal(partial.remainingL,null,'remaining water must stay unknown');
    assert.equal(partial.partialUsedMl,512.91,'preserve the recorded partial counter');
    const view = dom.window.document.createElement('div');
    view.innerHTML = card._buildWaterTab(tracked,partial);
    assert.ok(view.textContent.includes(label),`${lang}: label the partial estimate`);
    assert.ok(view.textContent.includes('0.51 L'),`${lang}: render the recorded amount`);
    assert.ok(view.textContent.includes(guidance),`${lang}: distinguish recording from unknown balance`);
    card._serverState.tank_states['vacuum.demo'].used_ml = 520;
    assert.equal(card._calcDeviceData(tracked).partialUsedMl,520,'next observation must update');
    card._serverState.tank_states['vacuum.demo'].used_ml = 512.91;
  }
  const stored = card._serverState.tank_states['vacuum.demo'];
  stored.initialized=false; delete stored.last_reset_iso;
  assert.equal(card._calcDeviceData(tracked).partialUsedMl,null,'uninitialized zero is not evidence');
  stored.initialized=true;
  for (const invalid of [null,-1,Infinity,'512.91']) {
    stored.used_ml=invalid;
    assert.equal(card._calcDeviceData(tracked).partialUsedMl,null,'invalid counter must not render');
  }
  stored.used_ml=512.91; stored.accounting_incomplete=false;
  const complete=card._calcDeviceData(tracked);
  assert.equal(complete.partialUsedMl,null);
  assert.equal(complete.usedMl,512.91,'complete accounting must stay unchanged');

  dom.window.close();
}
"""
        result = subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
