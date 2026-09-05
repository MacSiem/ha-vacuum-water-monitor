"""Portable import must not turn v1 evidence or v2 labels into active rates."""
from copy import deepcopy
import unittest
from test_consumption_import import m, bundle
from test_profile_selection import profile, context, p


def v2_bundle(records):
    b=bundle(records)
    b['payload']['schema_version']=b['manifest']['schema_version']=2
    import hashlib
    b['manifest']['payload_sha256']=hashlib.sha256(m.canonical(b['payload'])).hexdigest()
    return b


class PortableV2Tests(unittest.TestCase):
    def test_v1_profiles_never_become_runtime_profiles(self):
        r=profile()
        with self.assertRaises(ValueError):m.compile_snapshot(bundle([r]))
        self.assertEqual(p.resolve_consumption_profile(context(),{'area_m2':10},dataset={'schema_version':1,'profiles':[r]})['source'],'unknown')

    def test_v2_evidence_only_bundle_and_unknown_schema(self):
        self.assertEqual(m.compile_snapshot(v2_bundle([]))['profiles'],[])
        b=v2_bundle([]);b['manifest']['schema_version']=True
        with self.assertRaises(ValueError):m.compile_snapshot(b)

    def test_label_only_profile_is_rejected(self):
        r={'kind':'profile','id':'fake','review':{'status':'approved'},'confidence':'validated','evidence_class':'empirical','accounting_contract':'v2'}
        with self.assertRaises(ValueError):m.compile_snapshot(v2_bundle([r]))

    def test_private_calibration_survives_unknown_dataset_version(self):
        r=profile();r['device_id']='vacuum.test';ctx=context();ctx['device_id']='vacuum.test'
        result=p.resolve_consumption_profile(ctx,{'area_m2':10},r,{'schema_version':999,'profiles':[]})
        self.assertEqual(result['source'],'device_calibration')

    def test_shared_v2_needs_empirical_and_accounting_contract(self):
        for field,value in [('evidence_class','declared'),('accounting_contract','missing')]:
            r=profile();r.update(evidence_class='empirical',accounting_contract='v2');r[field]=value
            result=p.resolve_consumption_profile(context(),{'area_m2':10},dataset={'schema_version':2,'profiles':[r]})
            self.assertEqual(result['source'],'unknown')

    def test_measured_v2_compilation_and_holdout_metrics(self):
        r=profile()
        train=r['validation']['training_ids'];hold=r['validation']['validation_ids']
        r['evidence_ids']=train+hold
        r['validation'].update(max_error_ml=0,max_relative_error=0)
        observations=[]
        for i,key in enumerate(train+hold):
            observations.append({'id':key,'kind':'observation','context':deepcopy(r['context']),
                'evidence_class':'empirical','confidence':'measured','provenance':deepcopy(r['provenance']),
                'measurement':{'series_id':'train_device' if i<3 else 'hold_device_'+str(i%2),
                    'cycle_id':str(i),'scope':'floor_only','exposure_unit':'m2','exposure':10,
                    'observed_ml':100,'instrument_resolution_ml':1,'settings_constant':True,
                    'interrupted':False,'publication_consent':True,'split':'train' if i<3 else 'validation'}})
        result=m.compile_snapshot(v2_bundle([r,*observations]))
        self.assertEqual(len(result['profiles']),1)
        # The compiler is not the public schema validator: CLI additionally
        # requires verified integration/settings/model records from trusted repo.
        bad=deepcopy(r);bad['validation']['max_error_ml']=5
        with self.assertRaises(ValueError):m.compile_snapshot(v2_bundle([bad,*observations]))
        bad_observations=deepcopy(observations)
        bad_observations[-1]['measurement']['series_id']='train_device'
        with self.assertRaises(ValueError):m.compile_snapshot(v2_bundle([r,*bad_observations]))

    def test_portable_envelope_is_bound_to_actual_source_bundle(self):
        import hashlib
        source=bundle([{'id':'evidence','kind':'observation'}])
        envelope={'schema_version':2,'envelope_kind':'portable_import',
                  'source_payload_sha256':source['manifest']['payload_sha256'],
                  'records':deepcopy(source['payload']['records'])}
        result=m.compile_portable(envelope,source)
        self.assertEqual(result['schema_version'],2)
        self.assertEqual(result['source_payload_sha256'],source['manifest']['payload_sha256'])
        for mutate in [lambda e:e.update(source_payload_sha256='0'*64),
                       lambda e:e['records'][0].update(id='different'),
                       lambda e:e.update(extra='unsupported'),lambda e:e.update(records=[])]:
            bad=deepcopy(envelope);mutate(bad)
            with self.assertRaises(ValueError):m.compile_portable(bad,source)
