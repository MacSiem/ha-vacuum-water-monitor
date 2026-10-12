const assert=require('node:assert/strict'),fs=require('fs'),{JSDOM}=require('jsdom');
for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js'])for(const lang of ['pl','en']){
 const d=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});d.window.eval(fs.readFileSync(file,'utf8'));const c=d.window.document.createElement('ha-vacuum-water-monitor');c.setConfig({devices:[]});c._lang=lang;
 const root=d.window.document.createElement('div');root.innerHTML=c._buildDiagnostics({lastAccountingInterruption:{ts:1791800000000,reasons:['accounting_context_changed','<img src=x onerror=alert(1)>'],resolved_ts:1791801000000,refill_source:'repair'}});
 assert.match(root.textContent,/accounting_context_changed/,'retained reason appears after repair');assert.equal(root.querySelector('img'),null,'reason codes escaped');assert.match(root.textContent,lang==='pl'?/Ostatnie przerwanie bilansu/:/Last accounting interruption/);
 root.innerHTML=c._buildDiagnostics({});assert.ok(!root.textContent.includes('undefined'));d.window.close();
}console.log('Issue13 retained interruption reason PL/EN and escaping PASS');
