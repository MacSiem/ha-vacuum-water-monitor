const {JSDOM}=require('jsdom');const fs=require('fs');const assert=require('node:assert/strict');const settle=()=>new Promise(r=>setImmediate(r));
(async()=>{for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 const dom=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});dom.window.eval(fs.readFileSync(file,'utf8'));
 let settings={warning_threshold:30,critical_threshold:15,sharing_intro_choice:'not_now'},calls=[];
 const c=dom.window.document.createElement('ha-vacuum-water-monitor');c.setConfig({devices:[{vacuum_entity:'vacuum.demo',water_total_ml:4000}]});
 c._hass={states:{'vacuum.demo':{entity_id:'vacuum.demo',state:'docked',attributes:{}}},user:{is_admin:true},callWS:async m=>{calls.push(m);return {settings:settings={...settings,...m.patch}};}};
 c._serverState={settings,tank_states:{}};c._serverReady=true;c._applyServerSettings();assert.equal(c._config.warning_threshold,30,'server overrides defaults');
 dom.window.document.body.append(c);c.setActiveTab('settings');let sr=c.shadowRoot;
 assert.ok(sr.querySelector('#vwm-settings-calibration [data-learning-status]'), 'learning status has its home in calibration settings');
 assert.equal(sr.querySelectorAll('.settings-toc a').length,6);assert.equal(sr.querySelector('.signal-summary').open,false);
 sr.querySelector('#vwm-warning-threshold').value='40';sr.querySelector('#vwm-critical-threshold').value='12';sr.querySelector('#vwm-save-thresholds').click();await settle();assert.equal(settings.warning_threshold,40);assert.equal(c._config.critical_threshold,12);
 sr=c.shadowRoot;sr.querySelector('#vwm-critical-threshold').value='80';sr.querySelector('#vwm-save-thresholds').click();await settle();assert.equal(calls.length,1,'invalid pair never sent');assert.ok(sr.querySelector('#vwm-threshold-status').textContent);
 c._authoredConfigKeys.add('warning_threshold');c._config.warning_threshold=77;c._applyServerSettings();assert.equal(c._config.warning_threshold,77);c._render();assert.match(c.shadowRoot.querySelector('#vwm-settings-thresholds').textContent,/YAML/);
 c._hass.user.is_admin=false;c._render();assert.equal(c.shadowRoot.querySelector('#vwm-save-thresholds').disabled,true);
 dom.window.close();
}console.log('V7 sections and V8 threshold edits/validation/YAML/role PASS');})().catch(e=>{console.error(e);process.exitCode=1;});
