"""Registry rename preserves personal/nominal contexts; replacement does not."""
import unittest
from copy import deepcopy
from test_profile_selection import context
from test_local_measurements import cycle,measurement,calibration
from test_nominal_time_learning import tank,result,CONTEXT
from importlib import import_module
profiles=import_module('vwmruntimepkg.profiles')
def observed(entity,registry='stable'):
 return {'wetness_level':{'value':'16','min':1,'max':32,'unit':None,'source':'hash-'+registry,
                          'source_registry_id':registry,'source_entity':entity}}
class ContextIdentityReview(unittest.TestCase):
 def test_personal_measurement_fits_across_rename_not_replacement(self):
  samples=[]
  for i,entity in enumerate(('number.old','number.new','number.new'),1):
   run=cycle(i);run['context']['observed_settings']=observed(entity);run['context']['signal_contract_version']=2
   samples.append(calibration.build_local_measurement(run,measurement(),'vacuum.test'))
  fit=calibration.fit_local_measurements(samples);self.assertIsNotNone(fit);self.assertEqual(fit['coefficient'],10)
  replacement=deepcopy(samples);replacement[2]['context']['observed_settings']=observed('number.new','replacement')
  self.assertIsNone(calibration.fit_local_measurements(replacement))
  self.assertTrue(profiles._compatible_context(samples[0]['context'],samples[1]['context']))
  self.assertFalse(profiles._compatible_context(samples[0]['context'],replacement[2]['context']))
 def test_nominal_bank_resolves_rename_and_rejects_replacement(self):
  old={**CONTEXT,'observed_settings':observed('number.old'),'signal_contract_version':2}
  renamed={**CONTEXT,'observed_settings':observed('number.new'),'signal_contract_version':2}
  different={**CONTEXT,'observed_settings':observed('number.new','replacement'),'signal_contract_version':2}
  bank={}
  for i in range(3):bank=tank(bank,context=old,now=1000+i*2_000_000)
  self.assertEqual(result(bank,context=renamed)['status'],'active')
  self.assertEqual(result(bank,context=different)['status'],'unavailable')
