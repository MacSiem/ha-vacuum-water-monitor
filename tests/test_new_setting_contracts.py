"""Conditional controls change context without inventing doses or extra passes."""
import unittest
from test_beta_runtime_path import discovery,effective,hass,tick,_S,BASE,SIGNALS

def descriptor(platform, controls):
 e=[dict(entity_id='vacuum.robot',platform=platform,device_id='d1',unique_id='vacuum')]
 e.extend(dict(entity_id=k,platform=platform,device_id='d1',translation_key=v,unique_id='id_'+v) for k,v in controls.items())
 return discovery.discover_descriptors(e,[dict(id='d1',manufacturer=platform,model='unknown')],{})[0]

class NewSettingContracts(unittest.TestCase):
 def test_ecovacs_interval_and_efficiency_scoped_and_domain_checked(self):
  d=descriptor('ecovacs',{'number.interval':'mop_wash_interval','select.efficiency':'efficiency_mode','sensor.bad':'mop_wash_interval'})
  self.assertEqual(d['signals']['context_mop_wash_interval_entity'],'number.interval')
  self.assertEqual(d['signals']['context_efficiency_mode_entity'],'select.efficiency')
 def test_requested_roborock_repeat_does_not_multiply_area(self):
  d=effective({},descriptor('roborock',{**SIGNALS,'select.repeat':'cleaning_cycles'}))
  self.assertEqual(d['context_cleaning_cycles_entity'],'select.repeat')
  s={**BASE,'last_area':0}
  for i,(area,repeat) in enumerate(((0,'1'),(0,'2'),(10,'2')),1):
   s,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=area,extra={'select.repeat':_S(repeat)}),d,s,now_ts=10_000_000+i*60000)
  # A generic model has no automatic water rate; add a declared rate for an
  # independent second pass of the same trace.
  self.assertEqual(s['used_ml'],0)
  d.update(usage_ml_per_m2={'default':6},calibration_scope='floor_only')
  s={**BASE,'last_area':0}
  for i,(area,repeat) in enumerate(((0,'1'),(0,'2'),(10,'2')),1):
   s,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=area,extra={'select.repeat':_S(repeat)}),d,s,now_ts=20_000_000+i*60000)
  self.assertEqual(s['used_ml'],60)
 def test_ecovacs_interval_is_context_not_dose(self):
  d=effective({},descriptor('ecovacs',{'number.interval':'mop_wash_interval','select.efficiency':'efficiency_mode'}))
  state={**BASE,'last_area':0}
  for i,interval in enumerate((10,15),1):
   state,_=tick.tick_device(hass(extra={'number.interval':_S(str(interval),{'min':10,'max':30}),
                                      'select.efficiency':_S('standard')}),d,state,now_ts=10_000_000+i*60000)
  obs=state['last_consumption_context']['observed_settings']
  self.assertEqual(obs['mop_wash_interval']['value'],'15')
  self.assertEqual(state['used_ml'],0)
