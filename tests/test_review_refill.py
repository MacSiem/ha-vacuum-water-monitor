"""Confirmation of an earlier automatic refill preserves open-session usage."""
import asyncio,json,tempfile,unittest
from pathlib import Path
from test_beta_runtime_path import BASE,tick
from importlib import import_module
storage=import_module('vwmruntimepkg.storage');refill=import_module('vwmruntimepkg.refill')
class JsonStore:
 def __init__(self,path):self.path=path
 async def async_load(self):return json.loads(self.path.read_text()) if self.path.exists() else None
 async def async_save(self,value):self.path.write_text(json.dumps(value))
class ReviewRefillTest(unittest.TestCase):
 def test_late_confirmation_preserves_usage_open_session_and_one_history(self):
  async def go(path):
   s={**BASE,'used_ml':3000,'cycle_full_confirmed':True}
   refill.apply_refill(s,10_000_000,'dock_cleared',rebaseline=True)
   s.update(used_ml=12,session_start_ts=10_010_000)
   db=storage.VacuumWaterStorage(None);db._store=JsonStore(path);await db.async_set_tank_state('vacuum.robot',s)
   return await db.async_reset_tank('vacuum.robot','1970-01-01T02:47:00+00:00',10_020_000,'card')
  with tempfile.TemporaryDirectory() as tmp:s=asyncio.run(go(Path(tmp)/'state'))
  self.assertEqual(s['used_ml'],12);self.assertEqual(s['session_start_ts'],10_010_000)
  self.assertEqual(len(s['refill_history']),1);self.assertTrue(s['cycle_full_confirmed'])
  self.assertFalse(s['refill_full_unconfirmed']);self.assertEqual(s['cycle_full_confirmation_source'],'card')
  self.assertFalse(s['nominal_time_start_pending'])
