"""A robot shared over Matter and also added natively (5.7.0-beta.7).

The registry cannot prove they are one robot, so the integration only suggests
it; the user confirms in the card (robot_links) or keeps them apart.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from test_beta_runtime_path import discovery, sc

ROOT = Path(__file__).resolve().parents[1]


def registry(*, second_native=False, matter_maker="Roborock"):
    entities = [
        {"entity_id": "vacuum.s8", "platform": "roborock", "device_id": "d1"},
        {"entity_id": "vacuum.robotic_vacuum_cleaner", "platform": "matter", "device_id": "d2"},
    ]
    devices = [
        {"id": "d1", "manufacturer": "Roborock", "model": "roborock.vacuum.a97", "model_id": "a97"},
        {"id": "d2", "manufacturer": matter_maker, "model": "Robotic Vacuum Cleaner", "name": "Robotic Vacuum Cleaner"},
    ]
    if second_native:
        entities.append({"entity_id": "vacuum.q7", "platform": "roborock", "device_id": "d3"})
        devices.append({"id": "d3", "manufacturer": "Roborock", "model": "roborock.vacuum.a40"})
    return discovery.discover_descriptors(entities, devices, {})


def by_entity(descriptors):
    return {d["entity_id"]: d for d in descriptors}


class SuggestionTests(unittest.TestCase):
    def test_matter_robot_of_the_only_native_maker_is_suggested(self):
        d = by_entity(registry())
        self.assertEqual(d["vacuum.robotic_vacuum_cleaner"]["possible_duplicate_of"], "vacuum.s8")
        self.assertNotIn("possible_duplicate_of", d["vacuum.s8"])

    def test_two_native_robots_of_that_maker_are_not_guessed(self):
        d = by_entity(registry(second_native=True))
        self.assertNotIn("possible_duplicate_of", d["vacuum.robotic_vacuum_cleaner"])

    def test_another_maker_is_not_suggested(self):
        d = by_entity(registry(matter_maker="Dreame"))
        self.assertNotIn("possible_duplicate_of", d["vacuum.robotic_vacuum_cleaner"])


class LinkTests(unittest.TestCase):
    def entities(self, links):
        settings = {"robot_links": links} if links is not None else {}
        return sorted(d["vacuum_entity"] for d in sc.build_vacuum_devices(settings, {}, registry()))

    def test_without_a_decision_both_robots_are_kept(self):
        self.assertEqual(self.entities(None), ["vacuum.robotic_vacuum_cleaner", "vacuum.s8"])

    def test_confirmed_duplicate_joins_the_native_robot(self):
        devices = sc.build_vacuum_devices({"robot_links": {"vacuum.robotic_vacuum_cleaner": "vacuum.s8"}}, {}, registry())
        self.assertEqual([d["vacuum_entity"] for d in devices], ["vacuum.s8"])
        self.assertEqual(devices[0]["duplicate_entities"], ["vacuum.robotic_vacuum_cleaner"])

    def test_native_robot_stays_primary_even_when_both_have_a_tank(self):
        tanks = {"vacuum.s8": {"used_ml": 10}, "vacuum.robotic_vacuum_cleaner": {"used_ml": 0}}
        devices = sc.build_vacuum_devices({"robot_links": {"vacuum.robotic_vacuum_cleaner": "vacuum.s8"}}, tanks, registry())
        self.assertEqual([d["vacuum_entity"] for d in devices], ["vacuum.s8"])

    def test_linked_entity_is_never_the_owner_even_with_the_only_history(self):
        tanks = {"vacuum.robotic_vacuum_cleaner": {"used_ml": 500}}
        devices = sc.build_vacuum_devices({"robot_links": {"vacuum.robotic_vacuum_cleaner": "vacuum.s8"}}, tanks, registry())
        self.assertEqual([d["vacuum_entity"] for d in devices], ["vacuum.s8"])

    def test_distinct_keeps_them_apart(self):
        self.assertEqual(self.entities({"vacuum.robotic_vacuum_cleaner": "distinct"}),
                         ["vacuum.robotic_vacuum_cleaner", "vacuum.s8"])


class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = r"""
const fs = require('fs'); const vm = require('vm'); const classes = {};
global.HTMLElement = class { constructor() { this.tagName = 'HA-VACUUM-WATER-MONITOR'; } attachShadow() { this.shadowRoot = { querySelector() { return null; }, querySelectorAll() { return []; } }; } };
global.customElements = { get(n) { return classes[n]; }, define(n, c) { classes[n] = c; } };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} }; global.location = { pathname: '/' }; global.window = global; global.CustomEvent = class {};
vm.runInThisContext(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js', 'utf8'));
const Card = classes['ha-vacuum-water-monitor'];
const make = (links, lang) => {
  const card = new Card();
  card._lang = lang;
  card._discoveredVacuums = [
    { entity_id: 'vacuum.s8', name: 'S8 <b>', identity_group: 'vacuum.s8' },
    { entity_id: 'vacuum.robotic_vacuum_cleaner', name: 'Robotic Vacuum Cleaner', identity_group: 'vacuum.robotic_vacuum_cleaner', possible_duplicate_of: 'vacuum.s8' },
  ];
  card._serverState = { settings: links ? { robot_links: links } : {}, tank_states: {} };
  return card;
};
const out = {
  ask: make(null, 'pl')._duplicateNoticeHtml(),
  askEn: make(null, 'en')._duplicateNoticeHtml(),
  hidden: make({ 'vacuum.robotic_vacuum_cleaner': 'vacuum.s8' }, 'pl')._duplicateNoticeHtml(),
  distinct: make({ 'vacuum.robotic_vacuum_cleaner': 'distinct' }, 'pl')._duplicateNoticeHtml(),
};
const linked = make({ 'vacuum.robotic_vacuum_cleaner': 'vacuum.s8' }, 'pl');
linked._getDeviceCandidates = () => linked._discoveredVacuums.map(v => ({ vacuum_entity: v.entity_id }));
linked._backendDescriptor = (d) => linked._discoveredVacuums.find(v => v.entity_id === d.vacuum_entity);
out.linkedDevices = linked._getDevices().map(d => d.vacuum_entity);
const apart = make({ 'vacuum.robotic_vacuum_cleaner': 'distinct' }, 'pl');
apart._getDeviceCandidates = linked._getDeviceCandidates;
apart._backendDescriptor = linked._backendDescriptor;
out.apartDevices = apart._getDevices().map(d => d.vacuum_entity).sort();
linked._discoveredVacuums[1].identity_group = linked._discoveredVacuums[0].identity_group;
out.apartSharedIdentity = apart._getDevices().map(d => d.vacuum_entity).sort();
const renamed = make(null, 'en');
renamed._serverState.vacuum_aliases = { 'vacuum.old': 'vacuum.s8' };
const authored = { vacuum_entity: 'vacuum.old', water_total_ml: 1234 };
out.renamedConfig = renamed._resolveConfiguredVacuum(authored);
renamed._discoveredVacuums.push({ entity_id: 'vacuum.old', identity_group: 'new-robot' });
out.reusedOldId = renamed._resolveConfiguredVacuum(authored);
renamed._config = {vacuum_entity:'vacuum.old', water_total_ml:1234};
renamed._authoredConfigKeys = new Set(['vacuum_entity','water_total_ml']);
renamed._serverState.ambiguous_vacuum_ids = ['vacuum.old'];
out.blockedConfiguredDevices = renamed._getDevices();
out.blockedConfiguredNotice = renamed._duplicateNoticeHtml();
renamed._serverState.registry_identity_conflicts = [{entity_id:'vacuum.<old>'}];
out.identityConflict = renamed._duplicateNoticeHtml();
console.log(JSON.stringify(out));
"""
        cls.result = json.loads(subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                                               capture_output=True, text=True).stdout)

    def test_card_asks_before_hiding(self):
        self.assertIn("Ukryj duplikat", self.result["ask"])
        self.assertIn('data-target="distinct"', self.result["ask"])
        self.assertIn("Hide the duplicate?", self.result["askEn"])

    def test_names_are_escaped(self):
        self.assertIn("S8 &lt;b&gt;", self.result["ask"])
        self.assertNotIn("S8 <b>", self.result["ask"])

    def test_hidden_duplicate_can_be_shown_again(self):
        self.assertIn("Ukryty duplikat", self.result["hidden"])
        self.assertIn("Pokaż", self.result["hidden"])
        self.assertNotIn("Ukryj duplikat", self.result["hidden"])

    def test_distinct_decision_is_not_asked_again(self):
        self.assertEqual(self.result["distinct"], "")

    def test_linked_duplicate_is_not_a_separate_device_tab(self):
        self.assertEqual(self.result["linkedDevices"], ["vacuum.s8"])
        self.assertEqual(self.result["apartDevices"], ["vacuum.robotic_vacuum_cleaner", "vacuum.s8"])
        self.assertEqual(self.result["apartSharedIdentity"], ["vacuum.robotic_vacuum_cleaner", "vacuum.s8"])

    def test_rename_resolves_authored_config_without_retargeting_reused_id(self):
        self.assertEqual(self.result["renamedConfig"], {"vacuum_entity": "vacuum.s8", "water_total_ml": 1234})
        self.assertEqual(self.result["reusedOldId"], {"vacuum_entity": "vacuum.old", "water_total_ml": 1234})
        self.assertEqual(self.result["blockedConfiguredDevices"], [])
        self.assertIn('Card paused', self.result["blockedConfiguredNotice"])
        self.assertIn('history for', self.result["identityConflict"].lower())
        self.assertIn('vacuum.&lt;old&gt;', self.result["identityConflict"])

    def test_registry_event_fetches_new_state_and_renders_without_reload(self):
        script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert'), classes = {};
global.HTMLElement = class {attachShadow(){this.shadowRoot={querySelector(){return null},querySelectorAll(){return []}}}};
global.customElements={get:n=>classes[n],define:(n,c)=>classes[n]=c};
global.localStorage={getItem(){return null},setItem(){},removeItem(){}};
global.window=global; global.history={replaceState(){}};global.location={pathname:'/'};global.CustomEvent=class {};
vm.runInThisContext(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
(async()=>{
 const c=new classes['ha-vacuum-water-monitor'](); let handler, renders=0; const calls=[];
 c._config={}; c._serverState={settings:{},tank_states:{}}; c._discoveredVacuums=[];
 c._render=()=>renders++; c._refreshHealth=()=>{}; c._applyServerSettings=()=>{};
 c._hass={states:{},connection:{subscribeMessage:async cb=>{handler=cb;return ()=>{}}},callWS:async msg=>{
   calls.push(msg.type); if(msg.type.endsWith('/get_state')) return {settings:{},tank_states:{'vacuum.new':{used_ml:42}},vacuum_aliases:{'vacuum.old':'vacuum.new'}};
   if(msg.type.endsWith('/list_vacuums')) return {vacuums:[{entity_id:'vacuum.new'}]}; throw Error(msg.type);
 }};
 c._subscribeServerEvents(); await new Promise(r=>setTimeout(r,0));
 handler({data:{registry_rename:{old:'vacuum.old',new:'vacuum.new'}}});
 await new Promise(r=>setTimeout(r,30));
 assert(calls.some(x=>x.endsWith('/get_state'))); assert(calls.some(x=>x.endsWith('/list_vacuums')));
 assert.equal(c._serverState.tank_states['vacuum.new'].used_ml,42); assert(renders>0);
})().catch(e=>{console.error(e);process.exit(1)});
"""
        subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_reused_id_in_authored_card_renders_no_robot_action(self):
        script = r"""
const {JSDOM}=require('jsdom'), fs=require('fs'), assert=require('assert/strict');
const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'http://localhost/'});
dom.window.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
const card=dom.window.document.createElement('ha-vacuum-water-monitor');
card.setConfig({vacuum_entity:'vacuum.old',water_total_ml:1234,compact:true});
let writes=[]; card._hass={language:'en',locale:{language:'en'},states:{'vacuum.old':{state:'docked',attributes:{}}},
 user:{is_admin:true},callWS:async msg=>{writes.push(msg);return {}},connection:{subscribeMessage:async()=>()=>{}}};
card._serverState={settings:{},tank_states:{'vacuum.old':{used_ml:99}},ambiguous_vacuum_ids:['vacuum.old']};
card._discoveredVacuums=[{entity_id:'vacuum.old',identity_group:'independent-b'}];
card._ensureServerState=()=>null;card._refreshHealth=()=>null;dom.window.document.body.append(card);card._render();
assert.match(card.shadowRoot.textContent,/Card paused/);
assert.equal(card.shadowRoot.querySelector('.refill-btn'),null);
assert.equal(card._getDevices().length,0);assert.equal(writes.length,0);dom.window.close();
"""
        subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
