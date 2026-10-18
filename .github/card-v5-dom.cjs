// Standalone RED/GREEN harness. Run under the owner's FIFO receipt on frozen sources.
// VWM_CARD_FILE=<baseline or candidate JS> node .github/card-v5-dom.cjs
const {JSDOM}=require('jsdom');
const fs=require('fs');const assert=require('assert/strict');
const source=fs.readFileSync(process.env.VWM_CARD_FILE || 'ha-vacuum-water-monitor.js','utf8');
const tests=[];const test=(name,fn)=>tests.push([name,fn]);
function fixture(language='en',config={}) {
 const dom=new JSDOM('<!doctype html><html><body></body></html>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(source);
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');
 card.setConfig({type:'custom:ha-vacuum-water-monitor',...config});
 card._lang=language;card._hass={language,locale:{language,time_format:'24',time_zone:'server'},config:{time_zone:'Europe/Warsaw'},states:{},user:{is_admin:false}};
 const device={vacuum_entity:'vacuum.demo',name:'Robot',water_total_ml:4000};
 const data={totalMl:4000,percentRemaining:null,remainingL:null,usedMl:null,charge:null,stateReason:'missing_time_rate',initialized:false,calibrationHistory:[],refillHistory:[],vacState:'docked'};
 card._getDevices=()=>[device];card._calcDeviceData=()=>data;card._healthFor=()=>null;
 card._ensureServerState=()=>null;dom.window.document.body.append(card);card._render();return {dom,card,device,data,sr:card.shadowRoot};
}
test('unknown state replaces the empty ring in PL and EN',()=>{
 for(const [lang,unknown,refill] of [['pl','Stan zbiornika nieznany','Dolano'],['en','Tank state unknown','Refilled']]) {
  const {dom,sr}=fixture(lang);
  assert.ok(sr.querySelector('.tank-unknown')?.textContent.includes(unknown));
  assert.equal(sr.querySelector('.gauge-wrap svg'),null);
  assert.ok(sr.querySelector('.refill-btn')?.textContent.includes(refill));
  dom.window.close();
 }
});
test('missing rate is visible and refill does not claim to repair it',()=>{
 const {dom,card,data,sr}=fixture('en',{compact:true});
 assert.match(sr.querySelector('.vwm-compact').textContent,/Time consumption rate missing/);
 assert.match(sr.querySelector('.vwm-compact').textContent,/does not provide a consumption rate/);
 data.initialized=false;
 assert.doesNotMatch(card._buildAccountingGuidance(data),/until you press Refilled/);
 dom.window.close();
});
test('compact exposes refill and full card, then restores compact with keyboard focus',()=>{
 const {dom,card,sr}=fixture('pl',{compact:true,default_tab:'history'});
 assert.ok(sr.querySelector('.refill-btn'));assert.ok(sr.querySelector('#vwm-expand'));
 assert.equal(sr.querySelector('[role=tablist]'),null);
 assert.ok(card.getGridOptions().min_columns<=3);assert.equal(card.getGridOptions().rows,'auto');
 sr.querySelector('#vwm-expand').click();
 assert.ok(sr.querySelector('[role=tablist]'));assert.ok(sr.querySelector('#vwm-collapse'));
 sr.querySelector('#vwm-collapse').click();
 assert.equal(sr.activeElement?.id,'vwm-expand');assert.ok(sr.querySelector('.vwm-compact'));
 dom.window.close();
});
test('compact tile reserves a usable narrow height and keeps details behind expansion',()=>{
 const {dom,card,sr}=fixture('en',{compact:true});
 card._duplicateNoticeHtml=()=>'<p data-extra-duplicate>Detailed duplicate controls</p>';
 card._lastHtml='';card._render();
 assert.equal(sr.querySelector('[data-extra-duplicate]'),null);
 assert.equal(sr.querySelector('.device-header'),null);
 assert.equal(card.getGridOptions().columns,6);
 assert.equal(card.getGridOptions().rows,'auto');
 sr.querySelector('#vwm-expand').click();
 assert.ok(sr.querySelector('[data-extra-duplicate]'));assert.ok(sr.querySelector('.device-header'));
 assert.equal(card.getGridOptions().rows,'auto');
 dom.window.close();
});
test('help is one closed summary and remembers explicit close over render/recreation',async()=>{
 const {dom,card,sr}=fixture('en');
 let help=sr.querySelector('details#tip-banner');assert.ok(help);assert.equal(help.open,false);
 assert.equal(help.querySelectorAll(':scope > summary').length,1);
 help.open=true;help.dispatchEvent(new dom.window.Event('toggle'));
 help.open=false;help.dispatchEvent(new dom.window.Event('toggle'));
 card._lastHtml='';card._render();assert.equal(sr.querySelector('#tip-banner').open,false);
 const second=dom.window.document.createElement('ha-vacuum-water-monitor');second.setConfig({});second._hass=card._hass;second._getDevices=card._getDevices;second._calcDeviceData=card._calcDeviceData;second._healthFor=()=>null;second._render();
 assert.equal(second.shadowRoot.querySelector('#tip-banner').open,false);
 card._config.show_help=false;card._render();assert.equal(sr.querySelector('#tip-banner'),null);
 dom.window.close();
});
test('mobile starts with closed help even after wide-screen opening, preserving explicit mobile reading',()=>{
 const {dom,card,sr}=fixture('en');
 let help=sr.querySelector('#tip-banner');help.open=true;help.dispatchEvent(new dom.window.Event('toggle'));
 Object.defineProperty(dom.window,'innerWidth',{configurable:true,value:390});
 card._lastHtml='';card._render();help=sr.querySelector('#tip-banner');assert.equal(help.open,false);
 help.open=true;help.dispatchEvent(new dom.window.Event('toggle'));card._lastHtml='';card._render();
 assert.equal(sr.querySelector('#tip-banner').open,true);
 dom.window.close();
});
test('diagnostic codes are confined to escaped copyable report; evidence retained',async()=>{
 for(const language of ['pl','en']) {
 const {dom,card,sr}=fixture(language);
 const data={reservoirLevels:{dock_clean:{reason:'volume_sensor_unbound'},dock_dirty:{volume_ml:3900}},profileKey:'<script>bad()</script>',profileSource:'model_id',profileConfidence:'high',consumptionResolution:{source:'unknown',reason:'incomplete_context'},lastAccountingInterruption:{ts:1000,reasons:['area_delta_too_large'],area_observation:{raw_value:120,previous_m2:2,current_m2:120,delta_m2:118,ceiling_m2:10,interval_seconds:60,version:'5.11.3'}},nominalTimeResolution:{status:'provisional',sample_count:1,accuracy:'not_established',basis:'nominal_full_to_empty_time'}};
 sr.innerHTML=card._buildDiagnostics(data);
 const human=sr.querySelector('.diagnostics-grid').textContent;
 assert.doesNotMatch(human,/dock_clean|dock_dirty|volume_sensor_unbound|incomplete_context|model_id|area_delta_too_large/);
 assert.match(human,language==='pl'?/Czujnik objętości nieprzypisany/:/Volume sensor not assigned/);
 assert.match(human,/118/);assert.match(human,/120/);assert.match(human,/60/);
 assert.match(human,language==='pl'?/Dokładność nie została ustalona/:/Accuracy has not been established/);
 const report=sr.querySelector('#vwm-diagnostic-report');assert.match(report.textContent,/volume_sensor_unbound/);assert.match(report.textContent,/area_delta_too_large/);assert.equal(sr.querySelector('script'),null);
 let copied;Object.defineProperty(dom.window.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
 card._attachListeners([],{});sr.querySelector('#vwm-copy-diagnostics').click();await Promise.resolve();
 assert.equal(copied,report.textContent);
 dom.window.close();
 }
});
test('visual editor previews all options while retaining unknown keys and device roles',()=>{
 const {dom,card}=fixture('en');
 const editor=dom.window.document.createElement('ha-vacuum-water-monitor-editor');
 const original={type:'custom:ha-vacuum-water-monitor',title:'Original',default_tab:'water',tabs:['water','history','extension-tab'],show_help:true,show_support:true,compact:false,custom_extension:{keep:true},devices:[{vacuum_entity:'vacuum.demo',duration_sensor:'sensor.runtime'}]};
 editor.setConfig(original);let config;editor.addEventListener('config-changed',event=>{config=event.detail.config;});
 const es=editor.shadowRoot;
 es.querySelector('#cf_title').value='Preview title';es.querySelector('#cf_title').dispatchEvent(new dom.window.Event('input'));
 for(const key of ['show_help','show_support','compact']) {const input=es.querySelector('#cf_'+key);assert.ok(input,key);input.checked=key==='compact';input.dispatchEvent(new dom.window.Event('change'));}
 const select=es.querySelector('#cf_default_tab');assert.ok(select);select.value='history';select.dispatchEvent(new dom.window.Event('change'));
 es.querySelector('[data-tab-option=history]').checked=false;es.querySelector('[data-tab-option=history]').dispatchEvent(new dom.window.Event('change'));
 assert.deepEqual(JSON.parse(JSON.stringify(config.custom_extension)),original.custom_extension);
 assert.deepEqual(JSON.parse(JSON.stringify(config.devices)),original.devices);assert.ok(config.tabs.includes('extension-tab'));
 assert.equal(config.default_tab,'water');assert.equal(config.show_help,false);assert.equal(config.show_support,false);assert.equal(config.compact,true);
 card.setConfig(config);card._render();
 assert.match(card.shadowRoot.querySelector('.card-title').textContent,/Preview title/);assert.ok(card.shadowRoot.querySelector('.vwm-compact'));assert.equal(card.shadowRoot.querySelector('#tip-banner'),null);
 dom.window.close();
});
test('editor state refresh preserves a focused draft and offers only visible default tabs',()=>{
 const {dom}=fixture('en');
 const editor=dom.window.document.createElement('ha-vacuum-water-monitor-editor');
 editor.setConfig({tabs:['water','history'],default_tab:'water'});
 editor.hass={language:'en',states:{}};dom.window.document.body.append(editor);
 const input=editor.shadowRoot.querySelector('#cf_title');input.focus();input.value='Editing';input.dispatchEvent(new dom.window.Event('input'));
 editor.hass={language:'en',states:{'sensor.unrelated':{state:'2'}}};
 assert.equal(editor.shadowRoot.activeElement?.id,'cf_title');
 assert.equal(editor.shadowRoot.querySelector('#cf_title').value,'Editing');
 assert.deepEqual([...editor.shadowRoot.querySelector('#cf_default_tab').options].map(option=>option.value),['water','history']);
 dom.window.close();
});
test('tab arrows, Home and End activate and focus visible tabs',()=>{
 const {dom,sr}=fixture('en',{tabs:['water','history','settings']});
 const send=(id,key)=>sr.querySelector('[data-tab='+id+']').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key,bubbles:true}));
 send('water','ArrowRight');assert.equal(sr.activeElement?.dataset.tab,'history');assert.equal(sr.activeElement?.getAttribute('aria-selected'),'true');
 send('history','End');assert.equal(sr.activeElement?.dataset.tab,'settings');
 send('settings','Home');assert.equal(sr.activeElement?.dataset.tab,'water');
 assert.equal(sr.querySelector('[data-tab=maintenance]'),null);
 dom.window.close();
});
test('HA time zone and numeric locale are used in actual visible history output',()=>{
 const {dom,card}=fixture('pl');
 card._getSessionsFromStorage=()=>[{ts:Date.parse('2026-10-18T10:30:00Z'),area:10,water_ml:100,source:'manual'}];
 const html=card._buildHistoryTab({vacuum_entity:'vacuum.demo'},{});
 card.shadowRoot.innerHTML=html;
 assert.match(card.shadowRoot.textContent,/12:30/);
 assert.match(card._formatMl(1234.5),/1[\s\u00a0\u202f]?234,5/);
 dom.window.close();
});
test('active nominal time data removes the unrelated model prior and describes its actual method',()=>{
 const {dom,card,device}=fixture('en');
 delete card._calcDeviceData;
 card._withBackendDescriptor=d=>d;card._backendDescriptor=()=>null;card._effectiveCustomCalibration=()=>({});
 card._serverState={tank_states:{'vacuum.demo':{initialized:true,used_ml:100,last_accounting_evidence:'nominal_full_to_empty_time',nominal_time_resolution:{status:'active',sample_count:3,accuracy:'not_established'}}}};
 const data=card._calcDeviceData({...device,estimate_basis:'class_prior',uncertainty_percent:50});
 assert.equal(data.estimateBasis,null);assert.equal(data.uncertaintyPercent,null);
 assert.equal(data.uncertaintyKind,'nominal_tank_repeatability');
 card.shadowRoot.innerHTML=card._buildDiagnostics(data);
 const human=card.shadowRoot.querySelector('.diagnostics-grid').textContent;
 assert.match(human,/whole-tank depletion per active mopping minute/i);
 assert.doesNotMatch(human,/cleaned area|±50%/);
 dom.window.close();
});
test('partial recorded consumption follows the HA numeric locale',()=>{
 const {dom,card,device,data}=fixture('pl');
 data.partialUsedMl=1250;data.initialized=true;data.stateReason='accounting_incomplete';
 card.shadowRoot.innerHTML=card._buildWaterTab(device,data);
 assert.match(card.shadowRoot.textContent,/1,25 L/);assert.doesNotMatch(card.shadowRoot.textContent,/1\.25 L/);
 dom.window.close();
});
test('recorded history formats decimal summaries, areas and numeric minutes with HA locale',()=>{
 const {dom,card,device}=fixture('pl');
 card._getSessionsFromStorage=()=>[{ts:Date.now(),area:4.5,water:600,duration:45.5}];
 card.shadowRoot.innerHTML=card._buildHistoryTab(device,{});
 const text=card.shadowRoot.textContent;
 assert.match(text,/0,6/);assert.match(text,/4,5 m²/);assert.match(text,/45,5 min/);
 dom.window.close();
});
(async()=>{let failed=0;for(const [name,fn] of tests){try{await fn();console.log('PASS '+name);}catch(error){failed++;console.error('FAIL '+name+'\n'+error.stack);}}if(failed)process.exitCode=1;})();
