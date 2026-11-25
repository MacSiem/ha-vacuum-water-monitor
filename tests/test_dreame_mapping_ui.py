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
 dom.window.close();
}
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
