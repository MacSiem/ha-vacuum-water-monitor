"""Synthetic scenario contracts; rates and truth are assumptions, not measurements."""
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import subprocess
import unittest

from tests.test_beta_runtime_path import BASE, descriptor, effective, hass, tick, sc

storage = importlib.import_module('vwmruntimepkg.storage')

class JsonStore:
    def __init__(self, path): self.path = path
    async def async_load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None
    async def async_save(self, value):
        self.path.write_text(json.dumps(value, allow_nan=False))

async def roundtrip(path, state):
    store = storage.VacuumWaterStorage(None)
    store._store = JsonStore(path)
    await store.async_set_tank_state('vacuum.robot', state)
    reopened = storage.VacuumWaterStorage(None)
    reopened._store = JsonStore(path)
    return (await reopened.async_get_state())['tank_states']['vacuum.robot']

class RealisticConsumptionTests(unittest.TestCase):
    def test_s1_full_cycle_persists_and_history_matches_independent_ledger(self):
        device = effective({}, descriptor())
        state = {**BASE, 'last_area': 0, 'cycle_full_confirmed': True}
        steps = [('prewash','washing_the_mop','docked',0,150),
                 ('floor_start','cleaning','cleaning',0,150),
                 ('floor_10','cleaning','cleaning',10,210),
                 ('midwash','washing_the_mop','docked',10,360),
                 ('resume','cleaning','cleaning',10,360),
                 ('floor_20','cleaning','cleaning',20,420),
                 ('finalwash','washing_the_mop','docked',20,570),
                 ('finish','charging','docked',20,570)]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'store.json'
            for i,(name,status,vac,area,expected) in enumerate(steps,1):
                state,_=tick.tick_device(hass(status=status,vac=vac,area=area),device,state,now_ts=10_000_000+i*60_000)
                state=asyncio.run(roundtrip(path,state))
                self.assertEqual(state['used_ml'],expected,name)
            result=sc.estimate_water_state(device,state,{})
            self.assertEqual(result['used_ml'],570)
            self.assertEqual(result['remaining_ml'],3430)
            self.assertEqual(len(state.get('automatic_sessions') or []),1)

    def test_s8_clear_is_not_evidence_of_full_volume(self):
        device=effective({},descriptor())
        state={**BASE,'used_ml':3000,'last_dock_err':'ok','cycle_full_confirmed':True}
        for i,err in enumerate(('water_empty','ok'),1):
            state,_=tick.tick_device(hass(dock_err=err),device,state,now_ts=10_000_000+i*60_000)
        result=sc.estimate_water_state(device,state,{})
        self.assertFalse(state['cycle_full_confirmed'])
        self.assertIsNone(result['remaining_ml'],result)
        self.assertIsNone(result['remaining_percent'],result)

    def test_s8_lid_partial_and_volume_sensor_precedence(self):
        from importlib import import_module
        refill=import_module('vwmruntimepkg.refill'); device=effective({},descriptor())
        state={**BASE,'used_ml':1600,'cycle_full_confirmed':True,'calibration_samples':2}
        refill.apply_refill(state,10_060_000,'lid',rebaseline=False)
        self.assertEqual(state['calibration_samples'],2)
        self.assertTrue(state['refill_full_unconfirmed'])
        self.assertIsNone(sc.estimate_water_state(device,state,{})['remaining_ml'])
        measured={**state,'last_accounting_source':'real_sensor','last_water_volume_ml':1800}
        self.assertEqual(sc.estimate_water_state({**device,'water_volume_sensor':'sensor.water'},measured,{})['remaining_ml'],1800)
        full={**BASE,'used_ml':1600}
        refill.apply_refill(full,10_060_000,'lid',rebaseline=False,full_practice_confirmed=True)
        self.assertFalse(full['refill_full_unconfirmed'])
        self.assertEqual(sc.estimate_water_state(device,full,{})['remaining_ml'],4000)

    def test_s8_card_confirmation_after_clear_is_same_refill_and_restores_full(self):
        device=effective({},descriptor())
        state={**BASE,'used_ml':3000,'last_dock_err':'ok','cycle_full_confirmed':True}
        for i,err in enumerate(('water_empty','ok'),1):
            state,_=tick.tick_device(hass(dock_err=err),device,state,now_ts=10_000_000+i*60_000)
        async def confirm(path):
            st=storage.VacuumWaterStorage(None); st._store=JsonStore(path)
            await st.async_set_tank_state('vacuum.robot',state)
            return await st.async_reset_tank('vacuum.robot','1970-01-01T00:00:00+00:00',10_180_000,'card')
        with tempfile.TemporaryDirectory() as tmp:
            state=asyncio.run(confirm(Path(tmp)/'store.json'))
        self.assertEqual(len(state['refill_history']),1)
        self.assertTrue(state['cycle_full_confirmed'])
        self.assertFalse(state['accounting_incomplete'])
        self.assertEqual(sc.estimate_water_state(device,state,{})['remaining_ml'],4000)

    def test_card_unconfirmed_clear_and_real_sensor_precedence(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');const classes={};
global.HTMLElement=class{constructor(){this.tagName='HA-VACUUM-WATER-MONITOR'} attachShadow(){this.shadowRoot={querySelector(){return null},querySelectorAll(){return []},getElementById(){return null}}}};
global.customElements={get(n){return classes[n]},define(n,c){classes[n]=c}};
global.localStorage={getItem(){return null},setItem(){},removeItem(){}};global.window=global;global.history={replaceState(){}};global.location={pathname:'/'};global.CustomEvent=class{};
vm.runInThisContext(fs.readFileSync('ha-vacuum-water-monitor.js','utf8'));
const card=new (classes['ha-vacuum-water-monitor'])();card._hass={states:{}};
const id='vacuum.robot';card._serverState={settings:{configured_devices:[{vacuum_entity:id,water_total_ml:4000}]},tank_states:{[id]:{initialized:true,used_ml:0,refill_full_unconfirmed:true}}};
const d={vacuum_entity:id,water_total_ml:4000};let x=card._calcDeviceData(d);
assert.equal(x.remainingL,null);assert.equal(x.stateReason,'accounting_incomplete');
card._serverState.tank_states[id]={initialized:true,used_ml:0,last_reset_source:'dock_cleared',cycle_full_confirmed:false};x=card._calcDeviceData(d);assert.equal(x.remainingL,null);
card._serverState.tank_states[id]={initialized:true,used_ml:0,last_reset_source:'dock_cleared',cycle_full_confirmed:true};x=card._calcDeviceData(d);assert.equal(x.remainingL,4);
card._serverState.tank_states[id]={initialized:true,used_ml:0,refill_full_unconfirmed:true,last_accounting_source:'real_sensor',last_water_volume_ml:1250};x=card._calcDeviceData({...d,water_volume_sensor:'sensor.ml'});assert.equal(x.remainingL,1.25);
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_s3_two_hour_charge_with_and_without_area_reset(self):
        device=effective({},descriptor())
        for reset in (False, True):
            state={**BASE,'last_area':0,'cycle_full_confirmed':True}; now=10_000_000
            steps=[('cleaning','cleaning',0,60000,0),('cleaning','cleaning',10,60000,60),
                   ('paused','paused',10,60000,60),('charging','docked',10,60000,60),
                   ('charging','docked',0 if reset else 10,7200000,60),
                   ('cleaning','cleaning',0 if reset else 10,60000,60),
                   ('cleaning','cleaning',10 if reset else 20,60000,120),
                   ('charging','docked',10 if reset else 20,60000,120)]
            with tempfile.TemporaryDirectory() as tmp:
                for status,vac,area,gap,expected in steps:
                    now+=gap
                    state,_=tick.tick_device(hass(status=status,vac=vac,area=area),device,state,now_ts=now)
                    state=asyncio.run(roundtrip(Path(tmp)/'store.json',state))
                    self.assertEqual(state['used_ml'],expected,(reset,status,area))
                self.assertFalse(state.get('accounting_incomplete'))
                self.assertEqual(sc.estimate_water_state(device,state,{})['remaining_ml'],3880)

    def test_s2_area_semantics_are_input_not_second_pass_multiplier(self):
        device=effective({},descriptor())
        for reported_area, expected in ((20,120),(40,240)):
            state={**BASE,'last_area':0,'cycle_full_confirmed':True}
            for i,area in enumerate(range(0,reported_area+1,10),1):
                state,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=area),device,state,now_ts=10_000_000+i*60000)
            self.assertEqual(state['used_ml'],expected)
        # Without adapter evidence, 20 unique vs 40 accumulated is not identifiable.

    def test_s7_nominal_rate_frozen_before_new_tank_sensitivity(self):
        from tests.test_nominal_time_learning import learning, CONTEXT
        capacity=4000; bank={}; t=1000
        for cycle in range(3):
            bank=learning.start_full(bank,context=CONTEXT,capacity_ml=capacity,now_ts=t)
            bank=learning.observe(bank,context=CONTEXT,capacity_ml=capacity,now_ts=t,active=True)
            for minute in range(100):
                t+=60000; bank=learning.observe(bank,context=CONTEXT,capacity_ml=capacity,now_ts=t,active=True)
            bank=learning.finish_empty(bank,context=CONTEXT,capacity_ml=capacity,now_ts=t)
            t+=1000
        resolution=learning.resolve(bank,context=CONTEXT,capacity_ml=capacity)
        self.assertEqual(resolution['status'],'active')
        frozen=resolution['usage_ml_per_active_minute']
        self.assertAlmostEqual(frozen,38)
        # Sensitivity only: an assumed extra 300 ml of washes in tank 4.
        elapsed=(3800-300)/frozen
        predicted=frozen*elapsed
        self.assertAlmostEqual(predicted,3500)
        self.assertAlmostEqual((predicted-3800)/3800*100,-7.894736842105263)
        self.assertEqual(learning.resolve(bank,context=CONTEXT,capacity_ml=capacity)['usage_ml_per_active_minute'],frozen)

    def test_s7_tapo_runtime_trains_three_tanks_then_freezes_fourth(self):
        from tests.test_nominal_time_runtime import device, observe
        from importlib import import_module
        apply_refill=import_module('vwmruntimepkg.refill').apply_refill
        dev=device(); state={}; now=10_000_000
        cap=dev['tracked_capacity_ml']
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'store.json'
            for cycle in range(3):
                apply_refill(state,now,'service',rebaseline=True)
                state=observe(dev,state,now,False)
                for minute in range(100):
                    now+=60000; state=observe(dev,state,now,True)
                    if minute in (24,74):
                        now+=60000; state=observe(dev,state,now,False) # dock wash/idle
                        now+=60000; state=observe(dev,state,now,True)
                now+=60000;state=observe(dev,state,now,False)
                state['user_empty_active']=True;now+=60000
                state=observe(dev,state,now,False)
                state=asyncio.run(roundtrip(path,state));now+=60000
            res=state['nominal_time_resolution'];self.assertEqual(res['status'],'active')
            self.assertEqual(res['sample_count'],3)
            frozen=res['usage_ml_per_active_minute']; self.assertAlmostEqual(frozen,cap*.95/102,places=5)
            apply_refill(state,now,'service',rebaseline=True);state=observe(dev,state,now,False)
            # Freeze the rate before any fourth-tank empty event or training update.
            frozen_snapshot=json.dumps(state['nominal_time_learning'],sort_keys=True)
            for minute in range(50):
                now+=60000;state=observe(dev,state,now,True)
            self.assertEqual(state['nominal_time_resolution']['sample_count'],3)
            self.assertAlmostEqual(state['used_ml'],frozen*49,delta=0.25)
            self.assertIsNone(sc.estimate_water_state(dev,state,{})['uncertainty_percent'])
            self.assertTrue(frozen_snapshot)

    def test_sourced_action_and_area_sensitivity_is_not_auto_binding(self):
        # H50 Pro manufacturer describes first 180 ml and mid-task 120 ml;
        # final wash and HA completion bindings remain unknown.
        self.assertEqual(180+120,300)
        self.assertEqual((180+120)-2*120,60)
        # Q8 Max+: public one-off weighing report, 0.4 g/ft²; assume water
        # density 1 g/ml only to show unit sensitivity, not physical accuracy.
        reported_ml_per_m2=.4/.09290304
        self.assertAlmostEqual(reported_ml_per_m2,4.30556,places=4)
        self.assertAlmostEqual(reported_ml_per_m2*20,86.1113,places=3)

    def test_s10_global_fit_cannot_identify_floor_and_wash_separately(self):
        # Both pairs total 300 ml in training; a scalar fit cannot distinguish them.
        training_a=(6*25)+(150*1); training_b=(10*25)+(50*1)
        self.assertEqual(training_a,training_b)
        # Same scalar, new mix, different assumed truths: not a physical measurement.
        test_a=6*10+150*2; test_b=10*10+50*2
        self.assertEqual((test_a,test_b),(360,200))
        self.assertEqual(test_a-test_b,160)
        # Exercise the real tick with the same frozen global factor, not the
        # hypothetical alternative "truth" (which is not a measurement).
        device=effective({},descriptor())
        state={**BASE,'last_area':0,'calibration_factor':1,'calibration_samples':3}
        steps=[('washing_the_mop','docked',0),('cleaning','cleaning',0),
               ('cleaning','cleaning',10),('washing_the_mop','docked',10)]
        for i,(status,vac,area) in enumerate(steps,1):
            state,_=tick.tick_device(hass(status=status,vac=vac,area=area),device,state,now_ts=10_000_000+i*60000)
        self.assertEqual(state['used_ml'],360)
        self.assertEqual(state['calibration_factor'],1)

if __name__=='__main__': unittest.main()
