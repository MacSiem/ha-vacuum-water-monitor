"""A navigation-only robot selection must never persist an authored device."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PanelNavigationTests(unittest.TestCase):
    def test_tile_to_panel_and_direct_query_never_write_settings(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{for(const direct of [false,true]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/lovelace/home'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/vwm-panel.js','utf8').replace("import './ha-vacuum-water-monitor.js';",''));
 const yes={visible:true,read:true,execute:true},a='vacuum.a',b='vacuum.b',calls=[],settings={sharing_intro_choice:'not_now'};
 const hass={language:'en',user:{id:'u',is_admin:false},states:{[a]:{entity_id:a,state:'docked',attributes:{friendly_name:'Alpha'}},[b]:{entity_id:b,state:'docked',attributes:{friendly_name:'Bravo'}}},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m);
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[a]:{initialized:true,used_ml:10},[b]:{initialized:true,used_ml:30}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:a,name:'Alpha',identity_group:a,tracked_capacity_ml:4000},{entity_id:b,name:'Bravo',identity_group:b,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[a]:{water:yes,settings:yes},[b]:{water:yes,settings:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 if(direct)w.history.pushState(null,'','/vacuum-water-monitor?vacuum='+encodeURIComponent(b));
 else{const tile=w.document.createElement('ha-vacuum-water-monitor');tile.setConfig({devices:[{vacuum_entity:b}],variant:'tile',tap_target:'panel'});tile._refreshHealth=()=>null;tile.hass=hass;w.document.body.append(tile);await tile._ensureServerState(true);await delay(40);calls.length=0;tile.shadowRoot.querySelector('[data-r6-open]').click();assert.equal(w.location.pathname,'/vacuum-water-monitor');assert.equal(new w.URL(w.location.href).searchParams.get('vacuum'),b);tile.remove();}
 calls.length=0;const panel=w.document.createElement('vwm-standalone-panel');w.document.body.append(panel);panel.hass=hass;await delay(80);
 const card=panel.shadowRoot.querySelector('ha-vacuum-water-monitor');assert.equal(card.shadowRoot.querySelector('.dtab-active')?.textContent.trim().includes('Bravo'),true,'Bravo is the active robot, not merely present in tabs');assert.match(card.shadowRoot.querySelector('#vwm-tab-panel').textContent,/3[.,]97/,'the rendered balance belongs to Bravo');assert(!calls.some(m=>m.type.endsWith('/set_settings')),'navigation does not author or save device config');assert(!settings.configured_devices);
 panel.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
