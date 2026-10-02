const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 const dom=new JSDOM('<html></html>',{runScripts:'dangerously',url:'http://localhost/'});
 try {
  dom.window.eval(fs.readFileSync(file,'utf8'));
  const card=dom.window.document.createElement('ha-vacuum-water-monitor');
  card._serverState={settings:{},tank_states:{'vacuum.qa':{used_ml:100,automatic_sessions:[{ts:1,water:10}]}}};
  let eventHandler; let busAttempts=0;
  card._hass={user:{is_admin:false},states:{},connection:{
   subscribeEvents:async()=>{busAttempts++;throw {code:'unauthorized'};},
   subscribeMessage:async(callback,message)=>{
    if(message.type!=='ha_vacuum_water_monitor/subscribe')throw {code:'unknown_command'};
    eventHandler=callback;return ()=>{};
   }
  },callWS:async()=>({robots:[]})};
  card._subscribeServerEvents();
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(typeof eventHandler,'function','household receives scoped updates without an admin-only bus subscription');
  eventHandler({data:{partial:true,tank_states:{'vacuum.qa':{used_ml:175}}}});
  assert.equal(card._serverState.tank_states['vacuum.qa'].used_ml,175);
  assert.equal(card._serverState.tank_states['vacuum.qa'].automatic_sessions[0].water,10,'compact updates preserve retained history');
  assert.equal(busAttempts,0);
 } finally {dom.window.close();}
}console.log('Household event model updated immediately; history preserved in both shipped cards');})().catch(error=>{console.error(error);process.exitCode=1;});
