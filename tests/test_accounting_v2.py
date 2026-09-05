"""Hand-calculated conservation and hostile event boundaries; no hardware claims."""
import importlib.util
import json
from pathlib import Path
from copy import deepcopy
import unittest

ROOT=Path(__file__).resolve().parents[1]

def engine():
    spec=importlib.util.spec_from_file_location('accounting_v2',ROOT/'custom_components/ha_vacuum_water_monitor/accounting_v2.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def fixture():
    return json.loads((ROOT/'tests/fixtures/portable-v2/synthetic-replay-v2.json').read_text())

class AccountingV2Tests(unittest.TestCase):
    def test_frozen_five_reservoir_replay(self):
        r=engine().replay_synthetic(fixture())
        self.assertEqual(r['balances_ml'],{'dock_clean':1260,'dock_dirty':100,'robot_clean':90,'robot_dirty':50,'detergent':50})
        self.assertEqual(r['external_supply_ml'],300)
        self.assertEqual(r['external_drain_ml'],0)
        self.assertEqual(r['completed_actions'],['wash-1'])
        self.assertEqual(r['aborted_actions'],['wash-2'])
        self.assertEqual(r['segment_accounting'],'unknown_missing_event_segment')
        self.assertFalse(r['runtime_eligible'])

    def test_invalid_event_cannot_be_hidden_by_expected_totals(self):
        mutations=[lambda f:f['events'][0].update(aborted=True),
                   lambda f:f['events'][0]['edges'][0].update(amount_ml=1000),
                   lambda f:f['events'][0]['edges'][0].update(amount_ml=float('nan')),
                   lambda f:f['events'][0]['edges'][0].update(amount_ml=True),
                   lambda f:f['events'][0]['edges'][0].update(to='detergent'),
                   lambda f:f['events'][0]['edges'][0].update(to='robot_clean'),
                   lambda f:f['events'][0].update(completion_evidence='command'),
                   lambda f:f['setting_segments'][1].update(start=4)]
        for mutate in mutations:
            f=fixture();mutate(f)
            with self.subTest(f=f),self.assertRaises(ValueError):engine().replay_synthetic(f)

    def test_persisted_identity_dedup_and_conflicting_replay(self):
        m=engine();f=fixture();s=m.new_balance(f['device_identity'],f['initial_reservoirs'])
        event=f['events'][0]
        s=m.apply_event(s,f['device_identity'],event)
        persisted=json.loads(json.dumps(s))
        self.assertEqual(m.apply_event(persisted,f['device_identity'],event),s)
        changed=deepcopy(event);changed['edges'][0]['amount_ml']=1
        with self.assertRaises(ValueError):m.apply_event(s,f['device_identity'],changed)
        with self.assertRaises(ValueError):m.apply_event(s,{'installation_id':'other','vacuum_id':'same'},event)
        self.assertEqual(s['balances_ml']['dock_clean'],960)

    def test_partial_physical_transfer_is_not_completed_action(self):
        m=engine();f=fixture();s=m.new_balance(f['device_identity'],f['initial_reservoirs'])
        s=m.apply_event(s,f['device_identity'],f['events'][2])
        self.assertEqual(s['completed_actions'],[])
        self.assertEqual(s['balances_ml']['robot_dirty'],10)
        self.assertEqual(s['external_drain_ml'],0)

    def test_external_drain_and_supply_conserve_mass(self):
        m=engine();f=fixture();s=m.new_balance(f['device_identity'],f['initial_reservoirs'])
        e={'id':'drain','completed':False,'aborted':False,'completion_evidence':'none','edges':[{'from':'dock_dirty','to':'external_drain','amount_ml':80}]}
        s=m.apply_event(s,f['device_identity'],e)
        self.assertEqual(s['external_drain_ml'],80)
        self.assertEqual(s['balances_ml']['dock_dirty'],20)
        self.assertEqual(sum(s['balances_ml'].values())+s['external_drain_ml'],1250)

    def test_unknown_source_states_never_become_completion_bindings(self):
        m=engine();source=json.loads((ROOT/'tests/fixtures/portable-v2/source-contracts-2026-09-05.json').read_text())
        result=m.source_readiness(source)
        self.assertEqual(result['verified_completion_count'],0)
        self.assertFalse(result['runtime_eligible'])
        self.assertEqual(result['settings']['carpet_policy'],'not_applicable')


def live_stream():
    f=fixture()
    stream={'schema_version':2,'fixture_class':'physical_event_stream','source_contract_id':'synthetic.contract',
            'device_identity':f['device_identity'],'baseline_id':'baseline.1','observed_at_ms':10000,
            'baseline_at_ms':0,'initial_reservoirs':f['initial_reservoirs'],'setting_segments':f['setting_segments'],
            'context':{'model':'test','firmware':'1','integration':'test','version':'1'},'complete_since_baseline':True,'events':[]}
    for i,e in enumerate(f['events']):
        stream['events'].append({'sequence':i+1,'timestamp_ms':1000*(i+1),'settings_id':'low',
                               'quantity_evidence':'physical_ml','event':e})
    contract={'id':'synthetic.contract','device_identity':f['device_identity'],'context':stream['context'],'source_entity':'sensor.events',
              'source_url':'https://example.org/pinned/abc','completion_evidence':['counter_increment','terminal_event']}
    return stream,contract


class LiveAccountingV2Tests(unittest.TestCase):
    def apply(self,stream=None,previous=None,contract=None,now=10000):
        s,c=live_stream()
        return engine().consume_stream(previous,stream or s,device_identity=s['device_identity'],
                                       context=s['context'],source_entity='sensor.events',contracts=[contract or c],now_ms=now)

    def test_source_bound_segment_replay_survives_restart_and_duplicate_delivery(self):
        s=self.apply()
        self.assertEqual(s['status'],'known')
        self.assertEqual(s['balances_ml']['dock_clean'],1260)
        self.assertEqual(s['segments'][0]['external_supply_ml'],300)
        self.assertEqual(s['segments'][1]['event_ids'],[])
        self.assertEqual(self.apply(previous=json.loads(json.dumps(s))),s)

    def test_stale_unknown_foreign_or_synthetic_sources_have_no_exposed_balance(self):
        cases=[('fixture_class','synthetic_accounting_replay'),('source_contract_id','other'),
               ('complete_since_baseline',False),('observed_at_ms',0),('context',{'firmware':'2'}),
               ('device_identity',{'installation_id':'other','vacuum_id':'other'})]
        for key,value in cases:
            s,c=live_stream();s[key]=value
            with self.subTest(key=key):
                out=self.apply(s,previous=self.apply())
                self.assertEqual(out['status'],'unknown')
                self.assertIsNone(out['balances_ml'])

    def test_stream_gaps_rewrites_and_untimed_segments_are_rejected(self):
        mutations=[lambda s:s['events'][1].update(sequence=3),
                   lambda s:s['events'][1].update(timestamp_ms=500),
                   lambda s:s['events'][0].update(settings_id='high'),
                   lambda s:s['events'][0].update(quantity_evidence='estimated'),
                   lambda s:s['events'][0]['event']['edges'][0].update(amount_ml=1)]
        for mutate in mutations:
            s,c=live_stream();mutate(s)
            with self.subTest(s=s):self.assertEqual(self.apply(s,previous=self.apply())['status'],'unknown')

    def test_return_to_same_settings_keeps_distinct_segments(self):
        stream,contract=live_stream()
        stream['setting_segments']=[{'start':0,'end':2,'settings_id':'low'}, {'start':2,'end':3,'settings_id':'high'}, {'start':3,'end':10,'settings_id':'low'}]
        stream['events'][1]['settings_id']='high'
        result=self.apply(stream)
        self.assertEqual(result['status'],'known')
        self.assertEqual(len(result['segments']),3)
        self.assertEqual(result['segments'][0]['event_ids'],['wash-1'])
        self.assertEqual(result['segments'][2]['event_ids'],['wash-2','plumbed-refill-1'])

    def test_unavailable_then_complete_immutable_stream_recovers(self):
        m=engine();s,c=live_stream();previous=self.apply()
        unknown=m.consume_stream(previous,None,device_identity=s['device_identity'],context=s['context'],source_entity='sensor.events',contracts=[c],now_ms=11000)
        self.assertIsNone(unknown['balances_ml'])
        self.assertEqual(self.apply(previous=unknown)['balances_ml'],previous['balances_ml'])

class TickV2Tests(unittest.TestCase):
    def test_tick_reads_only_trusted_source_and_hides_unavailable_balance(self):
        from test_tick import tick, _Hass, _State
        from unittest.mock import patch
        stream,contract=v3_live()
        device={'vacuum_entity':'vacuum.test','accounting_event_sensor':'sensor.events'}
        hass=_Hass({'vacuum.test':_State('docked'),'sensor.events':_State('ready',{'accounting_stream':stream})})
        binding={'entity_id':'sensor.events','contract_id':'contract.test',
                 'device_identity':deepcopy(stream['device_identity'])}
        with patch.object(tick.accounting_v2,'SOURCE_CONTRACTS',(contract,)):
            with patch.object(tick.accounting_v2,'SOURCE_BINDINGS',(binding,)):
                state=tick.tick_device(hass,device,{},now_ts=1007001)[0]
                self.assertEqual(state['accounting_v2']['balances_ml']['robot_dirty'],50)
                hass.states._values['sensor.events']=_State('unavailable')
                state=tick.tick_device(hass,device,state,now_ts=1007002)[0]
                self.assertIsNone(state['accounting_v2']['balances_ml'])
                self.assertIsNotNone(state['accounting_v2']['journal'])
        # A config dictionary cannot grant itself a trusted binding.
        device['source_contracts']=[contract]
        hass.states._values['sensor.events']=_State('ready',{'accounting_stream':stream})
        state=tick.tick_device(hass,device,{},now_ts=1007001)[0]
        self.assertEqual(state['accounting_v2']['reason'],'source_binding_unverified')

class PrimaryV2BalanceTests(unittest.TestCase):
    def test_source_gap_cannot_show_old_full_tank(self):
        from test_sensor_calculations import estimate_water_state
        device={'accounting_event_sensor':'sensor.events','tracked_reservoir':'dock_clean','tracked_capacity_ml':4000}
        state={'initialized':True,'used_ml':0,'accounting_v2':{'status':'unknown','reason':'stale_event_stream','balances_ml':None}}
        result=estimate_water_state(device,state)
        self.assertIsNone(result['remaining_percent'])
        self.assertIsNone(result['remaining_ml'])
        self.assertEqual(result['state_reason'],'stale_event_stream')
        state['accounting_v2']={'status':'known','balances_ml':{'dock_clean':1260}}
        result=estimate_water_state(device,state)
        self.assertEqual(result['remaining_ml'],1260)
        self.assertIsNone(result['remaining_percent'])
        self.assertIsNone(result['used_ml'])
        device['water_volume_sensor']='sensor.direct';state['last_water_volume_ml']=1300
        self.assertEqual(estimate_water_state(device,state)['remaining_ml'],1300)

class RevisedDatasetTests(unittest.TestCase):
    def replay(self):
        return json.loads((ROOT/'tests/fixtures/portable-v2/dataset-replay-revision2.json').read_text())

    def test_received_v3_epoch_timestamps_conserve_balance(self):
        result=engine().replay_dataset_synthetic(self.replay())
        self.assertEqual(result['balances_ml'],self.replay()['expected_final_reservoirs'])
        self.assertEqual(result['segments'][1]['event_ids'],['wash-2','plumbed-refill-1'])
        self.assertFalse(result['runtime_eligible'])

    def test_out_of_segment_timestamp_is_rejected(self):
        replay=self.replay()
        replay['events'][2]['observed_at_ms']=1003000
        with self.assertRaisesRegex(ValueError,'event_segment_mismatch'):
            engine().replay_dataset_synthetic(replay)
        replay['fixture_class']='physical_event_stream'
        with self.assertRaises(ValueError):engine().replay_dataset_synthetic(replay)

    def test_scoped_capability_inventory_does_not_enable_runtime(self):
        source=json.loads((ROOT/'tests/fixtures/portable-v2/dataset-sources-revision2.json').read_text())
        result=engine().source_readiness(source)
        self.assertFalse(result['runtime_eligible'])
        self.assertEqual(result['verified_completion_count'],0)
        self.assertEqual(result['settings']['carpet_policy'],'unknown')


def v3_live():
    replay=json.loads((ROOT/'tests/fixtures/portable-v2/dataset-replay-revision2.json').read_text())
    replay['fixture_class']='physical_event_stream'
    replay['source_provenance']='physical_ml'
    replay['device_identity'].update(model_id='model.test',sku='sku.test',firmware='fw.test')
    for event in replay['events']:
        event['source_contract_id']='contract.test'
        event['quantity_provenance']='physical_ml'
    scope={'model_id':'model.test','sku':'sku.test','firmware':'fw.test',
           'integration_id':'integration.synthetic','integration_version':'synthetic',
           'domain':'sensor','key':'physical_counter','unit':'ml'}
    contract={'schema_version':2,'fixture_class':'source_contract','hardware_verified':True,
              'verification':{'status':'hardware_verified','evidence':[{'kind':'registry_fixture','source':'https://example.org/proof','recorded_at_ms':1000000}]},
              'sources':['https://example.org/proof'],
              'bindings':[{'id':'contract.test','integration':'integration.synthetic','role':'wash_completion','key':'physical_counter','state':'source_documented_capability_dependent','scope':scope,'source':'https://example.org/proof'}],
              'settings':[{'name':name,'state':'unknown','scope':{**scope,'key':name}} for name in engine().SETTING_NAMES],
              'action_completion':{name:{'disposition':'unknown','evidence':'none','reason':'test boundary','scope':{**scope,'key':name},'source':'https://example.org/proof'} for name in ('wash_mop','tray_clean','flush','refill','detergent_dose')}}
    contract['action_completion']['wash_mop'].update(disposition='complete',evidence='counter_increment')
    return replay,contract


class NativeV3LiveTests(unittest.TestCase):
    @staticmethod
    def binding(replay):
        return {'entity_id':'sensor.events','contract_id':'contract.test',
                'device_identity':deepcopy(replay['device_identity'])}

    def test_exact_hardware_evidence_and_fresh_epoch_stream(self):
        replay,contract=v3_live()
        kwargs={'contracts':[contract],'source_bindings':[self.binding(replay)],
                'source_entity':'sensor.events'}
        result=engine().consume_dataset_live(None,replay,now_ms=1007001,**kwargs)
        self.assertEqual(result['status'],'known')
        self.assertEqual(result['balances_ml'],replay['expected_final_reservoirs'])
        self.assertEqual(result['segments'][1]['event_ids'],['wash-2','plumbed-refill-1'])
        self.assertEqual(engine().consume_dataset_live(result,replay,now_ms=1007002,**kwargs),result)

    def test_flag_only_source_synthetic_and_time_fail_closed(self):
        mutations=[lambda r,c:c.update(verification={'status':'hardware_verified','evidence':[]}),
                   lambda r,c:c['bindings'][0]['scope'].update(firmware='other'),
                   lambda r,c:r.update(source_provenance='synthetic'),
                   lambda r,c:r.update(unreviewed_extension=True),
                   lambda r,c:r['events'][0].update(unreviewed_extension=True),
                   lambda r,c:r['events'][2].update(observed_at_ms=1003000),
                   lambda r,c:r['events'][1].update(observed_at_ms=1001000)]
        for mutate in mutations:
            replay,contract=v3_live();mutate(replay,contract)
            with self.subTest(replay=replay):
                result=engine().consume_dataset_live(None,replay,contracts=[contract],
                    source_bindings=[self.binding(replay)],source_entity='sensor.events',
                    now_ms=1007001)
                self.assertEqual(result['status'],'unknown')
                self.assertIsNone(result['balances_ml'])
        replay,contract=v3_live()
        kwargs={'contracts':[contract],'source_bindings':[self.binding(replay)],
                'source_entity':'sensor.events'}
        self.assertEqual(engine().consume_dataset_live(None,replay,now_ms=1207002,**kwargs)['reason'],'stale_event_stream')
        self.assertEqual(engine().consume_dataset_live(None,replay,now_ms=990000,**kwargs)['reason'],'future_event_stream')

    def test_config_cannot_self_approve_and_rewrite_stays_hidden(self):
        replay,contract=v3_live()
        kwargs={'contracts':[contract],'source_bindings':[self.binding(replay)],
                'source_entity':'sensor.events'}
        known=engine().consume_dataset_live(None,replay,now_ms=1007001,**kwargs)
        changed=deepcopy(replay);changed['events'][0]['edges'][0]['amount_ml']=1
        hidden=engine().consume_dataset_live(known,changed,now_ms=1007002,**kwargs)
        self.assertEqual(hidden['reason'],'rewritten_or_truncated_event_stream')
        self.assertIsNone(hidden['balances_ml'])
        self.assertEqual(engine().consume_dataset_live(None,replay,contracts=[],
            source_bindings=[self.binding(replay)],source_entity='sensor.events',
            now_ms=1007001)['reason'],'source_binding_unverified')
        self.assertEqual(engine().consume_dataset_live(None,replay,contracts=[contract],
            now_ms=1007001)['reason'],'source_entity_unverified')

    def test_incomplete_source_document_cannot_activate_a_binding(self):
        mutations=[lambda c:c.update(sources=[]),
                   lambda c:c['bindings'][0].update(source='https://example.org/other'),
                   lambda c:c.update(settings=c['settings'][:-1]),
                   lambda c:c['settings'][0]['scope'].update(integration_version='other'),
                   lambda c:c['action_completion'].pop('refill'),
                   lambda c:c['verification']['evidence'][0].update(recorded_at_ms=True)]
        for mutate in mutations:
            replay,contract=v3_live();mutate(contract)
            result=engine().consume_dataset_live(None,replay,contracts=[contract],
                source_bindings=[self.binding(replay)],source_entity='sensor.events',
                now_ms=1007001)
            with self.subTest(contract=contract):
                self.assertEqual(result['reason'],'source_binding_unverified')
