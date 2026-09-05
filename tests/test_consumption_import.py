import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('consumption_import',Path(__file__).resolve().parents[1]/'scripts/import_consumption_data.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def bundle(records):
    payload={'schema_version':1,'dataset_version':'test','records':records}
    return {'manifest':{'schema_version':1,'dataset_version':'test','record_count':len(records),'payload_sha256':hashlib.sha256(m.canonical(payload)).hexdigest()},'payload':payload}

class ConsumptionImportTests(unittest.TestCase):
    def test_empty_dataset_keeps_no_rates(self):
        self.assertEqual(m.compile_snapshot(bundle([]))['profiles'],[])
    def test_corruption(self):
        b=bundle([]);b['payload']['dataset_version']='changed'
        with self.assertRaises(ValueError):m.compile_snapshot(b)
    def test_unapproved_profile_rejected(self):
        with self.assertRaises(ValueError):m.compile_snapshot(bundle([{'id':'test','kind':'profile','review':{'status':'experimental'}}]))
    def test_atomic_write_preserves_old_on_invalid_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json';path.write_text('old')
            with self.assertRaises(ValueError):m.atomic_write(path,{'value':float('nan')})
            self.assertEqual(path.read_text(),'old');self.assertEqual(len(list(Path(tmp).iterdir())),1)

    def test_snapshot_diff_reports_rate_and_lineage_changes(self):
        current={'profiles':[{'id':'same','method':'area','coefficient':1,'unit':'ml/m2','evidence_ids':['a']},
                             {'id':'removed','method':'area','coefficient':2,'unit':'ml/m2','evidence_ids':['b']}]}
        candidate={'profiles':[{'id':'same','method':'area','coefficient':1.5,'unit':'ml/m2','evidence_ids':['a','c']},
                               {'id':'added','method':'action','coefficient':4,'unit':'ml/action','evidence_ids':['d']}]}
        self.assertEqual(m.snapshot_diff(current,candidate),{
            'added':['added'],'removed':['removed'],
            'changed':[{'id':'same','before':{'method':'area','coefficient':1,'unit':'ml/m2','evidence_ids':['a']},
                        'after':{'method':'area','coefficient':1.5,'unit':'ml/m2','evidence_ids':['a','c']}}]})

    def test_post_write_failure_rolls_back_exact_previous_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json';path.write_bytes(b'previous snapshot\n')
            with self.assertRaisesRegex(ValueError,'readback failed'):
                m.atomic_write(path,{'value':1},verify=lambda _:False)
            self.assertEqual(path.read_bytes(),b'previous snapshot\n')
            self.assertEqual(len(list(Path(tmp).iterdir())),1)

    def test_revoked_profile_is_rejected_explicitly(self):
        record={'id':'revoked','kind':'profile','review':{'status':'revoked'}}
        with self.assertRaises(ValueError):m.compile_snapshot(bundle([record]))

    def test_v2_labeled_estimate_is_preserved_but_not_promoted_to_profile(self):
        estimate={'id':'estimate.h50','kind':'estimate','estimate_readiness':'labeled_runtime_estimate',
                  'label':'Manufacturer-declared, limited estimate','source_type':'manufacturer_declaration',
                  'confidence':'declared_source_limited','basis_kind':'manufacturer_declared_quantity',
                  'basis_ids':['observation.h50'],'method':'Declared wash quantity',
                  'quantity':{'value':180,'unit':'ml/action'},
                  'context':{'model_id':'xiaomi_h50_pro','reservoir':'dock_clean','action':'first_time_mop_wash'},
                  'limitations':['Completion-counter binding'],
                  'provenance':[{'claim':'Declared quantity'}], 'unknowns':['Firmware']}
        b=bundle([estimate]); b['payload']['schema_version']=2; b['manifest']['schema_version']=2
        b['manifest']['payload_sha256']=hashlib.sha256(m.canonical(b['payload'])).hexdigest()
        snapshot=m.compile_snapshot(b)
        self.assertEqual(snapshot['profiles'],[])
        self.assertEqual(snapshot['estimates'][0]['id'],'estimate.h50')

    def test_v2_estimate_without_basis_is_rejected(self):
        estimate={'id':'estimate.bad','kind':'estimate','estimate_readiness':'labeled_runtime_estimate'}
        b=bundle([estimate]); b['payload']['schema_version']=2; b['manifest']['schema_version']=2
        b['manifest']['payload_sha256']=hashlib.sha256(m.canonical(b['payload'])).hexdigest()
        with self.assertRaisesRegex(ValueError,'Ineligible v2 estimate'):
            m.compile_snapshot(b)
