"""R6 native findings through the rendered form, event stream and preview."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeFindingsTests(unittest.TestCase):
    def run_node(self, source):
        result = subprocess.run(["node", "-e", source], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preview_reads_authorized_robot_without_writes_or_actions(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.known',yes={visible:true,read:true,execute:true},calls=[],settings={sharing_intro_choice:'not_now'};let emit,active=0;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Known'}}},connection:{subscribeMessage:async cb=>{calls.push('subscribe');emit=cb;active++;return ()=>{active--}}},callWS:async m=>{calls.push(m.type);
 if(m.type.endsWith('/get_state'))return {settings,tank_states:{[id]:{initialized:true,used_ml:1000}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Known',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.preview=true;card.inert=true;card.setAttribute('inert','');card.setConfig({variant:'compact'});card.hass=hass;w.document.body.append(card);await new Promise(r=>setTimeout(r,100));
 assert.match(card.shadowRoot.textContent,/Known/);assert.match(card.shadowRoot.textContent,/3[.,]0/);assert(!card.shadowRoot.textContent.includes('No configured devices'));
 for(const button of card.shadowRoot.querySelectorAll('button'))button.click();await new Promise(r=>setTimeout(r,30));
 assert(!calls.some(x=>x.endsWith('/set_settings')||x.endsWith('/reset_tank')),'preview performs no writes or actions');assert.equal(active,1,'preview observes permission changes');
 active=0;emit({access_revoked:true});await new Promise(r=>setTimeout(r,40));assert.match(card.shadowRoot.textContent,/Access denied/);assert(!card.shadowRoot.textContent.includes('Known'));assert.equal(active,0);card.remove();assert.equal(active,0);dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_compact_theme_controls_have_accessible_computed_contrast(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const rgb=hex=>hex.match(/[a-f0-9]{2}/gi).map(x=>parseInt(x,16)/255),l=hex=>rgb(hex).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0),ratio=(a,b)=>(Math.max(l(a),l(b))+.05)/(Math.min(l(a),l(b))+.05),blend=(a,b,k)=>'#'+rgb(a).map((v,i)=>Math.round((v*k+rgb(b)[i]*(1-k))*255).toString(16).padStart(2,'0')).join('');
(async()=>{for(const [background,primary,dark,haBackground] of [['#ffffff','#fbbf24',false,null],['#f3f4f6','#2563eb',false,null],['#1c1c1e','#818cf8',true,null],['#ffffff','#2563eb',false,'#222222']]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},card=w.document.createElement('ha-vacuum-water-monitor');card.style.setProperty('--card-background-color',background);if(haBackground)card.style.setProperty('--ha-card-background',haBackground);card.style.setProperty('--primary-color',primary);card.style.setProperty('--divider-color',dark?'rgba(255, 255, 255, 0.12)':'rgba(0, 0, 0, 0.12)');card.setConfig({variant:'compact'});w.document.body.append(card);
 card.hass={language:'en',themes:{darkMode:dark},user:{id:'u',is_admin:false},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:1000}}};if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 await new Promise(r=>setTimeout(r,80));const prop=name=>card.style.getPropertyValue(name).trim();const fill=prop('--hat-primary-fill-computed'),fg=prop('--hat-on-primary-computed');assert(ratio(fill,fg)>=4.5);assert(ratio(prop('--vwm-warn-text-computed'),haBackground||background)>=4.5);assert(ratio(prop('--vwm-crit-text-computed'),haBackground||background)>=4.5);const bg=haBackground||background,track=blend(dark?'#ffffff':'#000000',bg,.12);assert.equal(prop('--vwm-meter-track'),track);for(const tone of ['normal','warn','crit'])assert(ratio(prop('--vwm-meter-'+tone),track)>=3,`${tone} meter`);for(const [tone,color] of [['ok','#22c55e'],['warn','#f59e0b'],['crit','#ef4444'],['unknown','#6b7280']])assert(ratio(prop('--vwm-badge-'+tone),blend(color,bg,32/255))>=4.5,`${tone} badge`);for(const alpha of [.03,.08])assert(ratio(prop('--vwm-tip-text'),blend('#3b82f6',bg,alpha))>=4.5,'help gradient');
 assert.equal(card.shadowRoot.querySelector('.vwm-compact-actions .refill-btn').textContent.trim(),'Refilled');assert(card.shadowRoot.querySelector('[data-r6-details]'));
 const full=w.document.createElement('ha-vacuum-water-monitor');full.setConfig({variant:'full',show_help:true,show_support:false});full.hass=card._hass;w.document.body.append(full);await new Promise(r=>setTimeout(r,80));const badge=full.shadowRoot.querySelector('.status-badge');assert(badge);assert.match(badge.getAttribute('style'),/--vwm-badge-ok/);assert(full.shadowRoot.querySelector('.tip-banner-title'));const css=full.shadowRoot.querySelector('style').textContent;assert.match(css,/color:\s*var\(--vwm-tip-text/);assert.match(css,/background:var\(--vwm-meter-normal/);assert.match(css,/:host\(\.bento-dark\) \.card :focus-visible, :host \.card :focus-visible \{ outline:2px solid var\(--hat-primary,var\(--primary-color,#2563eb\)\) !important; outline-offset:2px !important;/);full.remove();card.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_removed_preview_does_not_subscribe_when_reads_finish_late(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 let resolveState,resolveList,subscriptions=0;const hass={language:'en',user:{id:'u',is_admin:false},states:{},connection:{subscribeMessage:async()=>{subscriptions++;return ()=>{}}},callWS:m=>{
 if(m.type.endsWith('/get_state'))return new Promise(resolve=>{resolveState=()=>resolve({settings:{},tank_states:{}})});
 if(m.type.endsWith('/list_vacuums'))return new Promise(resolve=>{resolveList=()=>resolve({vacuums:[],balance_links:{}})});throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.preview=true;card.setConfig({variant:'compact'});w.document.body.append(card);card.hass=hass;card.remove();resolveState();resolveList();await new Promise(r=>setTimeout(r,30));assert.equal(subscriptions,0,'detached preview cannot subscribe from a stale read');dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_manual_form_saved_once_stays_visible_and_distinguishes_zero_unknown(self):
        self.run_node(r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{for(const water of ['40','0','']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.known',old='vacuum.historic',yes={visible:true,read:true,execute:true},calls=[],settings={sharing_intro_choice:'not_now',sessions:{[id]:[{ts:Date.now()-1000,area:'2',water:'100'},{ts:Date.now()-2000,area:'2',water:'0'},{ts:Date.now()-3000,area:'2',water:''}]}};
 const tanks={[id]:{initialized:true,used_ml:1000},[old]:{initialized:true,used_ml:500}},observed=[];let emit;
 const hass={language:'en',user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Known'}}},connection:{subscribeMessage:async cb=>{emit=cb;return ()=>{}}},callWS:async m=>{calls.push(m.type);
 if(m.type.endsWith('/get_state'))return {settings:structuredClone(settings),tank_states:structuredClone(tanks)};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Known',identity_group:id,tracked_capacity_ml:4000}],balance_links:{}};
 if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes},[old]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings')){Object.assign(settings,structuredClone(m.patch));emit({data:{settings_changed:true,authorized_vacuums:[id,old]}});await delay(5);return {settings:structuredClone(settings),bindings_refreshed:true}};throw Error(m.type)}};
 const card=w.document.createElement('ha-vacuum-water-monitor');card.setConfig({default_tab:'history',show_support:false});card.hass=hass;w.document.body.append(card);await card._ensureServerState(true);await delay(40);
 const observer=new w.MutationObserver(()=>observed.push(card.shadowRoot.textContent));observer.observe(card.shadowRoot,{childList:true,subtree:true,characterData:true});
 card.shadowRoot.querySelector('#hist-area').value='5';card.shadowRoot.querySelector('#hist-water').value=water;card.shadowRoot.querySelector('#hist-duration').value='2m';card.shadowRoot.querySelector('#hist-log-btn').click();await delay(120);
 assert.equal(calls.filter(x=>x.endsWith('/set_settings')).length,1,'one click makes one save');assert.equal(settings.sessions[id].length,4);assert.deepEqual(settings.sessions[id].slice(1).map(s=>s.water),['100','0',''],'adding a session does not rewrite historical strings');for(const input of ['hist-area','hist-water','hist-duration'])assert.equal(card.shadowRoot.getElementById(input).value,'','successful save clears the submitted draft');assert(!observed.some(s=>/Access denied|Not saved/.test(s)),'ordinary settings event is not a revocation or failed save');
 const rows=[...card.shadowRoot.querySelectorAll('[data-r6-session-data] tr')];assert.equal(rows.length,4);if(water==='')assert.match(rows[0].textContent,/Unknown/);else assert.match(rows[0].cells[1].textContent,new RegExp('^'+water+'\\s*ml'));assert.match(rows[1].textContent,/100\s*ml/);assert.match(rows[2].textContent,/0\s*ml/);assert.match(rows[3].textContent,/Unknown/);assert.match(rows[1].textContent,/Manual entry/);
 const weekly=[...card.shadowRoot.querySelectorAll('.stats-grid .stat-box')][2];assert(weekly);assert.equal(Number(weekly.querySelector('.stat-num').textContent.replace(',','.')),(100+(water?Number(water):0))/1000);assert.match(weekly.textContent,water===''?/2\/4 known/:/3\/4 known/);
 observer.disconnect();card.remove();dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
""")
