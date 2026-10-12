const {JSDOM}=require('jsdom');const fs=require('fs');const assert=require('node:assert/strict');
for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 const dom=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});dom.window.eval(fs.readFileSync(file,'utf8'));
 const c=dom.window.document.createElement('ha-vacuum-water-monitor');
 c.setConfig({type:'custom:ha-vacuum-water-monitor',devices:[{vacuum_entity:'vacuum.demo',name:'Demo',water_total_ml:4000,dock_clean_water_sensor:'binary_sensor.clean'}]});
 c._hass={states:{'vacuum.demo':{entity_id:'vacuum.demo',state:'docked',attributes:{}},'binary_sensor.clean':{entity_id:'binary_sensor.clean',state:'off',attributes:{}}},user:{is_admin:true}};
 c._serverReady=true;c._serverState={settings:{sharing_intro_choice:'not_now'},tank_states:{}};dom.window.document.body.append(c);c._render();
 assert.deepEqual([...c.shadowRoot.querySelectorAll('.tab-btn')].map(b=>b.dataset.tab),['water','history','maintenance','settings']);
 const root=c.shadowRoot;assert.ok(root.querySelector('details.water-details'));assert.equal(root.querySelector('details.water-details').open,false);
 assert.ok(root.querySelector('details.dock-status'));assert.equal(root.querySelector('details.dock-status').open,false);
 root.querySelector('#tip-dismiss').click();assert.ok(root.querySelector('#tip-banner').classList.contains('hidden'));root.querySelector('#vwm-help').click();assert.ok(!root.querySelector('#tip-banner').classList.contains('hidden'));
 root.querySelector('[data-tab="water"]').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(c._activeTab,'history');assert.equal(c.shadowRoot.activeElement?.dataset.tab,'history');
 for(const [old,target] of [['stats','history'],['database','settings'],['maintenance','maintenance']]){c.setActiveTab(old);assert.equal(c._activeTab,target);}
 c.setActiveTab('settings');assert.ok(c.shadowRoot.querySelector('#vwm-settings-calibration'));assert.ok(c.shadowRoot.querySelector('#vwm-custom-save'));
 c.setActiveTab('maintenance');assert.equal(c.shadowRoot.querySelector('#vwm-custom-save'),null);
 for(const [old,target] of [['stats','history'],['database','settings']]){dom.window.localStorage.setItem('ha-tools-vacuum-water-monitor-settings',JSON.stringify({_activeTab:old}));const n=dom.window.document.createElement('ha-vacuum-water-monitor');n.setConfig({type:'custom:ha-vacuum-water-monitor'});assert.equal(n._activeTab,target);}
 dom.window.close();
}console.log('V5/V6 layout, keyboard, help and legacy routes PASS');
