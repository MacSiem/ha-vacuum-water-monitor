"""Private measured calibration requires complete, separate physical cycles."""
import unittest
from copy import deepcopy
from test_calibration_export import module as calibration
from test_profile_selection import context


def cycle(ts=1, area=10):
    return {'ts':ts,'area':area,'context':context(),'accounting_valid':True,'exposure_complete':True,'segments':1}


def measurement():
    return {'observed_ml':100,'resolution_ml':5,'instrument':'graduated_jug',
            'boundaries_confirmed':True,'uninterrupted':True,'purpose':'training'}


class MeasurementTests(unittest.TestCase):
    def sample(self, session=None, values=None):
        fn=getattr(calibration,'build_local_measurement',None)
        self.assertTrue(callable(fn),'Local measured calibration is missing')
        return fn(session or cycle(),values or measurement(),'vacuum.test')

    def test_observed_volume_is_separate_from_prediction(self):
        s=cycle();s['water']=999
        result=self.sample(s)
        self.assertEqual(result['observed_ml'],100)
        self.assertEqual(result['area_m2'],10)
        self.assertEqual(result['purpose'],'training')

    def test_missing_boundaries_and_bad_numbers_rejected(self):
        for key,val in [('boundaries_confirmed',False),('uninterrupted',False),('observed_ml',float('inf')),('resolution_ml',0),('instrument',''),('observed_ml',True)]:
            v=measurement();v[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):self.sample(values=v)

    def test_partial_or_mixed_cycle_cannot_fit(self):
        for key,val in [('exposure_complete',False),('segments',2),('area',None),('context',None)]:
            s=cycle();s[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):self.sample(s)

    def test_three_distinct_training_cycles_produce_private_whole_cycle_area_rate(self):
        samples=[self.sample(cycle(i)) for i in (1,2,3)]
        fn=getattr(calibration,'fit_local_measurements',None)
        self.assertTrue(callable(fn),'Local fitting is missing')
        result=fn(samples)
        self.assertEqual(result['coefficient'],10)
        self.assertEqual(result['scope'],'whole_cycle')
        self.assertEqual(result['method'],'area')
        self.assertEqual(result['review']['status'],'experimental')
        self.assertIsNone(result['validation']['max_error_ml'])
        self.assertIsNone(fn(samples[:2]))
        self.assertIsNone(fn([samples[0]]*3))

    def test_holdout_never_changes_training_coefficient(self):
        samples=[self.sample(cycle(i)) for i in (1,2,3)]
        values=measurement();values.update(purpose='validation',observed_ml=120)
        samples.append(self.sample(cycle(4),values))
        fn=getattr(calibration,'fit_local_measurements',None)
        self.assertTrue(callable(fn))
        result=fn(samples)
        self.assertEqual(result['coefficient'],10)
        self.assertEqual(result['validation']['max_error_ml'],20)
        self.assertEqual(result['validation']['validation_ids'],['local.4'])

    def test_other_device_or_settings_cannot_merge(self):
        samples=[self.sample(cycle(i)) for i in (1,2,3)]
        fn=getattr(calibration,'fit_local_measurements',None)
        self.assertTrue(callable(fn))
        for key,val in [('device_id','vacuum.other'),('context',{'firmware':'other'})]:
            changed=deepcopy(samples);changed[2][key]=val
            self.assertIsNone(fn(changed))

    def test_identifiability_accepts_single_axis_and_full_rank_hybrid(self):
        fn=getattr(calibration,'check_identifiability',None)
        self.assertTrue(callable(fn),'Identifiability gate is missing')
        self.assertEqual(fn('area',[{'area':8},{'area':12},{'area':20}]),{
            'identifiable':True,'rank':1,'parameters':1,'reason':'full_rank'})
        self.assertEqual(fn('hybrid',[
            {'area':10,'time':5,'action':0},
            {'area':0,'time':8,'action':2},
            {'area':4,'time':0,'action':7},
        ]),{'identifiable':True,'rank':3,'parameters':3,'reason':'full_rank'})

    def test_identifiability_rejects_one_total_and_collinear_hybrid(self):
        fn=getattr(calibration,'check_identifiability',None)
        self.assertEqual(fn('hybrid',[{'area':10,'time':20,'action':2}]),{
            'identifiable':False,'rank':1,'parameters':3,'reason':'insufficient_rank'})
        result=fn('hybrid',[
            {'area':10,'time':20,'action':2},
            {'area':20,'time':40,'action':4},
            {'area':30,'time':60,'action':6},
        ])
        self.assertFalse(result['identifiable'])
        self.assertEqual(result['rank'],1)
        self.assertEqual(result['parameters'],3)
        self.assertEqual(result['reason'],'insufficient_rank')

    def test_identifiability_rejects_invalid_design_without_fitting(self):
        fn=getattr(calibration,'check_identifiability',None)
        for method,rows in [
            ('unknown',[{'area':1}]),
            ('area',[{'area':True}]),
            ('time',[{'time':float('inf')}]),
            ('action',[{'action':-1}]),
            ('hybrid',[{'area':1,'time':2}]),
            ('hybrid',[]),
        ]:
            with self.subTest(method=method,rows=rows):
                result=fn(method,rows)
                self.assertFalse(result['identifiable'])
                self.assertEqual(result['reason'],'invalid_design')
