"""A forecast band is drawn only from a qualified forecast plus uncertainty."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ForecastBandTests(unittest.TestCase):
    def test_qualified_and_missing_uncertainty(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const uncertainty of [20,null]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.r6',sensor='sensor.r6_remaining',now=Date.now(),yes={visible:true,read:true,execute:true};
 const settings={sharing_intro_choice:'not_now'},states={[id]:{entity_id:id,state:'docked',attributes:{}},[sensor]:{entity_id:sensor,state:'50',attributes:{vacuum_entity:id,unit_of_measurement:'%',remaining_ml:2000}}};
 const hass={language:'en',config:{time_zone:'Europe/Warsaw'},user:{id:'u',is_admin:false},states,connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{
 if(m.type==='history/history_during_period')return {[sensor]:[{state:'50',last_changed:new Date(now-100000).toISOString()}]};
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,profile_key:'roborock_s8_maxv_ultra',capacity_ml:3000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[{vacuum_entity:id,initialized:true,uncertainty_percent:uncertainty,supply:{basis_runs:5,cleanings_left:4,days_left:8}}]};
 if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:3000,default_tab:'history',show_support:false});c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,70));
 const chart=c.shadowRoot.querySelector('.r6-history svg');assert(chart);const band=chart.querySelector('rect');
 if(uncertainty===null)assert.equal(band,null,'no invented uncertainty band');else{assert(band,'qualified data produces a band');const title=band.querySelector('title').textContent;assert.match(title,/Estimated empty interval/);assert(c.shadowRoot.querySelector('.r6-history').textContent.includes(title),'chart and data use the same interval');}
 c.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
