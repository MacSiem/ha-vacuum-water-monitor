"""Tank status and measured-volume distinctions in the rendered card."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DreameMappingUI(unittest.TestCase):
    def test_mapping_and_diagnostics(self):
        script = r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
for (const lang of ['en','pl']) {
 const dom=new JSDOM('<body></body>',{runScripts:'dangerously',url:'http://localhost/'});
 dom.window.eval(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
 const card=dom.window.document.createElement('ha-vacuum-water-monitor');
 card._hass={language:lang,locale:{language:lang},states:{}};card._lang=lang;
 const id='vacuum.robot', role='dock_clean_water_sensor', auto='sensor.clean_status', manual='sensor.manual';
 const device={vacuum_entity:id,signals:{[role]:auto},[role]:auto,sibling_entities:[{entity_id:auto,name:'<Status>'},{entity_id:manual,name:'Manual'}]};
 card._serverState={settings:{signal_overrides:{}}};
 let host=dom.window.document.createElement('div');host.innerHTML=card._buildSignalMappingSection(device);
 let select=host.querySelector('#vwm-signal-'+role);
 assert.equal(select.value,'');assert.match(select.options[0].textContent,/sensor.clean_status/);
 assert(host.textContent.includes(lang==='pl'?'a nie o objętości w ml':'not the volume in ml'));
 assert.equal(host.querySelector('status'),null);assert(select.textContent.includes('<Status>'));
 card._serverState.settings.signal_overrides[id]={[role]:manual};
 host.innerHTML=card._buildSignalMappingSection({...device,[role]:manual,signals:{[role]:manual}});
 select=host.querySelector('#vwm-signal-'+role);assert.equal(select.value,manual);assert(!select.options[0].textContent.includes(manual));
 const data={reservoirLevels:{dock_clean:{volume_ml:null,reason:'volume_sensor_unbound'}},signals:{[role]:auto}};
 host.innerHTML=card._buildDiagnostics(data);
 const human=host.querySelector('.diagnostics-grid').textContent;
 assert.match(human,lang==='pl'?/Brak pomiaru objętości/:/No volume measurement/);
 assert.match(human,lang==='pl'?/Stan zbiornika nie podaje ml/:/Tank status does not report ml/);
 assert.match(host.querySelector('#vwm-diagnostic-report').textContent,/dock_clean: .*volume_sensor_unbound/);
 data.reservoirLevels.dock_clean={volume_ml:123};host.innerHTML=card._buildDiagnostics(data);
 assert.match(host.querySelector('.diagnostics-grid').textContent,/123/);
 assert.doesNotMatch(host.querySelector('.diagnostics-grid').textContent,/No volume measurement|Brak pomiaru objętości/);

 // Automatic Dreame status is informational and never becomes an override.
 const dreame={...device,integration_adapter:'dreame_vacuum',signals:{clean_water_tank_status_sensor:auto,dirty_water_tank_status_sensor:'sensor.dirty_status'},dock_clean_water_sensor:undefined};
 card._serverState.settings.signal_overrides={};
 host.innerHTML=card._buildSignalMappingSection(dreame);
 select=host.querySelector('#vwm-signal-'+role);assert.equal(select.value,'');assert(select.options[0].textContent.includes(auto));
 assert(host.querySelector('#vwm-signal-dock_dirty_water_sensor').options[0].textContent.includes('sensor.dirty_status'));
 card._serverState.settings.signal_overrides[id]={[role]:manual};
 host.innerHTML=card._buildSignalMappingSection(dreame);select=host.querySelector('#vwm-signal-'+role);
 assert.equal(select.value,manual);assert(!select.options[0].textContent.includes(auto));
 card.setConfig({vacuum_entity:id,variant:'full'});card._serverState={settings:{},tank_states:{[id]:{clean_tank_advisory:'low_water'}}};
 card._health={[id]:{clean_tank_advisory:'missing'}};card._discoveredVacuums=[];
 const robot={vacuum_entity:id,tracked_reservoir:'dock_clean'};
 for(const variant of ['full','compact','tile']) {
  card._config.variant=variant;
  for(const [state,expected] of [['low_water',lang==='pl'?'niski poziom':'low water'],['missing',lang==='pl'?'brak zbiornika':'tank is missing'],['ok',null],['unknown',null],[null,null]]) {
   card._serverState.tank_states[id].clean_tank_advisory=state;
   const data=card._calcDeviceData(robot);assert.equal(data.cleanTankAdvisory,expected?state:null);
   host.innerHTML=card._buildWaterTab(robot,data);
   if(expected) assert(host.textContent.toLowerCase().includes((variant==='full' ? expected : state==='low_water' ? (lang==='pl'?'mało wody':'low water') : (lang==='pl'?'brak zbiornika':'tank missing')).toLowerCase()));
   else assert(!/Station reports low water|Station reports the clean-water tank is missing|Stacja zgłasza niski poziom|Stacja zgłasza brak zbiornika|Low water · station|Tank missing · station|Mało wody · stacja|Brak zbiornika · stacja/.test(host.textContent));
  }
 }
 delete card._serverState.tank_states[id].clean_tank_advisory;
 assert.equal(card._calcDeviceData(robot).cleanTankAdvisory,'missing');
 assert.equal(card._calcDeviceData({...robot,dock_variant:'plumbed'}).cleanTankAdvisory,null);
 dom.window.close();
}
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
