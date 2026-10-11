// Real card render/click consumer: persisted interest must never become packet consent.
const {JSDOM}=require('jsdom');
const fs=require('fs');
const assert=require('assert/strict');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 for(const lang of ['pl','en']){
  const dom=new JSDOM('<html></html>',{runScripts:'dangerously',url:'http://localhost/'});
  dom.window.eval(fs.readFileSync(file,'utf8'));
  dom.window.localStorage.setItem('vacuum-water-monitor-tips-v3.0.0','dismissed');
  let settings={local_measurements:{'vacuum.demo':[{id:'sample.1',confirmed:true,observed_ml:100,area_m2:10,purpose:'validation'}]}};
  const calls=[];
  let failSave=false;
  const hass={states:{'vacuum.demo':{state:'docked',attributes:{friendly_name:'Demo'}}},user:{id:'demo',is_admin:true},callWS:async msg=>{
   calls.push(msg);
   if(msg.type==='ha_vacuum_water_monitor/set_settings'){
    if(failSave)throw new Error('offline');
    settings={...settings,...JSON.parse(JSON.stringify(msg.patch))};
    return {settings:JSON.parse(JSON.stringify(settings))};
   }
   if(msg.type==='ha_vacuum_water_monitor/contribution_preview')return {kind:'confirmed_measurement_contribution',publication_consent:false,runtime_eligible:false,samples:[{area_m2:10,measured_ml:100}]};
   throw new Error('Unexpected request '+msg.type);
  }};
  const make=(ready=true,devices=true)=>{
   const c=dom.window.document.createElement('ha-vacuum-water-monitor');
   c.setConfig({type:'custom:ha-vacuum-water-monitor',devices:devices?[{vacuum_entity:'vacuum.demo',name:'Demo'}]:[]});
   c._lang=lang;c._hass=hass;c._serverReady=ready;
   c._serverState={settings:JSON.parse(JSON.stringify(settings)),tank_states:{}};
   c._render();return c;
  };
  let card=make(false);
  assert.equal(card.shadowRoot.querySelector('[data-sharing-choice]'),null,'wait for persisted settings before asking again');
  card._serverReady=true;card._render();
  let sr=card.shadowRoot;
  assert.ok(sr.querySelector('[data-sharing-choice="not_now"]'),'first run must offer an explicit refusal even when old tips were dismissed');
  assert.ok(sr.querySelector('[data-sharing-choice="learn_more"]'),'first run must offer information without consenting');
  assert.match(sr.getElementById('vwm-sharing-intro').textContent,lang==='pl'?/opcjonaln|dobrowoln/i:/optional/i);
  sr.querySelector('[data-sharing-choice="not_now"]').click();await settle();
  assert.equal(settings.sharing_intro_choice,'not_now','refusal must be persisted through the real settings boundary');
  assert.equal(card.shadowRoot.getElementById('vwm-sharing-intro'),null);
  assert.ok(card.shadowRoot.querySelector('[data-tab="water"]'),'refusal cannot remove ordinary tracking');
  assert.equal(calls.length,1,'refusal only saves the preference, never exports');
  assert.equal(settings.local_measurements['vacuum.demo'].length,1);
  card._render({preserveDraft:true});
  assert.equal(card.shadowRoot.getElementById('vwm-sharing-intro'),null,'heartbeat must not repeat the question');
  card=make();
  assert.equal(card.shadowRoot.getElementById('vwm-sharing-intro'),null,'new card/upgrade must read the persisted refusal');
  card.shadowRoot.querySelector('[data-tab="settings"]').click();
  sr=card.shadowRoot;
  assert.ok(sr.getElementById('vwm-sharing-information'),'Settings must let the user revisit the explanation');
  assert.equal(sr.getElementById('cal-share-enabled').checked,false);
  sr.querySelector('[data-sharing-choice="learn_more"]').click();await settle();
  assert.equal(settings.sharing_intro_choice,'learn_more');
  sr=card.shadowRoot;
  assert.equal(sr.getElementById('cal-sharing').open,true);
  assert.equal(sr.getElementById('cal-share-enabled').checked,false,'interest does not enable packet preview or sharing');
  assert.equal(sr.getElementById('cal-share-consent').checked,false);
  assert.equal(sr.getElementById('cal-download').disabled,true);
  assert.deepEqual(calls.map(c=>c.type),['ha_vacuum_water_monitor/set_settings','ha_vacuum_water_monitor/set_settings']);
  sr.getElementById('cal-share-enabled').click();sr.getElementById('cal-preview').click();await settle();
  assert.equal(sr.getElementById('cal-export-preview').hidden,false);
  assert.equal(JSON.parse(sr.getElementById('cal-export-preview').value).publication_consent,false);
  assert.equal(sr.getElementById('cal-download').disabled,true);
  sr.getElementById('cal-share-consent').click();
  assert.equal(sr.getElementById('cal-download').disabled,false);
  card=make();card.shadowRoot.querySelector('[data-tab="settings"]').click();sr=card.shadowRoot;
  assert.equal(sr.getElementById('cal-share-consent').checked,false,'reloading interested preference must not inherit packet consent');
  assert.equal(sr.getElementById('cal-download').disabled,true);
  sr.querySelector('[data-sharing-choice="not_now"]').click();await settle();
  assert.equal(settings.sharing_intro_choice,'not_now','Settings can reverse interest');
  assert.equal(card.shadowRoot.getElementById('cal-share-enabled').checked,false);
  delete settings.sharing_intro_choice;failSave=true;card=make();
  dom.window.console.error=()=>{}; // Expected transport failure; UI error is asserted below.
  card.shadowRoot.querySelector('[data-sharing-choice="not_now"]').click();await settle();
  assert.ok(card.shadowRoot.getElementById('vwm-sharing-intro'),'failed save must not silently dismiss the question');
  assert.ok(card.shadowRoot.getElementById('vwm-sharing-choice-status').textContent.trim());
  assert.equal(card.shadowRoot.querySelector('[data-sharing-choice="not_now"]').disabled,false);
  failSave=false;card=make(true,false);
  card.shadowRoot.querySelector('[data-sharing-choice="learn_more"]').click();await settle();
  assert.ok(card.shadowRoot.getElementById('vwm-sharing-information'),'first run with no robot still explains sharing');
  assert.equal(card.shadowRoot.getElementById('cal-share-consent'),null);
  dom.window.close();
 }
}
console.log('Sharing first-run PL/EN refusal/interest/persistence/no inherited consent/save failure/no-robot PASS, both cards');
})().catch(e=>{console.error(e);process.exitCode=1;});
