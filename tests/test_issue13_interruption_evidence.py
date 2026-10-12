"""Keep the accounting interruption evidence after the user's repair (#13)."""
import asyncio
import copy
import importlib
import unittest
from test_beta_runtime_path import BASE, descriptor, effective, run, tick, hass
from test_user_device_removal import storage
from test_58_setup import report
refill = importlib.import_module("vwmruntimepkg.refill")
class InterruptionEvidenceTests(unittest.TestCase):
 def interrupted(self):
  device=effective({'device_options':{'vacuum.robot':{'capacity_ml':3000}}},descriptor('a27'))
  initial=run(device,{**BASE,'last_reset_ts':1000},[dict(status='cleaning',vac='cleaning',area='0'),dict(status='cleaning',vac='cleaning',area='2')])
  return device,run(device,initial,[dict(status='cleaning',vac='cleaning',area='4',intensity='high')],ts=10_120_000)
 def test_real_s7_context_interruption_survives_later_idle_tick(self):
  device,state=self.interrupted();self.assertTrue(state['accounting_incomplete'])
  incident=copy.deepcopy(state.get('last_accounting_interruption'))
  self.assertIsInstance(incident,dict)
  self.assertIn('accounting_context_changed',incident['reasons'])
  self.assertEqual(incident['ts'],10_180_000)
  later=run(device,state,[dict(status='charging',vac='docked',area='4',intensity='high')],ts=10_180_000)
  self.assertEqual(later['last_accounting_interruption'],incident)
 def test_actual_storage_repair_keeps_original_incident_and_learning(self):
  _,state=self.interrupted();state.update(calibration_factor=1.12,calibration_samples=4)
  async def scenario():
   st=storage.VacuumWaterStorage(None);await st.async_set_tank_state('vacuum.robot',state)
   return await st.async_reset_tank('vacuum.robot','2026-10-12T12:00:00Z',20_000_000,source='repair')
  fixed=asyncio.run(scenario());incident=fixed.get('last_accounting_interruption')
  self.assertIsInstance(incident,dict);self.assertIn('accounting_context_changed',incident['reasons'])
  self.assertEqual(incident['resolved_ts'],20_000_000);self.assertEqual(incident['refill_source'],'repair')
  self.assertFalse(fixed['accounting_incomplete']);self.assertEqual(fixed['used_ml'],0)
  self.assertEqual((fixed['calibration_factor'],fixed['calibration_samples']),(1.12,4))
 def test_dock_refill_resolves_evidence_without_erasing_it(self):
  _,state=self.interrupted();before=copy.deepcopy(state.get('last_accounting_interruption'))
  refill.apply_refill(state,20_000_000,'dock_cleared',rebaseline=True)
  self.assertIsInstance(before,dict)
  self.assertEqual(state['last_accounting_interruption']['reasons'],before['reasons'])
  self.assertEqual(state['last_accounting_interruption']['refill_source'],'dock_cleared')
 def test_healthy_idle_and_legacy_broken_state_do_not_invent_an_incident(self):
  device=effective({},descriptor('a27'))
  for state in [dict(BASE),{**BASE,'accounting_incomplete':True}]:
   result=run(device,state,[dict(status='charging',vac='docked')]);self.assertNotIn('last_accounting_interruption',result)
 def test_health_exposes_stable_reason_in_repair_parameters(self):
  _,state=self.interrupted();state['last_accounting_reason']='not_mopping'
  health=report(tank=state,desc=descriptor('a27'))
  check=next(c for c in health['checks'] if c['id']=='accounting_paused')
  self.assertIn('accounting_context_changed',check['params']['reason'])
