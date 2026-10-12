const {JSDOM}=require('jsdom');
const fs=require('fs');
const assert=require('node:assert/strict');
let failures=[];
for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 for(const lang of ['pl','en']){
  const dom=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});
  dom.window.eval(fs.readFileSync(file,'utf8'));
  const card=dom.window.document.createElement('ha-vacuum-water-monitor');
  card.setConfig({type:'custom:ha-vacuum-water-monitor',devices:[]}); card._lang=lang;
  const device={vacuum_entity:'vacuum.demo',water_shortage_sensor:'binary_sensor.shortage',dock_clean_water_sensor:'binary_sensor.clean',dock_dirty_water_sensor:'binary_sensor.dirty'};
  card._hass={states:Object.fromEntries(Object.values(device).map(id=>[id,{entity_id:id,state:'off',attributes:{friendly_name:'Demo '+id},last_changed:'2026-10-12T10:00:00Z'}]))};
  card._serverState={settings:{},tank_states:{'vacuum.demo':{water_empty_ts:1791799200}}};
  const base={initialized:true,totalMl:4000,remainingL:2,percentRemaining:50,usedMl:2000,dockCleanWaterState:'off',dockDirtyWaterState:'off',charge:null};
  for(const [name,patch] of Object.entries({empty:{waterEmpty:true},low:{waterLow:true},shortage:{waterShortage:true},clean:{dockCleanWaterProblem:true,dockCleanWaterState:'empty'},removed:{dockCleanWaterProblem:true,dockCleanWaterState:'missing'},dirty:{dockDirtyWaterProblem:true,dockDirtyWaterFull:true,dockDirtyWaterState:'full'},critical:{percentRemaining:5},combined:{waterEmpty:true,waterShortage:true,dockDirtyWaterProblem:true,dockDirtyWaterFull:true,percentRemaining:0}})){
   try{
    const root=dom.window.document.createElement('div'); root.innerHTML=card._buildWaterTab(device,{...base,...patch});
    assert.equal(root.querySelectorAll('.water-alert').length,1,'one shared alert');
    assert.ok(root.querySelectorAll('.water-alert li').length>=1,'reasons');
    assert.ok(root.querySelector('.water-alert [data-alert-source]'),'source');
    assert.ok(root.querySelector('.water-alert time, .water-alert .unknown-time'),'time or explicitly unknown');
    assert.equal(root.querySelectorAll('.water-alert [data-water-action]').length,1,'one action');
    assert.equal(root.querySelectorAll('.alert-banner').length,0,'legacy banner removed');
    assert.ok(!root.textContent.includes('Tracked reservoir is empty.'),'no duplicate guidance');
    if(lang==='pl') assert.match(root.querySelector('.water-alert').textContent,/wod|zbiornik/i);
    if(name==='dirty') assert.ok(!root.querySelector('.water-alert').textContent.includes(lang==='pl' ? 'Napełnij śledzony' : 'Refill the tracked'), 'dirty-only alert must not request a clean-water refill');
    if(name==='combined') assert.ok(root.querySelectorAll('.water-alert li').length>=3,'all concurrent causes');
   }catch(e){failures.push(`${file} ${lang} ${name}: ${e.message}`);}
  }
  dom.window.close();
 }
}
const pl=JSON.parse(fs.readFileSync('custom_components/ha_vacuum_water_monitor/translations/pl.json','utf8'));
try {assert.doesNotMatch(JSON.stringify(pl),/\b(prog|domyslne|ostrzezen|dziala|ladowana|ostrzezenia|integracje)\b/i);for(const flow of ['config','options']) for(const label of Object.values(Object.values(pl[flow].step)[0].data)) assert.match(label,/%/);}catch(e){failures.push('Polish config/options: '+e.message);}
if(failures.length){console.error(failures.join('\n'));process.exitCode=1;}else console.log('V1 alert matrix and V2 Polish translation PASS');
