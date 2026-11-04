"""A known, explicitly rebased starting area must not discard the next interval."""
import unittest
from test_beta_runtime_path import BASE,descriptor,effective,hass,tick
class GapRebaseTests(unittest.TestCase):
 def test_long_docked_idle_setting_change_then_new_area_is_counted(self):
  dev=effective({},descriptor())
  state={**BASE,'last_area':10,'last_status':'charging','last_tick_ts':10_000_000,
         'last_rate_settings':{'cleaning_mode':None,'mop_mode':'standard','mop_intensity':'medium'}}
  state,_=tick.tick_device(hass(status='charging',vac='docked',area=10),dev,state,now_ts=10_000_000)
  old=state['used_ml']
  state,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=0,intensity='high'),dev,state,now_ts=17_200_000)
  state,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=.5,intensity='high'),dev,state,now_ts=17_260_000)
  self.assertAlmostEqual(state['used_ml']-old,3.9,places=2)
  self.assertFalse(state.get('accounting_incomplete'))
  self.assertTrue(state.get('session_exposure_complete'))
  self.assertEqual(state.get('session_start_ts'),17_200_000)
 def test_prior_incomplete_tank_is_not_requalified_by_zero_area(self):
  dev=effective({},descriptor())
  state={**BASE,'last_area':10,'last_status':'charging','last_tick_ts':10_000_000,'accounting_incomplete':True,
         'last_rate_settings':{'cleaning_mode':None,'mop_mode':'standard','mop_intensity':'medium'}}
  state,_=tick.tick_device(hass(status='charging',vac='docked',area=10),dev,state,now_ts=10_000_000)
  state,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=0,intensity='high'),dev,state,now_ts=17_200_000)
  state,_=tick.tick_device(hass(status='cleaning',vac='cleaning',area=.5,intensity='high'),dev,state,now_ts=17_260_000)
  self.assertTrue(state.get('accounting_incomplete'))
  self.assertFalse(state.get('session_exposure_complete'))
