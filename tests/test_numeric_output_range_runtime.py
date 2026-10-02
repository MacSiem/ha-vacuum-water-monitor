import unittest
import test_signal_mapping as mapping
from test_beta_runtime_path import discovery, effective, tick, _Hass, _S

class NumericOutputRuntimeTests(unittest.TestCase):
    def sample(self, level, attributes=None, override_factor=None):
        entities, devices, states = mapping.XiaomiHomeSignalMappingTests()._fixture()
        old = next(e['entity_id'] for e in entities if 'mop_water_output' in e['entity_id'])
        new = old.replace('select.', 'number.', 1)
        for entity in entities:
            if entity['entity_id']==old:
                entity['entity_id']=new;entity['unique_id']=new
        states.pop(old);states[new]=mapping._state(str(level), **(attributes or {}))
        vacuum=next(e['entity_id'] for e in entities if e['entity_id'].startswith('vacuum.'))
        area=next(e['entity_id'] for e in entities if 'cleaning_area' in e['entity_id'])
        states[area]=mapping._state('2',unit_of_measurement='m²')
        device=effective({}, discovery.discover_descriptors(entities,devices,states)[0])
        if override_factor is not None: device['intensity_factor']=override_factor
        values={k:_S(v['state'],v['attributes']) for k,v in states.items()}
        state,_=tick.tick_device(_Hass(values),device,
            {'initialized':True,'used_ml':0,'last_area':0,'last_tick_ts':60000},now_ts=120000)
        return state,device

    def test_bounded_numeric_output_uses_declared_range_for_estimate(self):
        for level,factor in [(1,.7),(2,1),(3,1.3)]:
            with self.subTest(level=level):
                state,device=self.sample(level, {'min':1,'max':3})
                self.assertAlmostEqual(state['used_ml'],2*device['usage_ml_per_m2']['default']*factor,places=2)
                self.assertFalse(state.get('accounting_incomplete'))

    def test_non_three_level_range_is_normalized_before_the_factor(self):
        for level,factor in [(2,.7),(6,1),(10,1.3)]:
            with self.subTest(level=level):
                state,device=self.sample(level, {'min':1,'max':10})
                self.assertAlmostEqual(state['used_ml'],2*device['usage_ml_per_m2']['default']*factor,places=2)
                self.assertFalse(state.get('accounting_incomplete'))

    def test_unbounded_numeric_enum_does_not_invent_a_band(self):
        state,_=self.sample(8)
        self.assertEqual(state['used_ml'],0)
        self.assertTrue(state.get('accounting_incomplete'))

    def test_zero_output_stays_dry(self):
        state,_=self.sample(0, {'min':0,'max':3})
        self.assertEqual(state['used_ml'],0)

    def test_authored_numeric_factor_has_precedence_over_inferred_band(self):
        state,device=self.sample(2,{'min':1,'max':10}, {'2':1.1,'default':1})
        self.assertAlmostEqual(state['used_ml'],2*device['usage_ml_per_m2']['default']*1.1,places=2)

    def test_out_of_range_output_is_not_clamped_to_a_supported_level(self):
        state,_=self.sample(4,{'min':1,'max':3})
        self.assertEqual(state['used_ml'],0)
        self.assertTrue(state.get('accounting_incomplete'))
