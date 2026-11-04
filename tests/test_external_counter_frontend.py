"""The mounted card displays a scoped external-counter server projection."""
from pathlib import Path
import subprocess
import unittest
ROOT = Path(__file__).resolve().parents[1]

class ExternalCounterFrontendTests(unittest.TestCase):
    def test_external_update_unknown_and_no_refill_action(self):
        script = r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',helper='input_number.diy_used',yes={visible:true,read:true,execute:true},calls=[];let emit,used=500;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}},[helper]:{entity_id:helper,state:'500',attributes:{unit_of_measurement:'mL'}}},connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m.type);
 if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:125,external_counter:{used_ml:used,remaining_ml:null,remaining_sensor:false,last_session_ml:null,last_reset:null}}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings:{sharing_intro_choice:'not_now'}};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({vacuum_entity:id,water_total_ml:4000,water_used_input:helper,show_support:false});card.hass=hass;w.document.body.append(card);await pause(180);
 const data=()=>card._calcDeviceData(card._getDevices()[0]);assert.equal(data().usedMl,500);assert.equal(data().remainingL,3.5);
 assert.equal(card.shadowRoot.querySelector('.refill-btn'),null); assert.match(card.shadowRoot.textContent,/own automation; VWM does not reset the counter/);
 for(const [lang,expected] of [['en',/Forecast unavailable for an external water source/],['pl',/Brak prognozy dla zewnętrznego źródła wody/]]){
  card._lang=lang;const html=card._buildSupplyAnswer(card._getDevices()[0],data());assert.match(html,expected);assert(!html.includes('data-open-confidence'));
 }
 card._lang='en';
 used=1500;emit({data:{state_changed:true,authorized_vacuums:[id]}});await pause(180);assert.equal(data().usedMl,1500);assert.equal(data().remainingL,2.5);assert.match(card.shadowRoot.textContent,/2\.50/);
 used=0;emit({data:{state_changed:true,authorized_vacuums:[id]}});await pause(180);assert.equal(data().usedMl,0);assert.equal(data().remainingL,4);
 used=null;emit({data:{state_changed:true,authorized_vacuums:[id]}});await pause(180);assert.equal(data().usedMl,null);assert.equal(data().remainingL,null);assert(!calls.some(x=>x.endsWith('/reset_tank')));
 card.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
