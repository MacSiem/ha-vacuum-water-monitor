"""Issue 32: rendered Matter identity, evidence and refresh."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MatterCardTests(unittest.TestCase):
    def test_render_and_refresh(self):
        script = r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const lang of ['en','pl']) {
 const dom=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.matter', card=dom.window.document.createElement('ha-vacuum-water-monitor');
 card.setConfig({vacuum_entity:id}); let count=0, resolve;
 const original={sharing_intro_choice:'not_now',custom_calibration:{[id]:{tracked_capacity_ml:4321}}};
 const descriptor={entity_id:id,name:'Robot',platform:'matter',profile_key:'dreame_x50_ultra',signals:{}};
 card._serverReady=true; card._serverLoadedAt=Date.now(); card._serverState={settings:original,tank_states:{[id]:{used_ml:42}}};
 card._discoveredVacuums=[descriptor]; card._refreshHealth=()=>null;
 card.hass={language:lang,locale:{language:lang},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},user:{is_admin:true},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{if(m.type.endsWith('/reprofile')) {count++;return await new Promise(r=>resolve=r)};throw Error(m.type)}};
 dom.window.document.body.append(card);card._render();
 assert.match(card.shadowRoot.textContent,/Dreame X50 Ultra/);
 assert.match(card.shadowRoot.textContent,lang==='pl'?/nie przypisano sygnałów powierzchni/i:/No area, water or mop-wash signals/i);
 descriptor.signals.area_sensor='sensor.area';card._lastHtml='';card._render();
 assert.doesNotMatch(card.shadowRoot.textContent,/No area, water or mop-wash signals|nie przypisano sygnałów powierzchni/i);
 delete descriptor.signals.area_sensor; descriptor.profile_key='roborock_s8_maxv_ultra';card._lastHtml='';card._render();
 assert.doesNotMatch(card.shadowRoot.textContent,/No area, water or mop-wash signals|nie przypisano sygnałów powierzchni/i);
 descriptor.profile_key='dreame_x50_ultra';card._activeTab='settings';card._lastHtml='';card._render();
 assert(card.shadowRoot.querySelector('[onclick*="_reprofileDevice"]'));
 const a=card._reprofileDevice(),b=card._reprofileDevice();assert.strictEqual(a,b);assert.equal(count,1);
 resolve({settings:original,vacuums:[{...descriptor,profile_key:null}],balance_links:{},bindings_refreshed:true});await a;
 assert.equal(card._serverState.tank_states[id].used_ml,42);assert.equal(card._serverState.settings.custom_calibration[id].tracked_capacity_ml,4321);
 assert.match(card.shadowRoot.getElementById('vwm-reprofile-status').textContent,lang==='pl'?/nadal jest nieznany/i:/still unknown/i);
 dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
