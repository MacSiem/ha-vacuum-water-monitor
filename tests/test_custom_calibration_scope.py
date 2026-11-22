"""Calibration actions target the same robot as the visible card."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CustomCalibrationScopeTests(unittest.TestCase):
    def test_two_cards_fallback_and_selected_device_save_clear_without_shared_default(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const ids=['vacuum.a','vacuum.b'], calls=[];
 let settings={configured_devices:[],user_devices:[],custom_calibration:{default:{wash_volume_ml:77}},sharing_intro_choice:'not_now'};
 const vacuums=ids.map(id=>({entity_id:id,name:id,identity_group:id,balance_owner:id}));
 const hass={language:'en',locale:{language:'en'},user:{is_admin:true},states:Object.fromEntries(ids.map(id=>[id,{entity_id:id,state:'docked',attributes:{friendly_name:id}}])),
  connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{
   calls.push(structuredClone(m));
   if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:{}};
   if(m.type.endsWith('/list_vacuums'))return {vacuums:structuredClone(vacuums),balance_links:{}};
   if(m.type.endsWith('/health'))return {robots:[]};
   if(m.type.endsWith('/set_settings')){
    for(const [key,value] of Object.entries(m.patch.custom_calibration||{})){
     if(value===null)delete settings.custom_calibration[key];
     else settings.custom_calibration[key]={...(settings.custom_calibration[key]||{}),...value};
    }
    return {settings:structuredClone(settings),bindings_refreshed:true};
   }
   if(m.type.endsWith('/reprofile'))return {settings:structuredClone(settings),vacuums:structuredClone(vacuums),balance_links:{},bindings_refreshed:true};
   throw Error(m.type);
  }};
 function card(config,idx){
  dom.window.localStorage.setItem('ha-tools-vacuum-water-monitor-settings',JSON.stringify({_activeDeviceIdx:idx,_activeTab:'settings'}));
  const c=dom.window.document.createElement('ha-vacuum-water-monitor');c.setConfig({...config,default_tab:'settings'});
  c._serverReady=true;c._serverLoadedAt=Date.now();c._serverState={settings:structuredClone(settings),tank_states:{}};
  c._discoveredVacuums=structuredClone(vacuums);c._refreshHealth=()=>null;c.hass=hass;
  dom.window.document.body.append(c);c._render();return c;
 }
 async function save(c,value){const sr=c.shadowRoot;const input=sr.getElementById('vwm-custom-tank');assert(input);input.value=String(value);
  const button=sr.getElementById('vwm-custom-save');assert(button);button.click();await new Promise(r=>setTimeout(r,25));}
 async function clear(c){const btn=c.shadowRoot.querySelector('[onclick*="_clearCustomCalibration"]');assert(btn);btn.click();await new Promise(r=>setTimeout(r,25));}
 const a=card({vacuum_entity:ids[0]},5),b=card({vacuum_entity:ids[1]},5);
 assert.match(a.shadowRoot.textContent,/vacuum\.a/i);assert.match(b.shadowRoot.textContent,/vacuum\.b/i);
 await save(b,4321);await save(a,4567);
 assert.equal(settings.custom_calibration['entity:vacuum.a'].tracked_capacity_ml,4567);
 assert.equal(settings.custom_calibration['entity:vacuum.b'].tracked_capacity_ml,4321);
 assert.deepEqual(settings.custom_calibration.default,{wash_volume_ml:77});
 await clear(a);assert(!settings.custom_calibration['entity:vacuum.a']);
 assert.equal(settings.custom_calibration['entity:vacuum.b'].tracked_capacity_ml,4321);
 assert.deepEqual(settings.custom_calibration.default,{wash_volume_ml:77});
 const multi=card({devices:ids.map(vacuum_entity=>({vacuum_entity}))},1);
 assert.match(multi.shadowRoot.querySelector('.device-name').textContent,/vacuum\.b/i);
 await save(multi,3333);assert.equal(settings.custom_calibration['entity:vacuum.b'].tracked_capacity_ml,3333);
 const profile=multi.shadowRoot.querySelector('[onclick*="_reprofileDevice"]');assert(profile);profile.click();
 await new Promise(r=>setTimeout(r,25));assert.equal(calls.filter(m=>m.type.endsWith('/reprofile')).at(-1).vacuum_entity,ids[1]);
 // No robot is available after an event; Clear must not touch the shared prior.
 vacuums.length=0;multi._config.devices=[];multi._discoveredVacuums=[];multi._serverState.settings.configured_devices=[];
 multi._serverState.settings.user_devices=[];multi._lastHtml='';multi._render();
 const before=calls.length;await multi._clearCustomCalibration();assert.equal(calls.length,before);
 assert.deepEqual(settings.custom_calibration.default,{wash_volume_ml:77});
 dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
