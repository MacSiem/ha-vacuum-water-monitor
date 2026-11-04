"""Observed proxy settings must remain distinct, scoped, and stable for calibration."""
import unittest
from test_beta_runtime_path import discovery,effective,hass,tick,_S,BASE

def fixture():
 keys={'sensor.robot_state':'state','sensor.robot_area':'cleaned_area','select.robot_mode':'cleaning_mode',
       'select.robot_humidity':'mop_pad_humidity','number.robot_wetness':'wetness_level',
       'select.robot_route':'cleaning_route','select.robot_remop':'auto_rewashing',
       'select.robot_reclean':'auto_recleaning','switch.robot_smart':'smart_mop_washing',
       'sensor.robot_clean_status':'clean_water_tank_status'}
 ents=[dict(entity_id='vacuum.robot',platform='dreame_vacuum',device_id='d1',unique_id='robot')]
 ents += [dict(entity_id=e,platform='dreame_vacuum',device_id='d1',translation_key=k,unique_id='robot_'+k) for e,k in keys.items()]
 ents += [dict(entity_id='select.other_route',platform='dreame_vacuum',device_id='d2',translation_key='cleaning_route',unique_id='other_route'),
          dict(entity_id='select.room_route',platform='dreame_vacuum',device_id='d1',translation_key='cleaning_route',unique_id='robot_segment_2_cleaning_route'),
          dict(entity_id='sensor.bad_wetness',platform='dreame_vacuum',device_id='d1',translation_key='wetness_level',unique_id='robot_wrong')]
 states={e:_S('on') for e in keys}
 desc=discovery.discover_descriptors(ents,[dict(id='d1',manufacturer='Dreame',model='L10s Ultra')],states)[0]
 return effective({},desc)

def event(dev,state,area,wetness=16,smart='off',remop='off',reclean='off',maxval=32,ts=10_000_000):
 extra={'sensor.robot_state':_S('cleaning'),'sensor.robot_area':_S(str(area),{'unit_of_measurement':'m²'}),
 'select.robot_mode':_S('mopping'),'select.robot_humidity':_S('medium'),
 'number.robot_wetness':_S(str(wetness),{'min':1,'max':maxval}), 'select.robot_route':_S('standard'),
 'select.robot_remop':_S(remop),'select.robot_reclean':_S(reclean),'switch.robot_smart':_S(smart)}
 return tick.tick_device(hass(status='cleaning',vac='cleaning',area=area,extra=extra),dev,state,now_ts=ts)[0]

