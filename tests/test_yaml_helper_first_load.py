"""A newly authored helper is projected before the first ready render."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuthoredHelperFirstLoadTests(unittest.TestCase):
    def test_yaml_helper_first_load_reads_projected_state_without_event(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<html></html>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;w.eval(fs.readFileSync(process.env.CARD_JS,'utf8'));
 const id='vacuum.qa', yes={visible:true,read:true,execute:true};let settings={configured_devices:[]}, saves=0,reads=0,release;
 const h={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{}},'input_number.used':{entity_id:'input_number.used',state:'500',attributes:{unit_of_measurement:'mL'}},'input_number.other':{entity_id:'input_number.other',state:'750',attributes:{unit_of_measurement:'mL'}}},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{
 if(m.type.endsWith('/get_state')){reads++;const visible=process.env.SCENARIO==='redacted'?{...settings,configured_devices:settings.configured_devices.map(d=>({vacuum_entity:d.vacuum_entity}))}:settings;return {settings:visible,tank_states:{[id]:settings.configured_devices.some(d=>d.water_used_input)?{used_ml:settings.configured_devices[0].water_used_input==='input_number.other'?750:500,initialized:true,external_counter:{used_ml:settings.configured_devices[0].water_used_input==='input_number.other'?750:500,remaining_ml:null,remaining_sensor:false}}:{used_ml:100,initialized:true}}};}
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'QA',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access')){const rule=process.env.SCENARIO==='redacted'?{visible:true,read:false,execute:true}:yes;return {capabilities:{water:yes,settings:rule,measurements:yes},resources:{[id]:{water:yes,settings:rule,measurements:yes}}};}
 if(m.type.endsWith('/set_settings')){saves++;settings={...settings,...m.patch};if((process.env.SCENARIO==='revoke'||process.env.SCENARIO==='swap')&&saves===1)await new Promise(r=>release=r);return {settings,bindings_refreshed:true}};
 if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type);
 }};
 const c=w.document.createElement('ha-vacuum-water-monitor');
 const config=(helper,other=false)=>{const device={vacuum_entity:id,water_total_ml:4000,...(helper?{water_used_input:other?'input_number.other':'input_number.used'}:{})};return process.env.SCENARIO==='flat'?{...device,show_support:false}:{devices:[device],show_support:false};};
 c.setConfig(config(process.env.SCENARIO!=='connected'));c.hass=h;w.document.body.append(c);await new Promise(r=>setTimeout(r,100));
 if(process.env.SCENARIO==='swap'){assert(release);c.setConfig(config(true,true));release();await new Promise(r=>setTimeout(r,300));assert.equal(saves,2);assert.equal(c._serverState.tank_states[id].external_counter.used_ml,750);dom.window.close();return;}
 if(process.env.SCENARIO==='revoke'){assert(release);c._clearPrivateAccess(false);c._accessDenied=true;release();await new Promise(r=>setTimeout(r,100));assert.equal(reads,1);assert.deepEqual(Object.keys(c._serverState.tank_states),[]);assert(c._configuredSaveFence == null);dom.window.close();return;}
 await new Promise(r=>setTimeout(r,200));
 if(process.env.SCENARIO==='connected'){c.setConfig(config(true));await new Promise(r=>setTimeout(r,300));}
 if(process.env.SCENARIO==='redacted'){await c._ensureServerState(true);await new Promise(r=>setTimeout(r,100));}
 const state=c._serverState.tank_states[id], text=c.shadowRoot.textContent;console.log(JSON.stringify({reads,saves,used:state.used_ml,projected:state.external_counter?.used_ml,rendered500:text.includes('0.50 L')}));assert.equal(saves,process.env.SCENARIO==='connected'?2:1);assert.equal(reads,process.env.SCENARIO==='connected'?4:process.env.SCENARIO==='redacted'?3:2);assert.equal(state.external_counter?.used_ml,500);assert(text.includes('0.50 L'));dom.window.close();
})().catch(e=>{console.error(e.stack);process.exit(1)});

"""
        for card in ("ha-vacuum-water-monitor.js",
                     "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js"):
            for scenario in ("first", "connected", "redacted", "flat", "revoke", "swap"):
                with self.subTest(card=card, scenario=scenario):
                    env = {**os.environ, "CARD_JS": str(ROOT / card), "SCENARIO": scenario}
                    result = subprocess.run(["node", "-e", script], cwd=ROOT, env=env,
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
