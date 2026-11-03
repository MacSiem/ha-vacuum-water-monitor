"""Uncommitted history input survives ordinary updates but not revocation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HistoryDraftTests(unittest.TestCase):
    def test_settings_event_keeps_draft_and_revocation_discards_it(self):
        source = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];let emit,settings={sharing_intro_choice:'not_now',warning_threshold:20,critical_threshold:10};
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},
  connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m.type);
  if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:{[id]:{initialized:true,used_ml:1000}}};
  if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
  if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
  if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant:'full',default_tab:'history',show_support:false});card.hass=hass;w.document.body.append(card);await pause(150);
 const sr=card.shadowRoot;sr.querySelector('#hist-area').value='7';sr.querySelector('#hist-water').value='55';let duration=sr.querySelector('#hist-duration');duration.value='9m';duration.focus();duration.setSelectionRange(1,1);
 assert.equal(sr.activeElement,duration);settings={...settings,warning_threshold:96,critical_threshold:90};emit({data:{settings_changed:true,authorized_vacuums:[id]}});await pause(150);
 duration=sr.querySelector('#hist-duration');assert.equal(sr.querySelector('#hist-area').value,'7');assert.equal(sr.querySelector('#hist-water').value,'55');assert.equal(duration.value,'9m');assert.equal(sr.activeElement,duration);assert.equal(duration.selectionStart,1);assert.equal(duration.selectionEnd,1);assert(!calls.some(x=>x.endsWith('/set_settings')),'event does not save the draft');
 // The user may move focus elsewhere without saving; another ordinary event
 // must not erase the pending inputs merely because no field is active.
 const outside=w.document.createElement('button');w.document.body.append(outside);outside.focus();assert.equal(sr.activeElement,null);emit({data:{settings_changed:true,authorized_vacuums:[id]}});await pause(150);assert.equal(sr.querySelector('#hist-area').value,'7');assert.equal(sr.querySelector('#hist-water').value,'55');assert.equal(sr.querySelector('#hist-duration').value,'9m');assert.equal(w.document.activeElement,outside);
 emit({access_revoked:true});await pause(30);assert.match(sr.textContent,/Access denied/);assert.equal(sr.querySelector('#hist-duration'),null);
 // Real re-grant causes a fresh authorized state event; the prior sensitive
 // unsaved draft must not return to the reconstructed form.
 card.hass={...hass,user:{...hass.user}};await pause(150);
 assert.equal(sr.querySelector('#hist-area').value,'');assert.equal(sr.querySelector('#hist-water').value,'');assert.equal(sr.querySelector('#hist-duration').value,'');
 card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
