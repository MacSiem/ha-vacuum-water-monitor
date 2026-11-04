"""HA picker preview cannot mutate a real robot from keyboard activation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PickerPreviewTests(unittest.TestCase):
    def test_same_card_exits_ha_edit_and_picker_without_clearing_external_inert(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];let emit,allowed=true;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{
 calls.push(m.type);if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access')&&!allowed)throw Object.assign(new Error('denied'),{code:'unauthorized'});if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/reset_tank'))return {state:{initialized:true,used_ml:0}};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant:'compact'});card.preview=true;card.hass=hass;w.document.body.append(card);await pause(120);
 assert(card.inert);card.shadowRoot.querySelector('.refill-btn').click();await pause(20);assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,0);
 // HA updates the same element when edit mode ends, without a reload.
 card.preview=false;await pause(100);assert(!card.inert);card.shadowRoot.querySelector('.refill-btn').click();await pause(30);assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,1);
 // The same instance can also move from picker shadow DOM into a dashboard.
 const picker=w.document.createElement('hui-card-picker'),root=picker.attachShadow({mode:'open'}),wrapper=w.document.createElement('div');root.append(wrapper);w.document.body.append(picker);wrapper.append(card);await pause(100);assert(card.inert);card.preview=false;card.shadowRoot.querySelector('.refill-btn').click();await pause(20);assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,1);
 w.document.body.append(card);await pause(100);assert(!card.inert);card.shadowRoot.querySelector('.refill-btn').click();await pause(30);assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,2);
 allowed=false;emit({access_revoked:true});await pause(30);card.preview=true;card.preview=false;await pause(100);assert.match(card.shadowRoot.textContent,/Access denied/);assert.equal(card.shadowRoot.querySelector('.refill-btn'),null);assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,2);
 const external=w.document.createElement('ha-vacuum-water-monitor');external.inert=true;external.preview=true;external.preview=false;assert(external.inert,'external inert is not removed');
 card.remove();picker.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_picker_is_read_only_but_saved_card_remains_actionable(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[],patches=[],settings={sharing_intro_choice:'not_now',foreign_setting:'keep'};let emit,active=0;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Alpha device'}}},
  connection:{subscribeMessage:async cb=>{emit=cb;active++;return ()=>{active--}}},callWS:async m=>{calls.push(m.type);
   if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:{[id]:{initialized:true,used_ml:1000}}};
   if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Alpha device',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
   if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
   if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/reset_tank'))return {state:{initialized:true,used_ml:0}};
   if(m.type.endsWith('/set_settings')){patches.push(structuredClone(m));Object.assign(settings,structuredClone(m.patch));return {settings:structuredClone(settings),bindings_refreshed:true}};throw Error(m.type)}};
 // HA creates the element and assigns config/hass before inserting it in the
 // shadow-root .preview of hui-card-picker; tabIndex=-1 is HA's own property.
 for (const [pickerName,variant] of [['hui-card-picker','compact'],['hui-card-picker','tile'],['hui-card-picker','full'],['hui-suggestion-picker','compact']]) {
 const picker=w.document.createElement(pickerName),root=picker.attachShadow({mode:'open'}),wrapper=w.document.createElement('div');
 wrapper.className='preview';wrapper.style.pointerEvents='none';root.append(wrapper);w.document.body.append(picker);
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant,devices:[{vacuum_entity:id,name:'Alpha device'}]});card.hass=hass;card.tabIndex=-1;await pause(50);assert(!calls.some(x=>x.endsWith('/set_settings')),'detached card does not persist configuration');wrapper.append(card);await pause(120);
 assert.match(card.shadowRoot.textContent,/3(?:[.,]0)?/);if(variant!=='tile')assert.match(card.shadowRoot.textContent,/Alpha device/);const refill=card.shadowRoot.querySelector('.refill-btn');assert(refill);
 // Enter on a focused native button results in click. Exercise every exposed
 // control as well: no picker child may send a mutating command.
 refill.focus();refill.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));refill.click();
 for(const control of card.shadowRoot.querySelectorAll('button,input,select,textarea'))control.click();await pause(60);
 assert(!calls.some(x=>x.endsWith('/reset_tank')||x.endsWith('/set_settings')),'picker must never mutate Store');
 assert(card.inert||card.hasAttribute('inert')||refill.disabled,'picker is unavailable to keyboard users');assert.equal(active,1);assert(calls.some(x=>x.endsWith('/get_state')),'picker reads authorized state');active=0;emit({access_revoked:true});await pause(30);assert.match(card.shadowRoot.textContent,/Access denied/);assert(!card.shadowRoot.textContent.includes('Alpha device'),'revocation clears picker');card.remove();picker.remove();
 }
 const before=calls.filter(x=>x.endsWith('/reset_tank')).length;
 const saved=w.document.createElement('ha-vacuum-water-monitor');saved.setConfig({variant:'compact',title:'My saved card',devices:[{vacuum_entity:id,name:'Saved name',custom_option:'preserved'}]});saved.hass=hass;await pause(30);assert.equal(patches.length,0,'detached authored saved card has not persisted');w.document.body.append(saved);await pause(120);
 assert.equal(patches.length,1,'connected saved card persists one partial update');assert.equal(patches[0].partial,true);assert.equal(patches[0].patch.configured_devices[0].vacuum_entity,id);assert.equal(patches[0].patch.configured_devices[0].name,'Saved name');assert.equal(patches[0].patch.configured_devices[0].custom_option,'preserved');assert.equal(settings.foreign_setting,'keep');assert.match(saved.shadowRoot.textContent,/My saved card/);
 const css=saved.shadowRoot.querySelector('style').textContent;assert.match(css,/ha-card\s*>\s*\.card\s*\{[^}]*background:\s*transparent\s*!important;[^}]*border:\s*0\s*!important;[^}]*border-radius:\s*0\s*!important;[^}]*box-shadow:\s*none\s*!important/);saved.shadowRoot.querySelector('.refill-btn').click();await pause(50);
 assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,before+1,'ordinary saved card still executes');
 saved.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
