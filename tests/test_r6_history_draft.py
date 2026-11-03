"""Uncommitted history input survives ordinary updates but not revocation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HistoryDraftTests(unittest.TestCase):
    def test_shared_event_does_not_move_focus_between_five_cards(self):
        source = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body><button id="outside">outside</button></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},handlers=[],calls=[];let settings={sharing_intro_choice:'not_now',warning_threshold:20,critical_threshold:10};
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},connection:{subscribeMessage:async cb=>{handlers.push(cb);return ()=>{}}},callWS:async m=>{
 calls.push(m.type);if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[{vacuum_entity:id,status:settings.warning_threshold===97?'warning':'ok',checks:[]}]};throw Error(m.type)}};
 const cards=[];for(const variant of ['tile','compact','full','full','compact']){const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant,default_tab:'history',show_support:false});card.hass=hass;w.document.body.append(card);cards.push(card)}await pause(180);
 assert.equal(handlers.length,5);const sr=cards[2].shadowRoot;let input=sr.querySelector('#hist-duration');input.value='6m';input.focus();input.setSelectionRange(1,1);assert.equal(sr.activeElement,input);
 settings={...settings,warning_threshold:97,critical_threshold:90};for(const cb of handlers)cb({data:{settings_changed:true,authorized_vacuums:[id]}});await pause(200);
 input=sr.querySelector('#hist-duration');assert.equal(input.value,'6m');assert.equal(sr.activeElement,input,'shared event/health refresh retains keyboard target');assert.equal(input.selectionStart,1);assert.equal(input.selectionEnd,1);input.setRangeText('x',input.selectionStart,input.selectionEnd,'end');assert.equal(input.value,'6xm');
 w.document.querySelector('#outside').focus();for(const cb of handlers)cb({data:{settings_changed:true,authorized_vacuums:[id]}});await pause(180);assert.equal(w.document.activeElement.id,'outside','ordinary update cannot steal focus after blur');assert.equal(sr.querySelector('#hist-duration').value,'6xm');assert(!calls.some(x=>x.endsWith('/set_settings')));
 for(const card of cards)card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_edit_during_save_is_not_erased(self):
        source = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];let release;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{
 if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings')){calls.push(m);return new Promise(resolve=>{release=()=>resolve({settings:{sharing_intro_choice:'not_now',...m.patch},bindings_refreshed:true})})}throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant:'full',default_tab:'history',show_support:false});card.hass=hass;w.document.body.append(card);await pause(100);
 const sr=card.shadowRoot;sr.querySelector('#hist-area').value='7';sr.querySelector('#hist-water').value='55';sr.querySelector('#hist-duration').value='9m';sr.querySelector('#hist-log-btn').click();await pause(20);assert.equal(calls.length,1);assert(release);
 sr.querySelector('#hist-duration').value='10m';release();await pause(100);assert.equal(sr.querySelector('#hist-duration').value,'10m');assert.equal(calls.length,1);assert.equal(calls[0].patch.sessions[id].length,1);
 card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_settings_event_keeps_draft_and_revocation_discards_it(self):
        source = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];let emit,target=id,settings={sharing_intro_choice:'not_now',warning_threshold:20,critical_threshold:10};
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},
  connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m.type);
  if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:{[target]:{initialized:true,used_ml:1000}}};
  if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:target,name:'Robot',identity_group:target,tracked_capacity_ml:4000}],balance_links:{}};
  if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes},'vacuum.other':{water:yes,settings:yes,measurements:yes}}};
  if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 hass.states['vacuum.other']={entity_id:'vacuum.other',state:'docked',attributes:{friendly_name:'Other'}};
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
 // A registry refresh switches from A to B: A's draft must not follow it.
 sr.querySelector('#hist-area').value='7';sr.querySelector('#hist-duration').value='9m';target='vacuum.other';emit({data:{registry_changed:true,authorized_vacuums:[id,target]}});await pause(150);assert.equal(sr.querySelector('#hist-area').value,'');assert.equal(sr.querySelector('#hist-duration').value,'');
 card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
