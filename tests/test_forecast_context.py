"""Forecasts use only recent runs comparable to the observed current settings."""
import unittest
from importlib import import_module
from copy import deepcopy
from test_beta_runtime_path import tick
forecast=import_module('vwmruntimepkg.forecast')
DAY=86_400_000;NOW=100*DAY

def context(water,source='id1',entity='number.old'):
 return {'model_id':'robot','reservoir':'dock_clean','settings':{'water_level':water},
         'observed_settings':{'wetness':{'value':water,'source':source,'source_registry_id':source,'source_entity':entity}}}
def session(water,idx,**extra):
 return {'ts':NOW-idx*2*DAY,'started_ts':NOW-idx*2*DAY-60_000,'water':210,
         'accounting_valid':True,'exposure_complete':True,'segments':1,'context':context(water),**extra}
class ForecastContextTests(unittest.TestCase):
 def test_observed_change_hides_old_forecast_until_three_new_comparable_runs(self):
  old=[session('medium',i) for i in range(5)]
  state={'automatic_sessions':old,'last_consumption_context':context('medium')}
  before=forecast.supply_forecast(state,2950,NOW);self.assertEqual(before['cleanings_left'],14)
  state['last_consumption_context']=context('high')
  after=forecast.supply_forecast(state,2950,NOW);self.assertIsNone(after['cleanings_left']);self.assertIsNone(after['days_left'])
  self.assertTrue(after['context_changed']);self.assertEqual(after['basis_runs'],0);self.assertEqual(state['automatic_sessions'],old)
  state['automatic_sessions']=[session('high',i) for i in range(3)]+old
  recovered=forecast.supply_forecast(state,2950,NOW);self.assertEqual(recovered['basis_runs'],3);self.assertEqual(recovered['cleanings_left'],14)
 def test_registry_rename_is_comparable_replacement_is_not(self):
  old=session('medium',0);new=context('medium',entity='number.renamed')
  self.assertTrue(forecast._same_forecast_context(new,old['context']))
  self.assertFalse(forecast._same_forecast_context(context('medium',source='newid'),old['context']))
 def test_missing_observed_source_does_not_qualify_old_history(self):
  state={'automatic_sessions':[session('medium',i) for i in range(3)],'last_consumption_context':context('medium')}
  state['last_consumption_context']['observed_settings']['wetness']['value']=None
  result=forecast.supply_forecast(state,2950,NOW);self.assertIsNone(result['cleanings_left']);self.assertEqual(result['basis_runs'],0)
 def test_mixed_or_incomplete_session_is_not_a_forecast_basis(self):
  state={'automatic_sessions':[session('medium',0,segments=2),session('medium',1),session('medium',2)],'last_consumption_context':context('medium')}
  result=forecast.supply_forecast(state,2950,NOW);self.assertEqual(result['basis_runs'],2);self.assertIsNone(result['cleanings_left'])
 def test_unavailable_previously_bound_setting_does_not_reuse_old_forecast(self):
  c=context('medium');c['settings']['water_level']=None;c['field_sources']={'water_level':'unavailable'}
  state={'automatic_sessions':[session('medium',i) for i in range(3)],'last_consumption_context':c}
  result=forecast.supply_forecast(state,2950,NOW);self.assertIsNone(result['cleanings_left']);self.assertEqual(result['basis_runs'],0)

 def test_loss_unbind_and_return_keep_history_and_withhold_forecast(self):
  history=[session('medium',i) for i in range(4)]
  before=deepcopy(history)
  current=context('medium');current['settings']['water_level']=None
  current['observed_settings']={};current['field_sources']={'water_level':'not_exposed'}
  state={'automatic_sessions':history,'last_consumption_context':current}
  result=forecast.supply_forecast(state,2950,NOW)
  self.assertIsNone(result['cleanings_left']);self.assertIsNone(result['days_left'])
  self.assertEqual(result['basis_runs'],0);self.assertTrue(result['context_changed'])
  self.assertEqual(history,before)
  state['last_consumption_context']=context('medium',entity='number.renamed')
  result=forecast.supply_forecast(state,2950,NOW)
  self.assertEqual(result['basis_runs'],4);self.assertEqual(result['cleanings_left'],14)
 def test_removed_observed_key_is_not_wildcard(self):
  current=context('medium');current['observed_settings']={}
  state={'automatic_sessions':[session('medium',i) for i in range(3)],'last_consumption_context':current}
  result=forecast.supply_forecast(state,2950,NOW)
  self.assertEqual(result['basis_runs'],0);self.assertTrue(result['context_changed'])
 def test_unavailable_and_both_unknown_and_legacy_current(self):
  previous=context('medium');current=context('medium');current['field_sources']={'water_level':'unavailable'}
  self.assertFalse(forecast._same_forecast_context(current,previous))
  unknown={'settings':{'water_level':None},'field_sources':{'water_level':'not_exposed'}}
  self.assertTrue(forecast._same_forecast_context(unknown,deepcopy(unknown)))
  self.assertTrue(forecast._same_forecast_context(None,previous))
  self.assertFalse(forecast._same_forecast_context(unknown,previous))
  self.assertFalse(forecast._same_forecast_context(unknown,None))
