"""R6 native findings through the rendered form, event stream and preview."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeFindingsTests(unittest.TestCase):
    def run_node(self, source):
        result = subprocess.run(["node", "-e", source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preview_reads_authorized_robot_without_writes_or_actions(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.known',yes={visible:true,read:true,execute:true},calls=[],settings={sharing_intro_choice:'not_now'};
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Known'}}},connection:{subscribeMessage:async()=>{calls.push('subscribe');return ()=>{}}},callWS:async m=>{calls.push(m.type);
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Known',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.preview=true;card.inert=true;card.setAttribute('inert','');card.setConfig({variant:'compact'});card.hass=hass;w.document.body.append(card);await new Promise(r=>setTimeout(r,100));
 assert.match(card.shadowRoot.textContent,/Known/);assert.match(card.shadowRoot.textContent,/3[.,]0/);assert(!card.shadowRoot.textContent.includes('No configured devices'));
 for(const button of card.shadowRoot.querySelectorAll('button'))button.click();await new Promise(r=>setTimeout(r,30));
 assert(!calls.some(x=>x.endsWith('/set_settings')||x.endsWith('/reset_tank')),'preview performs no writes or actions');assert(!calls.includes('subscribe'),'preview needs no live subscription');
 card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_manual_form_saved_once_stays_visible_and_distinguishes_zero_unknown(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{for(const water of ['40','0','']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.known',old='vacuum.historic',yes={visible:true,read:true,execute:true},calls=[],settings={sharing_intro_choice:'not_now',sessions:{}};
 const tanks={[id]:{initialized:true,used_ml:1000},[old]:{initialized:true,used_ml:500}},observed=[];let emit;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Known'}}},connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m.type);
 if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:structuredClone(tanks)};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Known',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes},[old]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings')){Object.assign(settings,structuredClone(m.patch));emit({data:{settings_changed:true,authorized_vacuums:[id]}});await delay(5);return {settings:structuredClone(settings),bindings_refreshed:true}};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({default_tab:'history',show_support:false});card.hass=hass;w.document.body.append(card);await card._ensureServerState(true);await delay(40);
 const observer=new w.MutationObserver(()=>observed.push(card.shadowRoot.textContent));observer.observe(card.shadowRoot,{childList:true,subtree:true,characterData:true});
 card.shadowRoot.querySelector('#hist-area').value='5';card.shadowRoot.querySelector('#hist-water').value=water;card.shadowRoot.querySelector('#hist-duration').value='2m';card.shadowRoot.querySelector('#hist-log-btn').click();await delay(120);
 assert.equal(calls.filter(x=>x.endsWith('/set_settings')).length,1,'one click makes one save');assert.equal(settings.sessions[id].length,1);assert(!observed.some(s=>/Access denied|Not saved/.test(s)),'ordinary settings event is not a revocation or failed save');
 const rows=[...card.shadowRoot.querySelectorAll('[data-r6-session-data] tr')];assert(rows.length);if(water==='')assert.match(rows[0].textContent,/Unknown/);else assert.match(rows[0].textContent,new RegExp('(^|\\D)'+water+'\\s*ml'));
 observer.disconnect();card.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
""")
