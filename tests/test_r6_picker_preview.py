"""HA picker preview cannot mutate a real robot from keyboard activation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PickerPreviewTests(unittest.TestCase):
    def test_picker_is_read_only_but_saved_card_remains_actionable(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},
  connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m.type);
   if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:1000}}};
   if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
   if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
   if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/reset_tank'))return {state:{initialized:true,used_ml:0}};
   if(m.type.endsWith('/set_settings'))return {settings:{sharing_intro_choice:'not_now'},bindings_refreshed:true};throw Error(m.type)}};
 // HA creates the element and assigns config/hass before inserting it in the
 // shadow-root .preview of hui-card-picker; tabIndex=-1 is HA's own property.
 const picker=w.document.createElement('hui-card-picker'),root=picker.attachShadow({mode:'open'}),wrapper=w.document.createElement('div');
 wrapper.className='preview';wrapper.style.pointerEvents='none';root.append(wrapper);w.document.body.append(picker);
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({variant:'compact'});card.hass=hass;card.tabIndex=-1;wrapper.append(card);await pause(120);
 assert.match(card.shadowRoot.textContent,/Robot/);const refill=card.shadowRoot.querySelector('.refill-btn');assert(refill);
 // Enter on a focused native button results in click. Exercise every exposed
 // control as well: no picker child may send a mutating command.
 refill.focus();refill.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));refill.click();
 for(const control of card.shadowRoot.querySelectorAll('button,input,select,textarea'))control.click();await pause(60);
 assert(!calls.some(x=>x.endsWith('/reset_tank')||x.endsWith('/set_settings')),'picker must never mutate Store');
 assert(card.hasAttribute('inert')||refill.disabled,'picker is unavailable to keyboard users');
 const before=calls.filter(x=>x.endsWith('/reset_tank')).length;
 const saved=w.document.createElement('ha-vacuum-water-monitor');saved.setConfig({variant:'compact'});saved.hass=hass;w.document.body.append(saved);await pause(120);
 saved.shadowRoot.querySelector('.refill-btn').click();await pause(50);
 assert.equal(calls.filter(x=>x.endsWith('/reset_tank')).length,before+1,'ordinary saved card still executes');
 card.remove();saved.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
