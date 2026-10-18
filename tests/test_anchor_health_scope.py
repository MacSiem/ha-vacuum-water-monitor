"""Manual tank-empty remains available when a generic robot error is unscoped."""
import importlib,unittest
from test_beta_runtime_path import discovery,sc
health=importlib.import_module(discovery.__package__+'.health')

def tapo():
    entities=[{'entity_id':'vacuum.tapo','device_id':'one','platform':'matter'}]
    entities += [{'entity_id':domain+'.'+key,'device_id':'one','platform':'matter','translation_key':key}
                 for domain,key in [('sensor','operational_state'),('sensor','operational_error'),('select','clean_mode')]]
    desc=discovery.discover_descriptors(entities,[{'id':'one','manufacturer':'Tapo','model':'RV50 Pro Omni','model_id':'1797'}],{})[0]
    return sc.apply_custom_calibration(sc.build_vacuum_devices({}, {}, [desc])[0],{})

class AnchorHealthScopeTests(unittest.TestCase):
    def test_unscoped_matter_error_does_not_disable_manual_tracked_tank_empty(self):
        device=tapo()
        self.assertEqual(device['tracked_reservoir'],'dock_clean')
        self.assertTrue(device['water_anchor_reservoir_inferred'])
        self.assertFalse(health.has_empty_signal(device))
        self.assertFalse(health.supports_auto_refill(device))
        self.assertEqual(health.refill_method(device),'manual')

    def test_explicit_same_reservoir_contract_still_allows_automatic_anchor(self):
        device=tapo();device['water_anchor_reservoir_inferred']=False
        self.assertTrue(health.has_empty_signal(device))
        self.assertTrue(health.supports_auto_refill(device))
