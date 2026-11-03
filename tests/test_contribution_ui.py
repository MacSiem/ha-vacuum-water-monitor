"""Real card controls for optional measurement contribution."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContributionUiTests(unittest.TestCase):
    def test_export_failure_is_readable_and_consent_follows_exact_preview(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 for(const lang of ['en','pl']) {
  const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
  dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
  const card=dom.window.document.createElement('ha-vacuum-water-monitor'), id='vacuum.robot';
  card.setConfig({vacuum_entity:id,water_total_ml:4000});
  const sample={id:'local.1',device_id:id,confirmed:true,area_m2:10,observed_ml:100,purpose:'training'};
  let calls=[];
  const sample2={...sample,id:'local.2',observed_ml:110};
  const settings={sharing_intro_choice:'not_now',local_measurements:{[id]:[sample,sample2]}};
  const hass={language:lang,locale:{language:lang},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},user:{is_admin:true},
   connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m);if(m.type.endsWith('/contribution_preview'))
    return {kind:'confirmed_measurement_contribution',publication_consent:false,runtime_eligible:false,samples:[{measured_ml:m.sample_ids[0]==='local.2'?110:100}]};
    throw Error(m.type)}};
  card._serverReady=true;card._serverLoadedAt=Date.now();card._serverState={settings,tank_states:{}};
  card._refreshHealth=()=>null;card._activeTab='settings';card.hass=hass;dom.window.document.body.append(card);card._render();
  const sr=card.shadowRoot, enable=sr.getElementById('cal-share-enabled'),preview=sr.getElementById('cal-preview');
  assert(enable && preview);assert.equal(enable.checked,false);assert.equal(preview.disabled,true);
  enable.checked=true;enable.dispatchEvent(new dom.window.Event('change'));assert.equal(preview.disabled,false);
  preview.click();await new Promise(r=>setTimeout(r,10));
  const consent=sr.getElementById('cal-share-consent'),download=sr.getElementById('cal-download'),box=sr.getElementById('cal-export-preview');
  assert.equal(download.disabled,true);assert.equal(consent.disabled,false);assert.match(box.value,/110/);
  consent.checked=true;consent.dispatchEvent(new dom.window.Event('change'));assert.equal(download.disabled,false);
  assert.equal(JSON.parse(box.value).publication_consent,true);
  let downloaded=null, clicked=0;
  dom.window.Blob=class {constructor(parts){downloaded=parts.join('')}};
  dom.window.URL.createObjectURL=()=> 'blob:synthetic';
  dom.window.URL.revokeObjectURL=()=>{};
  dom.window.HTMLAnchorElement.prototype.click=function(){clicked++};
  const accepted=box.value;download.click();assert.equal(downloaded,accepted);assert.equal(clicked,1);
  const select=sr.getElementById('cal-share-sample');select.value='local.1';
  select.dispatchEvent(new dom.window.Event('change'));assert.equal(download.disabled,true);assert.equal(consent.checked,false);
  preview.click();await new Promise(r=>setTimeout(r,10));consent.checked=true;consent.dispatchEvent(new dom.window.Event('change'));
  enable.checked=false;enable.dispatchEvent(new dom.window.Event('change'));assert.equal(download.disabled,true);assert.equal(consent.checked,false);
  enable.checked=true;enable.dispatchEvent(new dom.window.Event('change'));preview.click();await new Promise(r=>setTimeout(r,10));
  consent.checked=true;consent.dispatchEvent(new dom.window.Event('change'));
  dom.window.URL.createObjectURL=()=>{throw Error('synthetic browser download failure')};
  download.click();await new Promise(r=>setTimeout(r,0));
  const message=sr.getElementById('cal-export-status').textContent;
  assert.match(message, lang==='pl' ? /nie udało się|nie można/i : /could not|failed/i);
  assert.equal(calls.filter(x=>x.type.endsWith('/contribution_preview')).length,3);
  dom.window.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
