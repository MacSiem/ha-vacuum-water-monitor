"""R6 history uses Recorder points and Store sessions without inventing values."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WaterHistoryTests(unittest.TestCase):
    def test_history_points_gaps_refill_and_session_data(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const lang of ['en','pl']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.r6',sensor='sensor.r6_remaining',now=Date.now(),yes={visible:true,read:true,execute:true},calls=[];let emit;
 const sessions=[{ts:now-100000,type:'automatic',water:120,area:20,accounting_valid:true,exposure_complete:true,context:{model:'same'}},{ts:now-200000,type:'automatic',water:0,area:20,accounting_valid:true,exposure_complete:true,context:{model:'same'}},{ts:now-300000,type:'automatic',water:null,context:{model:'unknown'}}];
 const settings={sharing_intro_choice:'not_now',sessions:{[id]:sessions}};
 const states={[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}},[sensor]:{entity_id:sensor,state:'50',attributes:{vacuum_entity:id,unit_of_measurement:'%',remaining_ml:2000}}};
 const hass={language:lang,locale:{language:lang},config:{time_zone:'Europe/Warsaw'},user:{id:'u',is_admin:false},states,connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m);
 if(m.type==='history/history_during_period')return {[sensor]:[{state:'80',last_changed:new Date(now-400000).toISOString()},{state:'unavailable',last_changed:new Date(now-300000).toISOString()},{state:'50',last_changed:new Date(now-200000).toISOString()}]};
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:2000,refill_history:[{ts:now-250000,source:'manual'}]}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:4000,default_tab:'history',show_support:false});c._refreshHealth=()=>null;c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,40));
 const section=c.shadowRoot.querySelector('.r6-history');assert(section);assert.equal(calls.filter(x=>x.type==='history/history_during_period').length,1);
 const chart=section.querySelector('svg'),path=chart.querySelector('path');assert.equal((path.getAttribute('d').match(/ M /g)||[]).length,2,'unavailable separates the line');
 assert.equal(chart.querySelectorAll('circle').length,2);assert.equal(chart.querySelectorAll('line').length,1);
 assert.match(section.textContent,/80%/);assert.match(section.textContent,/50%/);assert.match(section.textContent,/120 ml/);assert.match(section.textContent,/0 ml/);
 assert.match(section.textContent,lang==='pl'?/Nieznany/:/Unknown/);assert.match(section.textContent,lang==='pl'?/Dolano/:/Refilled/);
 assert.match(section.textContent,lang==='pl'?/Bez procentu|Brak porównania/:/No percentage|No comparison/);assert(!section.textContent.includes('NaN'));
 settings.sessions[id]=[120,100,100,100].map((water,i)=>({ts:now-i*100000,type:'automatic',water,area:20,method:'area',segments:1,accounting_valid:true,exposure_complete:true,context:{model:'same'}}));
 assert(emit);emit({data:{settings_changed:true}});await new Promise(r=>setTimeout(r,80));const updated=c.shadowRoot.querySelector('.r6-history');assert.match(updated.textContent,/\+20(?:[.,]0)?%/,'complete comparable exposure enables a signed session comparison');
 settings.sessions[id][0].exposure_complete=false;emit({data:{settings_changed:true}});await new Promise(r=>setTimeout(r,80));assert.match(c.shadowRoot.querySelector('.r6-history').textContent,lang==='pl'?/Bez procentu|Brak porównania/:/No percentage|No comparison/);
 c.remove();w.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
