"""Neutral event labels, confirmation provenance and user-visible feedback."""
import subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ReviewRefillUiTest(unittest.TestCase):
 def test_auto_event_label_and_confirmation_source_in_both_languages(self):
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),classes={};
global.HTMLElement=class {constructor(){this.tagName='HA-VACUUM-WATER-MONITOR'}attachShadow(){this.shadowRoot={querySelector(){return null},querySelectorAll(){return []},getElementById(){return null}}}};
global.customElements={get(n){return classes[n]},define(n,c){classes[n]=c}};global.localStorage={getItem(){return null},setItem(){},removeItem(){}};global.window=global;global.history={replaceState(){}};global.location={pathname:'/'};global.CustomEvent=class{};
vm.runInThisContext(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
const card=new(classes['ha-vacuum-water-monitor'])(),id='vacuum.robot';card._hass={states:{}};card._serverState={settings:{configured_devices:[{vacuum_entity:id,water_total_ml:4000}]},tank_states:{}};
const d={vacuum_entity:id,water_total_ml:4000},state={initialized:true,used_ml:12,last_reset_iso:'2026-11-04T12:00:00+00:00',last_reset_source:'dock_cleared',cycle_full_confirmed:false,refill_full_unconfirmed:true};
function render(lang,patch={}){card._lang=lang;card._serverState.tank_states[id]={...state,...patch};return card._buildWaterTab(d,card._calcDeviceData(d))}
card._lang='en';assert.match(card._refillEvidence({full_confirmed:true,full_reason:'lid_and_clean_tank_removed',evidence:['lid','clean_tank_removed']}),/Full confirmed.*lid and clean tank.*lid opened/);assert.match(card._refillEvidence({full_confirmed:false,evidence:['lid']}),/Full unconfirmed/);assert.match(card._refillEvidence({}),/Older entry/);
card._lang='pl';assert.match(card._refillEvidence({full_confirmed:true,evidence:['lid','clean_tank_removed']}),/Pełne potwierdzone.*otwarcie pokrywy.*wyjęcie czystego zbiornika/);assert.match(card._refillEvidence({full_confirmed:false}),/Pełne niepotwierdzone/);assert.match(card._refillEvidence({}),/Starszy wpis/);
let x=render('en');assert.match(x,/Last tank event/);assert.match(x,/station alarm cleared/);assert(!x.includes('dock reported refilled'));assert(!x.includes('full confirmed by user'));
x=render('en',{cycle_full_confirmed:true,refill_full_unconfirmed:false,cycle_full_confirmation_source:'card'});assert.match(x,/full confirmed by user/);assert.match(x,/station alarm cleared/);
x=render('pl',{cycle_full_confirmed:true,refill_full_unconfirmed:false,cycle_full_confirmation_source:'card'});assert.match(x,/Ostatnie zdarzenie zbiornika/);assert.match(x,/alarm stacji ustąpił/);assert.match(x,/pełność potwierdzona przez użytkownika/);
x=render('en',{cycle_full_confirmed:true,cycle_full_confirmation_source:'declared_full_refill_practice'});assert.match(x,/full-refill practice enabled/);
x=render('en',{last_reset_source:'service',cycle_full_confirmed:true,cycle_full_confirmation_source:'service'});assert.match(x,/automation \/ script/);assert(!x.includes('station alarm cleared'));
'''
  result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
 def test_forecast_explains_changed_settings_en_and_pl(self):
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),classes={};
global.HTMLElement=class{constructor(){this.tagName='HA-VACUUM-WATER-MONITOR'}attachShadow(){this.shadowRoot={querySelector(){return null},querySelectorAll(){return []},getElementById(){return null}}}};
global.customElements={get(n){return classes[n]},define(n,c){classes[n]=c}};global.localStorage={getItem(){return null},setItem(){},removeItem(){}};global.window=global;global.history={replaceState(){}};global.location={pathname:'/'};global.CustomEvent=class{};
vm.runInThisContext(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));const card=new(classes['ha-vacuum-water-monitor'])();
card._healthFor=()=>({initialized:true,uncertainty_percent:20,supply:{basis_runs:0,cleanings_left:null,days_left:null,context_changed:true}});
const d={vacuum_entity:'vacuum.r'},data={initialized:true,remainingL:2.5,totalMl:4000,profileKey:'known',externalMode:false};
card._healthFor=()=>({supply:{reason:'external_counter'}});card._lang='en';assert.match(card._buildSupplyAnswer(d,{externalMode:true}),/external counter/);card._lang='pl';assert.match(card._buildSupplyAnswer(d,{externalMode:true}),/licznika zewnętrznego/);
card._healthFor=()=>({initialized:true,uncertainty_percent:20,supply:{basis_runs:0,cleanings_left:null,days_left:null,context_changed:true}});
card._lang='en';let x=card._buildSupplyAnswer(d,data);assert.match(x,/Settings changed/);assert.match(x,/0 of 3/);assert(!x.includes('data-cleanings-range'));
card._lang='pl';x=card._buildSupplyAnswer(d,data);assert.match(x,/Ustawienia się zmieniły/);assert.match(x,/0 z 3/);
'''
  r=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stderr)

 def test_auto_clear_explains_full_confirmation_in_both_languages(self):
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),classes={};
global.HTMLElement=class{constructor(){this.tagName='HA-VACUUM-WATER-MONITOR'}attachShadow(){this.shadowRoot={querySelector(){return null},querySelectorAll(){return []},getElementById(){return null}}}};
global.customElements={get(n){return classes[n]},define(n,c){classes[n]=c}};global.localStorage={getItem(){return null},setItem(){},removeItem(){}};global.window=global;global.history={replaceState(){}};global.location={pathname:'/'};global.CustomEvent=class{};
vm.runInThisContext(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));const card=new(classes['ha-vacuum-water-monitor'])();
const key="A cleared empty-tank alarm starts a new balance. Confirm a full refill unless the full-refill practice was already enabled. Disable this option if the alarm can clear without refilling.";
card._lang='en';assert.match(card._waterText(key),/Confirm a full refill/);assert.match(card._tipHtml(),/confirm a full refill/);assert(!card._tipHtml().includes('is recognised on its own'));
card._lang='pl';assert.match(card._waterText(key),/potwierdź pełne dolanie/i);assert.match(card._tipHtml(),/potwierdź pełne dolanie/i);assert(!card._tipHtml().includes('jest rozpoznawane samo'));
'''
  r=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stderr)

 def test_learning_and_plumbed_and_form_in_both_languages(self):
  script=r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const lang of ['en','pl']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.r',calls=[],yes={visible:true,read:true,execute:true},settings={sharing_intro_choice:'not_now'},states={[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}},'sensor.r_remaining':{entity_id:'sensor.r_remaining',state:'unknown',attributes:{vacuum_entity:id,source:'plumbed_supply',state_reason:'plumbed_supply_unmeasured'}}};
 const hass={language:lang,user:{id:'admin',is_admin:true},states,connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m);if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:5,physical_learning_resolution:{status:'provisional',source:'bound_reservoir_volume_sensor',scope:'whole_session',reason:'physical_observation_gap',sample_count:2,pending_count:1}}}};if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}]};if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings};throw Error(m.type)}};
 const c=w.document.createElement('ha-vacuum-water-monitor');c.setConfig({vacuum_entity:id,water_total_ml:4000,default_tab:'settings',show_support:false});c.hass=hass;w.document.body.append(c);await c._ensureServerState(true);await new Promise(r=>setTimeout(r,80));c._render();
 const rows=c._physicalLearningRows({status:'provisional',source:'bound_reservoir_volume_sensor',scope:'whole_session',reason:'physical_observation_gap',sample_count:2,pending_count:1,coefficient_ml_per_m2:5});assert(rows.some(x=>x[1]===(lang==='pl'?'Przerwa w obserwacji':'Observation gap')));assert(rows.some(x=>x[1]==='5 ml/m²'));
 const d=c._selectedDevice(),data=c._calcDeviceData(d);assert.equal(data.stateReason,'plumbed_supply_unmeasured');assert.equal(data.percentRemaining,null);assert.equal(data.remainingL,null);assert.match(c._buildSupplyAnswer(d,data),lang==='pl'?/podłączona do wody/:/plumbed supply/);
 const input=c.shadowRoot.querySelector('#vwm-former-volume-sensor'),button=c.shadowRoot.querySelector('#vwm-former-volume-save');assert(input&&button);input.value='sensor.old_tank';button.click();await new Promise(r=>setTimeout(r,30));assert(calls.some(m=>m.type.endsWith('/set_settings')&&m.patch.configured_devices?.[0]?.physical_learning_source_sensor==='sensor.old_tank'));c.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
'''
  result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
