"""Visible saved-but-not-refreshed recovery in the actual card."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BindingRefreshUiTests(unittest.TestCase):
    def test_saved_measurement_and_profile_can_retry_refresh_without_duplicate_save(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 for(const lang of ['en','pl'])for(const kind of ['measurement','measurement_minimal','reprofile','settings']){
  const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
  dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
  const id='vacuum.robot',card=dom.window.document.createElement('ha-vacuum-water-monitor'),calls=[];
  card.setConfig({vacuum_entity:id,water_total_ml:4000});
  const settings={sharing_intro_choice:'not_now'};
  const hass={language:lang,locale:{language:lang},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},
   user:{is_admin:true},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{
    calls.push(m.type);
    if(m.type.endsWith('/save_measurement'))return kind==='measurement_minimal'?{saved:true,bindings_refreshed:true}:{saved:true,sample_count:3,calibration:{coefficient:10},bindings_refreshed:false};
    if(m.type.endsWith('/reprofile'))return {settings,vacuums:[],balance_links:{},bindings_refreshed:false};
    if(m.type.endsWith('/refresh_bindings'))return {bindings_refreshed:true};
    if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{automatic_sessions:[{ts:123,area:10}]}}};
    if(m.type.endsWith('/list_vacuums'))return {vacuums:[],balance_links:{}};
    if(m.type.endsWith('/set_settings')||m.type.endsWith('/set_robot_link')){
      settings.robot_links=m.patch?.robot_links || {...settings.robot_links,[m.vacuum_entity]:m.target};
      return {settings,bindings_refreshed:false};
    }
    throw Error(m.type);
   }};
  card._serverReady=true;card._serverLoadedAt=Date.now();
  card._serverState={settings,tank_states:{[id]:{automatic_sessions:[{ts:123,area:10}]}}};
  card._discoveredVacuums=[{entity_id:id,name:'Robot',identity_group:id},
   {entity_id:'vacuum.copy',name:'Copy',identity_group:'vacuum.copy',possible_duplicate_of:id}];
  card._refreshHealth=()=>null;card._activeTab='settings';card.hass=hass;
  dom.window.document.body.append(card);card._render();
  let sr=card.shadowRoot;
  if(kind.startsWith('measurement')){
   sr.getElementById('cal-observed').value='100';sr.getElementById('cal-resolution').value='5';
   sr.getElementById('cal-boundaries').checked=true;sr.getElementById('cal-uninterrupted').checked=true;
   const button=sr.getElementById('cal-save');assert(button&&!button.disabled);button.click();
  } else if(kind==='reprofile') {
   const button=sr.querySelector('[onclick*="_reprofileDevice"]');assert(button);button.click();
  } else {
   const button=sr.querySelector('[data-dup="vacuum.copy"][data-target="distinct"]');assert(button);button.click();
  }
  await new Promise(r=>setTimeout(r,20));sr=card.shadowRoot;
  const status=kind.startsWith('measurement')?sr.getElementById('cal-local-status'):
   kind==='reprofile'?sr.getElementById('vwm-reprofile-status'):sr.querySelector('[data-vwm-refresh-status]');
  assert(status);assert.match(status.textContent,lang==='pl'?/zapisano/i:/saved/i);
  if(kind==='measurement_minimal'){
    assert(!/could not save|nie udało się zapisać/i.test(status.textContent));
    assert.equal(calls.filter(x=>x.endsWith('/save_measurement')).length,1);
    dom.window.close();continue;
  }
  assert.match(status.textContent,lang==='pl'?/odśwież/i:/refresh/i);
  const retry=sr.querySelector('[data-vwm-refresh-retry]');assert(retry&&!retry.disabled);retry.click();
  await new Promise(r=>setTimeout(r,20));
  assert.equal(calls.filter(x=>x.endsWith('/refresh_bindings')).length,1);
  assert.equal(calls.filter(x=>x.endsWith('/save_measurement')).length,kind==='measurement'?1:0);
  assert.equal(calls.filter(x=>x.endsWith('/reprofile')).length,kind==='reprofile'?1:0);
  assert.match(card.shadowRoot.textContent,lang==='pl'?/odświeżono/i:/refreshed/i);
  dom.window.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
