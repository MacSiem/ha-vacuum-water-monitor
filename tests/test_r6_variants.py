"""R6 variants through the public card picker, renderer and ordinary actions."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VariantCardTests(unittest.TestCase):
    def test_picker_legacy_variants_and_full_transition(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const lang of ['en','pl']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const C=w.customElements.get('ha-vacuum-water-monitor');assert.equal(C.getStubConfig().variant,'compact');
 const id='vacuum.r6',calls=[],settings={sharing_intro_choice:'not_now'},tanks={[id]:{initialized:true,used_ml:1000}};
 const yes={visible:true,read:true,execute:true};
 const hass={language:lang,locale:{language:lang},user:{id:'u',is_admin:false},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},
 connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m);if(m.type.endsWith('/get_state'))return {settings,tank_states:tanks};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};if(m.type.endsWith('/reset_tank'))return {vacuum_entity:id,state:{initialized:true,used_ml:0}};throw Error(m.type)}};
 async function card(config){const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:4000,show_support:false,...config});
 c._refreshHealth=()=>null;c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,20));c._render();return c;}
 let c=await card({});assert(c.shadowRoot.querySelector('[role=tablist]'),'existing missing variant remains full');c.remove();
 for(const variant of ['tile','compact']){const custom=await card({variant,title:'My upstairs robot'});assert.equal(custom.shadowRoot.querySelector(variant==='tile'?'.vwm-tile-copy strong':'.vwm-heading-copy strong').textContent,'My upstairs robot');custom.remove();const fresh=await card({variant});assert.equal(fresh.shadowRoot.querySelector(variant==='tile'?'.vwm-tile-copy strong':'.vwm-heading-copy strong').textContent,lang==='pl'?(variant==='tile'?'Woda robota':'Woda w robocie'):'Robot water');fresh.remove();}
 c=await card({compact:true});assert(!c.shadowRoot.querySelector('[role=tablist]'),'legacy compact stays compact');c.remove();
 c=await card({variant:'tile'});assert.equal(c.getGridOptions().columns,6);assert.equal(c.getGridOptions().rows,1);
 assert(c.shadowRoot.querySelector('ha-card'));assert(!c.shadowRoot.querySelector('[role=tablist]'));assert(c.shadowRoot.querySelector('[data-r6-open]'));assert(c.shadowRoot.querySelector('ha-icon[icon="mdi:water-percent"]'));assert.match(c.shadowRoot.querySelector('.vwm-tile-short').textContent,/%/);
 const action=c.shadowRoot.querySelector('.vwm-tile-action .refill-btn');assert(action);action.click();await new Promise(r=>setTimeout(r,15));assert(!c.shadowRoot.querySelector('[role=tablist]'),'refill does not open full');assert.equal(calls.filter(m=>m.type.endsWith('/reset_tank')).length,1);
 c.shadowRoot.querySelector('[data-r6-open]').click();assert(c.shadowRoot.querySelector('[role=tablist]'),'tile tap opens full');assert.equal(calls.filter(m=>m.type.endsWith('/reset_tank')).length,1);c.remove();
 c=await card({variant:'compact'});assert.equal(c.getGridOptions().columns,12);assert.equal(c.getGridOptions().min_columns,6);assert(c.shadowRoot.querySelector('ha-card'));
 assert(!c.shadowRoot.querySelector('[role=tablist]'));assert(c.shadowRoot.querySelector('[role=progressbar]'));assert(c.shadowRoot.querySelector('.refill-btn'));assert(c.shadowRoot.querySelector('.vwm-main-value'));assert(c.shadowRoot.querySelector('.vwm-confidence'));assert(c.shadowRoot.querySelector('ha-icon[icon="mdi:water-percent"]'));
 const open=c.shadowRoot.querySelector('[data-r6-open]');assert(open);open.click();assert(c.shadowRoot.querySelector('[role=tablist]'),'full tool opens without YAML');
 assert.equal(calls.filter(m=>m.type.endsWith('/reset_tank')).length,1,'opening compact must not refill');c.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
