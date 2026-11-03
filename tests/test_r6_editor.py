"""The visual editor keeps authored extension fields and focus during changes."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EditorTests(unittest.TestCase):
    def test_variant_and_tabs_preserve_authored_config_and_focus(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
for(const lang of ['pl','en']){
 const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 const editor=w.document.createElement('ha-vacuum-water-monitor-editor');editor.hass={language:lang};editor.setConfig({title:'Draft',devices:[{vacuum_entity:'vacuum.robot',custom:'kept'}],future:{x:7},tabs:['water','history','future_tab'],default_tab:'history',compact:true});
 let config;editor.addEventListener('config-changed',e=>config=e.detail.config);w.document.body.append(editor);
 const select=editor.shadowRoot.querySelector('#cf_variant');select.value='tile';select.dispatchEvent(new w.Event('change',{bubbles:true}));
 assert.equal(config.variant,'tile');assert.equal(config.compact,true);assert.equal(config.future.x,7);assert.equal(config.devices[0].custom,'kept');assert.equal(editor.shadowRoot.activeElement.id,'cf_variant');
 const history=editor.shadowRoot.querySelector('[data-tab-option=history]');history.checked=false;history.dispatchEvent(new w.Event('change',{bubbles:true}));
 assert(config.tabs.includes('future_tab'));assert.equal(config.default_tab,'water');assert.equal(editor.shadowRoot.activeElement.dataset.tabOption,'history');assert.equal(config.title,'Draft');dom.window.close();
}
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
