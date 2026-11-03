"""Standalone public panel places only an explicitly previewed dashboard card."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DashboardPlacementTests(unittest.TestCase):
    def test_preview_add_undo_and_foreign_change(self):
        script = r"""
const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('assert/strict');
const delay=()=>new Promise(r=>setTimeout(r,15)),copy=x=>JSON.parse(JSON.stringify(x));
(async()=>{const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'dangerously',url:'https://qa.invalid/lovelace/home',pretendToBeVisual:true}),w=dom.window;
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js','utf8'));
 w.eval(fs.readFileSync('custom_components/ha_vacuum_water_monitor/www/vwm-panel.js','utf8').replace("import './ha-vacuum-water-monitor.js';",''));
 const backups={};let holdBackup=false,releaseBackup,holdPrepare=false,releasePrepare;let stored={title:'Existing',foreign:{keep:true},views:[{title:'Home',type:'sections',sections:[{type:'grid',cards:[]}]}]},owner;const initial=copy(stored),calls=[];
 const yes={visible:true,read:true,execute:true},hass={user:{id:'admin',is_admin:true,is_active:true},connection:Object.assign(new w.EventTarget(),{connected:true,subscribeMessage:async()=>()=>{}}),connected:true,language:'en',states:{},panels:{lovelace:{config:{mode:'storage'}}},callWS:async m=>{calls.push(copy(m));if(m.type.endsWith('/dashboard_backup_prepare')){const id='b'+Object.keys(backups).length;backups[id]={target:m.target,before:copy(m.before),after:copy(m.after),created:'2026-11-03'};if(holdPrepare)return new Promise(resolve=>{releasePrepare=()=>resolve({id})});return {id}}if(m.type.endsWith('/dashboard_backup_list'))return {backups:Object.entries(backups).map(([id,b])=>({id,target:b.target,created:b.created}))};if(m.type.endsWith('/dashboard_backup_get')){const data=copy(backups[m.backup_id]);if(holdBackup)return new Promise(resolve=>{releaseBackup=()=>resolve(data)});return data}if(m.type==='lovelace/dashboards/list')return [];if(m.type==='lovelace/config')return copy(stored);if(m.type==='lovelace/config/save'){stored=copy(m.config);return null}if(m.type.endsWith('/get_state'))return {settings:{sharing_intro_choice:'not_now'},tank_states:{}};if(m.type.endsWith('/list_vacuums'))return {vacuums:[],balance_links:{}};if(m.type.endsWith('/get_feature_access'))return {capabilities:{water:yes,settings:yes,measurements:yes},resources:{}};if(m.type.endsWith('/health'))return {robots:[]};throw Error(m.type)}};
 const ha=w.document.createElement('home-assistant');ha.provideHass=e=>{e.hass=hass};ha.addEventListener('show-dialog',e=>{owner=w.document.createElement(e.detail.dialogTag);ha.provideHass(owner);owner.showDialog(e.detail.dialogParams);ha.append(owner)});
 const panel=w.document.createElement('vwm-standalone-panel');ha.append(panel);w.document.body.append(ha);panel.hass=hass;await delay();
 panel.shadowRoot.querySelector('[data-place]').click();await delay();let q=s=>owner.querySelector(s);const select=q('[data-dashboard]');select.value='0';select.dispatchEvent(new w.Event('change',{bubbles:true}));await delay();
 const preview=q('[data-preview] ha-vacuum-water-monitor');assert(preview&&preview.preview&&preview.hasAttribute('inert'));const writes=()=>calls.filter(m=>m.type==='lovelace/config/save');assert.equal(writes().length,0);
 q('[data-add]').click();await delay();assert.equal(writes().length,1);assert.equal(stored.views[0].sections[0].cards[0].type,'custom:ha-vacuum-water-monitor');
 q('[data-undo]').click();await delay();assert.deepEqual(stored,initial);assert.equal(writes().length,2);
 select.value='0';select.dispatchEvent(new w.Event('change',{bubbles:true}));await delay();q('[data-add]').click();await delay();assert.equal(writes().length,3);stored.foreign.changed=true;q('[data-undo]').click();await delay();assert.equal(writes().length,3);assert.equal(stored.foreign.changed,true);
 owner.closeDialog();panel.remove();const reopened=w.document.createElement('vwm-standalone-panel');ha.append(reopened);reopened.hass=hass;await delay();reopened.shadowRoot.querySelector('[data-backups]').click();await delay();let ui=reopened.shadowRoot.querySelector('[data-backup-ui]');assert.equal(ui.querySelectorAll('option').length,2);
 ui.querySelector('select').value='b1';holdBackup=true;ui.querySelector('button').click();await delay();assert(releaseBackup);ui.querySelector('select').value='b0';ui.querySelector('select').dispatchEvent(new w.Event('change',{bubbles:true}));releaseBackup();await delay();assert(!ui.textContent.includes('Restore this backup'));holdBackup=false;
 ui.querySelector('select').value='b1';ui.querySelector('select').dispatchEvent(new w.Event('change',{bubbles:true}));ui.querySelector('button').click();await delay();assert.match(ui.textContent,/Dashboard changed/);assert(!ui.textContent.includes('Restore this backup'));
 delete stored.foreign.changed;ui.querySelector('button').click();await delay();assert.match(ui.textContent,/Review the backup/);[...ui.querySelectorAll('button')].find(b=>b.textContent==='Restore this backup').click();await delay();assert.deepEqual(stored,initial);assert.equal(writes().length,4);
 reopened.shadowRoot.querySelector('[data-place]').click();await delay();q=s=>owner.querySelector(s);const selected=q('[data-dashboard]');selected.value='0';selected.dispatchEvent(new w.Event('change',{bubbles:true}));await delay();holdPrepare=true;q('[data-add]').click();await delay();assert(releasePrepare);stored.foreign.concurrent='keep';releasePrepare();await delay();assert.equal(writes().length,4,'foreign edit during backup must prevent native save');assert.equal(stored.foreign.concurrent,'keep');assert.match(owner.textContent,/Dashboard changed/);
 owner.closeDialog();reopened.remove();dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