class DreameObservedSettings(unittest.TestCase):
 def test_discovery_scope_exact_domain_and_all_controls(self):
  dev=fixture();self.assertEqual(dev['context_wetness_level_entity'],'number.robot_wetness')
  self.assertEqual(dev['context_cleaning_route_entity'],'select.robot_route')
  self.assertEqual(dev['context_auto_rewashing_entity'],'select.robot_remop')
  self.assertEqual(dev['context_auto_recleaning_entity'],'select.robot_reclean')
  self.assertEqual(dev['context_smart_mop_washing_entity'],'switch.robot_smart')
  self.assertEqual(dev['clean_water_tank_status_sensor'],'sensor.robot_clean_status')
  self.assertEqual(dev['signal_contract_version'],2)
 def test_exact_wetness_and_independent_settings_affect_same_snapshot(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  state=event(dev,state,5,ts=10_060_000)
  changed=event(dev,state,7,wetness=17,smart='on',remop='on',reclean='off',ts=10_120_000)
  obs=changed['last_consumption_context']['observed_settings']
  self.assertEqual(obs['wetness_level']['value'],'17');self.assertEqual(obs['wetness_level']['max'],32)
  self.assertEqual(obs['smart_mop_washing']['value'],'on');self.assertEqual(obs['auto_rewashing']['value'],'on')
  self.assertEqual(obs['auto_recleaning']['value'],'off')
  self.assertEqual(changed['used_ml'],state['used_ml']);self.assertTrue(changed['accounting_incomplete'])
 def test_known_control_unavailable_blocks_learning(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  state=event(dev,state,5,ts=10_060_000)
  changed=event(dev,state,6,wetness='unavailable',ts=10_120_000)
  self.assertTrue(changed['accounting_incomplete'])
  self.assertIsNone(changed['last_consumption_context']['observed_settings']['wetness_level']['value'])
 def test_lost_setting_at_rest_is_not_a_learnable_tank(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  changed=event(dev,state,0,wetness='unavailable',ts=10_060_000)
  self.assertTrue(changed['accounting_incomplete'])
 def test_change_preserves_legacy_calibration_in_separate_bank(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  # This factor was learned under the already-observed current context.
  state.update(calibration_factor=1.3,calibration_samples=3)
  old=state['accounting_calibration_context'];state=event(dev,state,5,ts=10_060_000)
  changed=event(dev,state,7,wetness=17,ts=10_120_000)
  self.assertEqual(changed['nominal_calibration_contexts'][old]['calibration_factor'],1.3)
  self.assertEqual(changed['calibration_factor'],1)
  self.assertEqual(changed['calibration_samples'],0)
 def test_personal_profile_does_not_cross_new_context(self):
  from vwmruntimepkg import profiles
  settings={k:'known' for k in profiles.CONSUMPTION_SETTINGS}
  left={k:'known' for k in profiles.CONSUMPTION_AXES};left['reservoir']='dock_clean';left['settings']=settings
  right={**left,'observed_settings':{'wetness_level':{'value':'17','min':1,'max':32,'unit':None}},'signal_contract_version':2}
  self.assertFalse(profiles._compatible_context(left,right))
  self.assertTrue(profiles._compatible_context(right,dict(right)))
 def test_legacy_factor_without_context_is_preserved_but_not_applied(self):
  dev=fixture();initial={**BASE,'last_area':0,'calibration_factor':1.3,'calibration_samples':3,'calibration_log_factors':[.26,.26,.26]}
  state=event(dev,initial,0)
  self.assertEqual(state['calibration_factor'],1)
  self.assertEqual(state['calibration_samples'],0)
  self.assertTrue(any(x.get('calibration_factor')==1.3 for x in state['nominal_calibration_contexts'].values()))
 def test_removing_previously_observed_binding_invalidates_cycle(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  state=event(dev,state,5,ts=10_060_000)
  removed=dict(dev);removed.pop('context_wetness_level_entity')
  result=event(removed,state,5,ts=10_120_000)
  self.assertTrue(result['accounting_incomplete'])
  self.assertIsNone(result['last_consumption_context']['observed_settings']['wetness_level']['value'])
 def test_numeric_range_change_separates_the_calibration_context(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  state=event(dev,state,5,ts=10_060_000)
  old=state['accounting_calibration_context'];changed=event(dev,state,5,maxval=15,ts=10_120_000)
  self.assertNotEqual(old,changed['accounting_calibration_context'])
  self.assertEqual(changed['last_consumption_context']['observed_settings']['wetness_level']['max'],15)
 def test_dreame_tank_status_is_diagnostic_not_refill_or_volume(self):
  dev=fixture();state={**BASE,'last_area':0,'used_ml':1000,'cycle_full_confirmed':True}
  for i,value in enumerate(('low_water','not_installed','checking','installed'),1):
   state=tick.tick_device(hass(extra={'sensor.robot_clean_status':_S(value)}),dev,state,now_ts=10_000_000+i*60000)[0]
  self.assertEqual(state['used_ml'],1000)
  self.assertNotEqual(state.get('last_reset_source'),'dock_cleared')
  self.assertNotIn('dock_clean_water_sensor',dev)
 def test_returning_to_drain_is_not_a_wash_or_floor_dose(self):
  dev=fixture();state=event(dev,{**BASE,'last_area':0},0)
  state=event(dev,state,5,ts=10_060_000);before=state['used_ml']
  state,_=tick.tick_device(hass(status='returning_to_drain',vac='returning',area=6,
   extra={'sensor.robot_state':_S('returning_to_drain'),'sensor.robot_area':_S('6',{'unit_of_measurement':'m²'}),
          'select.robot_mode':_S('mopping'),'select.robot_humidity':_S('medium'),
          'number.robot_wetness':_S('16',{'min':1,'max':32}), 'select.robot_route':_S('standard'),
          'select.robot_remop':_S('off'),'select.robot_reclean':_S('off'),'switch.robot_smart':_S('off')}),dev,state,now_ts=10_120_000)
  self.assertEqual(state['used_ml'],before)
  self.assertFalse(any(e.get('action')=='mop_wash' for e in state.get('consumption_events',[])))
