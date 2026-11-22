"""ADV 7.7 status and area sensors; source-shaped synthetic input only."""
import unittest
from test_discovery import _load_discovery
from test_tick import tick, _Hass, _State

def device():
 e=[dict(entity_id='vacuum.test',platform='tapo_rv30',unique_id='entry_vacuum',device_id='robot',config_entry_id='entry'),
    dict(entity_id='sensor.status',platform='tapo_rv30',unique_id='entry_status',device_id='robot',config_entry_id='entry',translation_key='status'),
    dict(entity_id='sensor.area',platform='tapo_rv30',unique_id='entry_clean_area',device_id='robot',config_entry_id='entry'),
    dict(entity_id='select.passes',platform='tapo_rv30',unique_id='entry_clean_passes',device_id='robot',config_entry_id='entry')]
 d=_load_discovery().discover_descriptors(e,[dict(id='robot',manufacturer='Tapo',model='RV50 Pro Omni')],{})[0]
 return {**d,**d['signals'],'vacuum_entity':'vacuum.test','cleaning_mode_entity':'select.mode','usage_ml_per_m2':{'low':2},'accounting_evidence':'user_calibration'}

def event(d,state=None,*,status='Cleaning',area=0,unit='m²',ts=1_000_000):
 h=_Hass({'vacuum.test':_State('cleaning',{'clean_area':area,'clean_time_min':0,'water_level':'low','mop_attached':True}),
          'select.mode':_State('Vacuum and Mop;Deep Clean'),'sensor.status':_State(status),
          'sensor.area':_State(str(area),{'unit_of_measurement':unit}),'select.passes':_State('1')})
 return tick.tick_device(h,d,state or {'used_ml':0,'initialized':True},now_ts=ts)[0]
class Adv7Tests(unittest.TestCase):
 def test_new_discovery_binds_status_and_area(self):
  d=device();self.assertEqual(d['signals']['status_sensor'],'sensor.status');self.assertEqual(d['signals']['area_sensor'],'sensor.area')
 def test_cleaning_sensor_and_ft2(self):
  d=device();a=event(d);b=event(d,a,area=10,ts=1_060_000);self.assertEqual(b['used_ml'],20)
  a=event(d,unit='ft²');b=event(d,a,area=100,unit='ft²',ts=1_060_000);self.assertAlmostEqual(b['used_ml'],18.58,places=2)
 def test_non_floor_and_unknown_labels_never_charge(self):
  d=device()
  for label in ('Mapping','Remote Control','Going To Point','Exploring','Code(90)','unknown'):
   a=event(d,status=label);b=event(d,a,status=label,area=10,ts=1_060_000);self.assertEqual(b['used_ml'],0,label)
 def test_unknown_unit_never_uses_raw_area(self):
  d=device();a=event(d,unit='坪');b=event(d,a,unit='坪',area=10,ts=1_060_000);self.assertEqual(b['used_ml'],0)
 def test_status_unavailable_does_not_fall_back_to_vacuum_cleaning(self):
  d=device();a=event(d,status='unavailable');b=event(d,a,status='unavailable',area=10,ts=1_060_000)
  self.assertEqual(b['used_ml'],0);self.assertEqual(b['last_accounting_reason'],'status_unavailable')
 def test_area_missing_or_unit_unknown_does_not_fall_back_to_raw(self):
  d=device();d.pop('area_sensor',None);a=event(d);b=event(d,a,area=10,ts=1_060_000)
  self.assertEqual(b['used_ml'],0)
  d=device();a=event(d,unit='');b=event(d,a,area=10,unit='',ts=1_060_000)
  self.assertEqual(b['used_ml'],0)
 def test_wrong_config_entry_never_binds_status(self):
  e=[dict(entity_id='vacuum.test',platform='tapo_rv30',unique_id='entry_vacuum',device_id='robot',config_entry_id='entry'),
     dict(entity_id='sensor.status',platform='tapo_rv30',unique_id='entry_status',device_id='robot',config_entry_id='foreign',translation_key='status')]
  d=_load_discovery().discover_descriptors(e,[dict(id='robot')],{})[0]
  self.assertNotIn('status_sensor',d['signals']);self.assertNotEqual(d.get('tapo_status_contract'),2)
