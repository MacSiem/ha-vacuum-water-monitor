const {JSDOM}=require('jsdom');
const fs=require('fs');const assert=require('assert/strict');
for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 const dom=new JSDOM('<html></html>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.localStorage.setItem('ha-tools-vacuum-water-monitor-settings',JSON.stringify({_activeTab:'history',_activeDeviceIdx:1}));
 dom.window.eval(fs.readFileSync(file,'utf8'));
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');
 card.setConfig({type:'custom:ha-vacuum-water-monitor'});
 assert.equal(card._activeTab,'history','ordinary reload must preserve selected History');
 assert.equal(card._activeDeviceIdx,1,'ordinary reload must preserve selected robot');
 const authored=dom.window.document.createElement('ha-vacuum-water-monitor');authored.setConfig({type:'custom:ha-vacuum-water-monitor',default_tab:'settings'});
 assert.equal(authored._activeTab,'settings','explicit starting tab takes precedence');
 dom.window.localStorage.setItem('ha-tools-vacuum-water-monitor-settings',JSON.stringify({_activeTab:'invalid',_activeDeviceIdx:-1}));
 const invalid=dom.window.document.createElement('ha-vacuum-water-monitor');invalid.setConfig({type:'custom:ha-vacuum-water-monitor'});
 assert.equal(invalid._activeTab,'water');assert.equal(invalid._activeDeviceIdx,0);
 dom.window.close();
}
console.log('Saved navigation/reload/explicit default/invalid state PASS, both shipped cards');
