"""Partial local-day comparisons use the same wall-clock cutoff across DST."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PeriodComparisonTests(unittest.TestCase):
    def test_dst_and_incomplete_coverage(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 const now=Date.parse('2026-10-26T11:00:00Z'),NativeDate=w.Date;w.Date=class extends NativeDate{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}};
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.r6',yes={visible:true,read:true,execute:true};let emit;
 const sample=(ts,water)=>({ts:Date.parse(ts),type:'automatic',water,area:20,method:'area',segments:1,accounting_valid:true,exposure_complete:true,context:{model:'same'}});
 const sessions=[sample('2026-10-26T10:00:00Z',120),sample('2026-10-19T09:00:00Z',100),sample('2026-10-19T12:00:00Z',999)];
 const settings={sharing_intro_choice:'not_now',sessions:{[id]:sessions}},hass={language:'en',config:{time_zone:'Europe/Warsaw'},user:{id:'u',is_admin:false},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:0}}};if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:4000,default_tab:'history',show_support:false});c._refreshHealth=()=>null;c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,50));
 const find=()=>[...c.shadowRoot.querySelectorAll('.r6-history p')].find(p=>/current 7 local days|No period comparison/.test(p.textContent)).textContent;
 assert.match(find(),/120 \/ 100 ml/);assert.match(find(),/\+20%/);assert(!find().includes('999'));
 sessions[1].exposure_complete=false;emit({data:{settings_changed:true}});await new Promise(r=>setTimeout(r,70));assert.match(find(),/No period comparison/);assert(!find().includes('%'));
 c.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
