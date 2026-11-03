"""Native R5 regressions exercised through the rendered card and events."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativePolicyRegressions(unittest.TestCase):
    def test_denied_singleton_does_not_look_like_first_run(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{for(const lang of ['en','pl'])for(const compact of [false,true])for(const denied of [true,false]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.hidden_robot',yes={visible:true,read:true,execute:true},calls=[];
 const hass={language:lang,locale:{language:lang},user:{id:'u',is_admin:false},states:denied?{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'SECRET ROBOT'}}}:{},
 connection:{subscribeMessage:async()=>()=>{}},callWS:async m=>{calls.push(m.type);if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{}};
 if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[],balance_links:{}};if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');card.setConfig(denied?{vacuum_entity:id,compact}:{compact});
 card._refreshHealth=()=>null;card.hass=hass;dom.window.document.body.append(card);await card._ensureServerState(true);await new Promise(r=>setTimeout(r,30));card._render();
 const text=card.shadowRoot.textContent;
 if(denied){assert.match(text,lang==='pl'?/Brak dostępnych robotów|Brak dostępu/:/No available robots|Access denied/);assert(!/No configured devices|Add a vacuum|Brak skonfigurowanych|Dodaj odkurzacz|SECRET ROBOT|hidden_robot/.test(text));}
 else assert.match(text,lang==='pl'?/Brak skonfigurowanych|Dodaj odkurzacz/:/No configured devices|Add a vacuum/);
 assert(!card.shadowRoot.querySelector('.refill-btn'));assert(!calls.some(x=>x.endsWith('/reset_tank')));dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_consecutive_policy_changes_and_resource_empty_state(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{for(const lang of ['en','pl'])for(const compact of [false,true]){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true},calls=[];let listeners=new Set(),mode='full',used=111,subscribed=0,maxActive=0;
 const caps=()=>({water:{visible:true,read:mode!=='denied',execute:mode==='full'},settings:yes,measurements:yes});
 const access=()=>({capabilities:caps(),resources:mode==='invisible'?{}:{[id]:caps()}});
 const hass={language:lang,locale:{language:lang},user:{id:'member',is_admin:false,is_active:true},
  states:{[id]:{entity_id:id,state:'docked',attributes:{friendly_name:'Robot'}}},
  connection:{subscribeMessage:async cb=>{subscribed++;listeners.add(cb);maxActive=Math.max(maxActive,listeners.size);return ()=>listeners.delete(cb)}},
  callWS:async m=>{calls.push(m.type);if(m.type.endsWith('/get_feature_access'))return access();
   if(m.type.endsWith('/get_state')){if(mode==='denied')throw Object.assign(Error('denied'),{code:'unauthorized'});return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:used}}};}
   if(m.type.endsWith('/list_vacuums'))return {vacuums:mode==='invisible'?[]:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
   if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings:{sharing_intro_choice:'not_now'}};
   if(m.type.endsWith('/reset_tank'))throw Error('unexpected action');throw Error(m.type)}};
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');card.setConfig({vacuum_entity:id,water_total_ml:4000,compact});card._refreshHealth=()=>null;card.hass=hass;dom.window.document.body.append(card);
 await card._ensureServerState(true);await delay(35);assert.equal(listeners.size,1);
 const event=data=>{for(const cb of [...listeners])cb(data)};
 mode='read_only';event({data:{feature_access_changed:true,authorized_vacuums:[id]}});await delay(45);
 let refill=card.shadowRoot.querySelector('.refill-btn');assert(refill&&refill.disabled,'first policy change must disable refill');assert.equal(listeners.size,1);
 mode='full';event({data:{feature_access_changed:true,authorized_vacuums:[id]}});await delay(45);
 refill=card.shadowRoot.querySelector('.refill-btn');assert(refill&&!refill.disabled,'second change must restore refill');assert.equal(listeners.size,1);
 mode='denied';const revoked=[...listeners];listeners.clear();for(const cb of revoked)cb({access_revoked:true});await delay(20);assert.equal(Object.keys(card._serverState.tank_states).length,0);
 assert.match(card.shadowRoot.textContent,lang==='pl'?/Brak dostępu/:/Access denied/);assert.equal(listeners.size,0);
 mode='full';used=222;hass.states[id]={...hass.states[id],state:'cleaning'};card.hass={...hass,states:{...hass.states}};await delay(55);
 assert.equal(card._serverState.tank_states[id].used_ml,222);assert.equal(listeners.size,1);assert(maxActive<=1);
 assert(!calls.some(x=>x.endsWith('/reset_tank')));assert.equal(subscribed,2);
 mode='invisible';event({data:{feature_access_changed:true,authorized_vacuums:[]}});await delay(45);
 const text=card.shadowRoot.textContent;assert.match(text,lang==='pl'?/Brak dostępnych robotów|Brak dostępu/:/No available robots|Access denied/);
 assert(!/No configured devices|Add a vacuum|Brak skonfigurowanych|Dodaj odkurzacz/.test(text));assert(!card.shadowRoot.querySelector('.refill-btn'));
 dom.window.close();
}})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disconnect_and_reconnect_leave_exactly_one_subscription(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const id='vacuum.robot',yes={visible:true,read:true,execute:true};let callbacks=new Set(),resolveFirst,first=true,unsubs=0;
 const hass={language:'en',user:{id:'member',is_admin:false},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},
 connection:{subscribeMessage:cb=>{callbacks.add(cb);const unsub=()=>{unsubs++;callbacks.delete(cb)};if(first){first=false;return new Promise(resolve=>{resolveFirst=()=>resolve(unsub)})}return Promise.resolve(unsub)}},
 callWS:async m=>{if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
 if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:123}}};
 if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
 if(m.type.endsWith('/health'))return {robots:[]};if(m.type.endsWith('/set_settings'))return {settings:{sharing_intro_choice:'not_now'}};throw Error(m.type)}};
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');card.setConfig({vacuum_entity:id,water_total_ml:4000});card._refreshHealth=()=>null;card.hass=hass;dom.window.document.body.append(card);
 await card._ensureServerState(true);await delay(20);assert(resolveFirst);assert.equal(callbacks.size,1);
 card.remove();dom.window.document.body.append(card);card.hass={...hass,states:{...hass.states}};await delay(20);
 assert.equal(callbacks.size,1,'no overlapping replacement before pending subscribe resolves');
 resolveFirst();await delay(35);assert.equal(unsubs,1);assert.equal(callbacks.size,1);
 card.remove();await delay(10);assert.equal(callbacks.size,0);assert.equal(unsubs,2);dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
