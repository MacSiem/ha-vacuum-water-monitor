"""Actual card access editor and revocation behavior."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AccessPolicyUiTests(unittest.TestCase):
    def test_admin_edits_scope_and_revoked_user_loses_cached_content(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 for(const lang of ['en','pl']){
  const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
  dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
  const id='vacuum.robot', calls=[];let callback, holdState=false, resolveState, liveUsed=123;
  const policy={schema:1,features:{}};
  const yes={visible:true,read:true,execute:true};
  let access={policy,capabilities:{water:yes,settings:yes,measurements:yes},resources:{[id]:{water:yes,settings:yes,measurements:yes}}};
  const hass={language:lang,locale:{language:lang},user:{id:'admin',is_admin:true,is_active:true},states:{[id]:{entity_id:id,state:'docked',attributes:{}}},
   connection:{subscribeMessage:async cb=>{callback=cb;return ()=>{}}},callWS:async m=>{
    calls.push(structuredClone(m));
    if(m.type.endsWith('/get_feature_access'))return structuredClone(access);
    if(m.type.endsWith('/get_state')){
      const state={settings:{sharing_intro_choice:'not_now'},tank_states:{[id]:{initialized:true,used_ml:liveUsed,automatic_sessions:[{ts:123,water:19}]}}};
      if(holdState)return await new Promise(resolve=>{resolveState=()=>resolve(state)});
      return state;
    }
    if(m.type.endsWith('/list_vacuums'))return {vacuums:[{entity_id:id,name:'Robot',identity_group:id}],balance_links:{}};
    if(m.type.endsWith('/health'))return {robots:[]};
    if(m.type.endsWith('/set_feature_access')){access.policy=structuredClone(m.policy);return {policy:m.policy};}
    if(m.type.endsWith('/set_settings'))return {settings:{sharing_intro_choice:'not_now'},bindings_refreshed:true};
    throw Error(m.type);
   }};
  const card=dom.window.document.createElement('ha-vacuum-water-monitor');card.setConfig({vacuum_entity:id,default_tab:'settings'});
  card._refreshHealth=()=>null;card.hass=hass;dom.window.document.body.append(card);
  await card._ensureServerState(true);await new Promise(r=>setTimeout(r,30));card._render();
  assert(callback);liveUsed=222;callback({data:{state_changed:true,authorized_vacuums:[id]}});
  await new Promise(r=>setTimeout(r,40));assert.equal(card._serverState.tank_states[id].used_ml,222);
  const row=card.shadowRoot.querySelector('[data-feature="water"][data-operation="execute"]');assert(row);
  row.querySelector('[data-access-mode]').value='selected_users';row.querySelector('[data-access-users]').value='user-1';
  row.querySelector('[data-access-limit]').checked=true;row.querySelector('[data-access-entities]').value=id;
  const empty=card.shadowRoot.querySelector('[data-feature="settings"][data-operation="read"]');empty.querySelector('[data-access-limit]').checked=true;
  card.shadowRoot.getElementById('vwm-access-save').click();await new Promise(r=>setTimeout(r,30));
  const saved=calls.find(m=>m.type.endsWith('/set_feature_access'));assert(saved);
  assert.deepEqual(saved.policy.features.water.execute,{mode:'selected_users',user_ids:['user-1'],entity_ids:[id]});
  assert.deepEqual(saved.policy.features.settings.read,{mode:'inherit',entity_ids:[]});
  assert(callback);holdState=true;
  const pending=card._ensureServerState(true);await new Promise(r=>setTimeout(r,0));assert(resolveState);
  callback({access_revoked:true});resolveState();await pending;await new Promise(r=>setTimeout(r,10));
  assert.equal(card._accessDenied,true);
  assert.equal(Object.keys(card._serverState.tank_states).length,0);
  assert.match(card.shadowRoot.textContent,lang==='pl'?/Brak dostępu/:/Access denied/);
  assert(!card.shadowRoot.textContent.includes('222'));
  dom.window.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
