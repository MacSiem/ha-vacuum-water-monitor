"""HA attribute and selected battery sensor changes refresh the card."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]

class BatteryFreshness(unittest.TestCase):
 def test_live_battery_and_unrelated_updates(self):
  script=r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const external of [false,true]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;w.eval(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.r',yes={visible:true,read:true,execute:true},settings={sharing_intro_choice:'not_now'},states={[id]:{entity_id:id,state:'docked',attributes:{battery_level:100}},'sensor.charge':{entity_id:'sensor.charge',state:'100',attributes:{}}};
 const hass={language:'en',user:{id:'u',is_admin:false},states,connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:1000}}};if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,...(external?{charge_sensor:'sensor.charge'}:{})}]};if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:4000,show_support:false});c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,60));assert.match(c.shadowRoot.textContent,/100%/);
 const original=c.shadowRoot.querySelector('ha-card');c._lastRenderTime=0;
 const next={...states,[id]:{...states[id],attributes:{battery_level:42}},'sensor.charge':{...states['sensor.charge'],state:external?'42':'100'}};c.hass={...hass,states:next};assert.match(c.shadowRoot.textContent,/42%/);assert.equal(c.shadowRoot.querySelector('ha-card'),original);
 const markup=c.shadowRoot.querySelector('#vwm-tab-panel');c._lastRenderTime=0;c.hass={...hass,states:{...next,'sensor.other':{entity_id:'sensor.other',state:'9',attributes:{}}}};assert.equal(c.shadowRoot.querySelector('#vwm-tab-panel'),markup);
 c.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
'''
  r=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stderr)
