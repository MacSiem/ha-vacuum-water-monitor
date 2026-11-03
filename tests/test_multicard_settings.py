"""Two actual cards sharing the same Home Assistant settings."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MultiCardSettingsTests(unittest.TestCase):
    def test_two_authored_cards_preserve_both_devices_without_write_loop(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const listeners=[], writes=[]; let deliver=true;
 let state={settings:{configured_devices:[],robot_links:{'vacuum.keep':'distinct'},warning_threshold:20,critical_threshold:10},
   tank_states:{'vacuum.a':{used_ml:123},'vacuum.b':{used_ml:456}}};
 const vacuums=['vacuum.a','vacuum.b'].map(id=>({entity_id:id,name:id,identity_group:id,balance_owner:id}));
 vacuums.push({entity_id:'vacuum.copy_a',name:'Copy A',identity_group:'vacuum.copy_a',possible_duplicate_of:'vacuum.a'},
              {entity_id:'vacuum.copy_b',name:'Copy B',identity_group:'vacuum.copy_b',possible_duplicate_of:'vacuum.b'});
 const hass={language:'en',locale:{language:'en'},user:{is_admin:true},states:{
   'vacuum.a':{entity_id:'vacuum.a',state:'docked',attributes:{}},
   'vacuum.b':{entity_id:'vacuum.b',state:'docked',attributes:{}}},
   connection:{subscribeMessage:async cb=>{listeners.push(cb);return ()=>{}}},
   callWS:async m=>{
    if(m.type.endsWith('/get_state'))return structuredClone(state);
    if(m.type.endsWith('/list_vacuums'))return {vacuums:structuredClone(vacuums),balance_links:structuredClone(state.settings.robot_links)};
    if(m.type.endsWith('/health'))return {robots:[]};
    if(m.type.endsWith('/set_robot_link')){
      state.settings.robot_links={...state.settings.robot_links,[m.vacuum_entity]:m.target};
      return {settings:structuredClone(state.settings)};
    }
    if(m.type.endsWith('/set_settings')){
      writes.push(structuredClone(m.patch));if(writes.length>10)throw Error('settings write loop');
      const patch=structuredClone(m.patch);
      if(m.partial){
       for(const key of ['configured_devices','user_devices'])if(patch[key]){
        const merged=structuredClone(state.settings[key]||[]);
        for(const item of patch[key]){const i=merged.findIndex(d=>d.vacuum_entity===item.vacuum_entity);if(i<0)merged.push(item);else merged[i]={...merged[i],...item};}
        patch[key]=merged;
       }
       if(patch.robot_links)patch.robot_links={...state.settings.robot_links,...patch.robot_links};
      }
      state.settings={...state.settings,...patch};
      const data={settings:structuredClone(state.settings)};
      if(deliver)for(const cb of listeners)queueMicrotask(()=>cb({data}));
      return {settings:structuredClone(state.settings),bindings_refreshed:true};
    }
    throw Error(m.type);
   }};
 const cards=[];
 for(const id of ['vacuum.a','vacuum.b']){
   const card=dom.window.document.createElement('ha-vacuum-water-monitor');
   card.setConfig({vacuum_entity:id,water_total_ml:id.endsWith('a')?1000:2000});
   card.hass=hass;dom.window.document.body.append(card);cards.push(card);
   await new Promise(r=>setTimeout(r,25));
 }
 await new Promise(r=>setTimeout(r,100));
 assert.deepEqual(state.settings.configured_devices.map(d=>d.vacuum_entity).sort(),['vacuum.a','vacuum.b']);
 assert.equal(state.settings.robot_links['vacuum.keep'],'distinct');
 assert.equal(state.tank_states['vacuum.a'].used_ml,123);assert.equal(state.tank_states['vacuum.b'].used_ml,456);
 assert(writes.length<=4,'automatic writes must converge');
 // A real incoming state event must preserve an open draft while the card rerenders.
 cards[0]._activeTab='settings';cards[0]._lastHtml='';cards[0]._render();
 let draft=cards[0].shadowRoot.querySelector('details.contribution-form');
 assert(draft);draft.open=true;
 cards[0].shadowRoot.getElementById('cal-observed').value='123';
 cards[0].shadowRoot.getElementById('cal-boundaries').checked=true;
 for(const cb of listeners)cb({data:{partial:true,tank_states:{'vacuum.a':{used_ml:124}}}});
 await new Promise(r=>setTimeout(r,30));
 draft=cards[0].shadowRoot.querySelector('details.contribution-form');
 assert(draft.open);assert.equal(cards[0].shadowRoot.getElementById('cal-observed').value,'123');
 assert.equal(cards[0].shadowRoot.getElementById('cal-boundaries').checked,true);
 deliver=false; // A and B are deliberately editing from the same earlier snapshot.
 const choice=(card,id)=>card.shadowRoot.querySelector(`[data-dup="${id}"][data-target="distinct"]`);
 assert(choice(cards[0],'vacuum.copy_a'));assert(choice(cards[1],'vacuum.copy_b'));
 choice(cards[0],'vacuum.copy_a').click();await new Promise(r=>setTimeout(r,30));
 choice(cards[1],'vacuum.copy_b').click();await new Promise(r=>setTimeout(r,30));
 assert.equal(state.settings.robot_links['vacuum.copy_a'],'distinct');
 assert.equal(state.settings.robot_links['vacuum.copy_b'],'distinct');
 assert.equal(state.settings.robot_links['vacuum.keep'],'distinct');
 for(const card of cards)card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
