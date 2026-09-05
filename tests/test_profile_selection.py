"""Synthetic applicability cases; no fixture becomes a shipped consumption rate."""
import importlib.util
from pathlib import Path
from copy import deepcopy
import unittest

spec = importlib.util.spec_from_file_location('selection_profiles', Path(__file__).resolve().parents[1] / 'custom_components/ha_vacuum_water_monitor/profiles.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def context():
    return {'model_id':'synthetic.model', 'sku':'EU', 'dock_variant':'tank',
            'firmware':'1', 'integration_id':'test', 'integration_version':'1',
            'reservoir':'dock_clean', 'action':'floor_mopping',
            'settings':dict.fromkeys(('mop_mode','water_level','route','passes','wash_mode',
                'wash_frequency','wash_temperature','adaptive_mode','detergent_mode',
                'cleaning_mode','task_scope','suction_level','carpet_policy'), 'confirmed')}


def profile():
    return {'id':'test.profile', 'kind':'profile', 'accounting_contract':'v2', 'evidence_class':'empirical', 'context':context(), 'method':'area',
            'coefficient':10, 'unit':'ml/m2', 'scope':'floor_only', 'evidence_ids':['sample.1'],
            'review':{'status':'approved','reviewer':'reviewer'}, 'confidence':'validated',
            'provenance':[{'type':'empirical','url':'https://example.org/sample','date':'2026-09-05','claim':'Synthetic test input'}],
            'unknowns':[], 'validation':{'training_ids':['train.1','train.2','train.3'], 'validation_ids':['validate.1','validate.2','validate.3','validate.4','validate.5'],
                'device_count':3, 'max_error_ml':5, 'max_relative_error':0.05},
            'exposure_domain':{'min':1,'max':100}}


class SelectionTests(unittest.TestCase):
    def resolve(self, ctx=None, signals=None, calibration=None, profiles=None):
        resolver = getattr(p, 'resolve_consumption_profile', None)
        self.assertTrue(callable(resolver), 'Consumption resolver is missing')
        return resolver(ctx or context(), signals or {'area_m2':10}, calibration,
                        {'schema_version':2,'dataset_version':'test','profiles':profiles if profiles is not None else [profile()]})

    def test_compatible_verified_profile(self):
        r=self.resolve()
        self.assertEqual(r['source'],'verified_model')
        self.assertEqual(r['coefficient'],10)
        self.assertEqual(r['profile_id'],'test.profile')
        self.assertEqual(r['validation']['max_error_ml'],5)

    def test_every_applicability_axis_must_match(self):
        for key in ('model_id','sku','dock_variant','firmware','integration_id','integration_version','reservoir','action'):
            for value in ('different',None):
                with self.subTest(key=key,value=value):
                    ctx=context();ctx[key]=value
                    self.assertEqual(self.resolve(ctx)['source'],'unknown')
        ctx=context();ctx['settings']['route']='new'
        self.assertEqual(self.resolve(ctx)['reason'],'context_mismatch')

    def test_matching_null_is_not_wildcard(self):
        record=profile();record['context']['firmware']=None
        ctx=context();ctx['firmware']=None
        self.assertEqual(self.resolve(ctx,profiles=[record])['source'],'unknown')

    def test_unknown_setting_or_extra_setting_rejected(self):
        for value in (None,'unknown','unavailable'):
            ctx=context();ctx['settings']['water_level']=value
            record=profile();record['context']=deepcopy(ctx)
            self.assertEqual(self.resolve(ctx,profiles=[record])['source'],'unknown')
        ctx=context();ctx['settings']['future_option']='new'
        self.assertEqual(self.resolve(ctx)['source'],'unknown')

    def test_invalid_profile_never_supplies_rate(self):
        for key,value in [('coefficient',float('inf')),('coefficient',True),('unit','ml/min'),
                          ('confidence','synthetic'),('evidence_ids',[]),('provenance',[]),('unknowns',['firmware']),
                          ('review',{'status':'revoked','reviewer':'x'})]:
            with self.subTest(key=key,value=value):
                r=profile();r[key]=value
                self.assertEqual(self.resolve(profiles=[r])['source'],'unknown')

    def test_missing_or_outside_exposure_rejected(self):
        for signals in ({'area_m2':0},{'area_m2':101},{'area_m2':float('nan')},{'time_minutes':10}):
            self.assertEqual(self.resolve(signals=signals)['source'],'unknown')

    def test_conflicting_profiles_fail_closed(self):
        other=profile();other['id']='test.other';other['coefficient']=20
        self.assertEqual(self.resolve(profiles=[profile(),other])['reason'],'ambiguous_profiles')

    def test_personal_calibration_precedes_shared_without_mutation(self):
        local=profile();local.update(device_id='device.a',coefficient=12)
        ctx=context();ctx['device_id']='device.a'
        before=deepcopy(local)
        self.assertEqual(self.resolve(ctx,calibration=local)['source'],'device_calibration')
        self.assertEqual(self.resolve(ctx,calibration=local)['coefficient'],12)
        self.assertEqual(local,before)
        ctx['device_id']='device.b'
        self.assertEqual(self.resolve(ctx,calibration=local)['coefficient'],10)

    def test_real_sensor_precedes_and_unavailable_never_falls_back(self):
        signal={'volume_sensor_configured':True,'volume_ml':0,'reservoir':'dock_clean'}
        self.assertEqual(self.resolve(signals=signal)['source'],'real_sensor')
        signal['volume_ml']=None
        self.assertEqual(self.resolve(signals=signal)['reason'],'real_sensor_unavailable')
        signal['volume_ml']=10;signal['reservoir']='robot_clean'
        self.assertEqual(self.resolve(signals=signal)['reason'],'real_sensor_reservoir_unverified')

    def test_labeled_estimate_requires_exact_named_model_action_and_basis(self):
        estimate={'id':'estimate.h50','kind':'estimate','estimate_readiness':'labeled_runtime_estimate',
                  'label':'Manufacturer-declared, limited estimate','source_type':'manufacturer_declaration',
                  'confidence':'declared_source_limited','basis_kind':'manufacturer_declared_quantity',
                  'basis_ids':['observation.h50'],'method':'Declared wash quantity',
                  'quantity':{'value':180,'unit':'ml/action'},
                  'context':{'model_id':'xiaomi_h50_pro','reservoir':'dock_clean','action':'first_time_mop_wash'},
                  'limitations':['Completion-counter binding'], 'provenance':[{'claim':'Declared quantity'}],
                  'unknowns':['Firmware']}
        ctx=context();ctx.update(model_id='xiaomi_h50_pro',action='first_time_mop_wash')
        dataset={'schema_version':2,'dataset_version':'test','profiles':[],'estimates':[estimate]}
        result=p.resolve_consumption_profile(ctx,{},None,dataset)
        self.assertEqual(result['source'],'manufacturer_data')
        self.assertEqual(result['coefficient'],None)
        ctx['action']='mid_task_mop_wash'
        self.assertEqual(p.resolve_consumption_profile(ctx,{},None,dataset)['source'],'unknown')
        estimate['basis_ids']=[]
        self.assertEqual(p.resolve_consumption_profile(context(),{},None,dataset)['source'],'unknown')

    def test_empty_shipped_snapshot_stays_unknown(self):
        self.assertEqual(self.resolve(profiles=[])['reason'],'no_compatible_profile')

    def test_training_leak_cannot_claim_verified(self):
        r=profile();r['validation']['validation_ids']=['train.1']
        self.assertEqual(self.resolve(profiles=[r])['source'],'unknown')

    def test_shared_scope_and_malformed_metadata_rejected(self):
        for key,value in [('scope','whole_cycle'),('review',[]),('validation',[]),('provenance',[{}]),('evidence_ids','string')]:
            r=profile();r[key]=value
            with self.subTest(key=key):
                self.assertEqual(self.resolve(profiles=[r])['source'],'unknown')

    def test_revoked_personal_profile_is_not_used(self):
        r=profile();r.update(device_id='device.a',coefficient=12)
        r['review']['status']='revoked'
        ctx=context();ctx['device_id']='device.a'
        self.assertEqual(self.resolve(ctx,calibration=r)['coefficient'],10)

    def test_personal_calibrations_are_selected_per_historical_context(self):
        a=profile();a.update(device_id='device.a',coefficient=12)
        b=deepcopy(a);b['context']['settings']['route']='deep';b['coefficient']=18
        ctx=context();ctx['device_id']='device.a'
        self.assertEqual(self.resolve(ctx,calibration=[a,b])['coefficient'],12)
        ctx['settings']['route']='deep'
        self.assertEqual(self.resolve(ctx,calibration=[a,b])['coefficient'],18)

    def test_shared_profile_minimum_cycles_are_enforced(self):
        for key,values in [('training_ids',['train.1']),('validation_ids',['validate.1'])]:
            r=profile();r['validation'][key]=values
            with self.subTest(key=key):
                self.assertEqual(self.resolve(profiles=[r])['source'],'unknown')
