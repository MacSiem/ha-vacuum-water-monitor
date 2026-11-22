"""Identity proof must use registry facts, never shared marketing names."""
import unittest
from test_discovery import _load_discovery
from test_sensor_calculations import build_vacuum_devices

class IdentityTests(unittest.TestCase):
    def descriptors(self, devices):
        entities=[{'entity_id':f'vacuum.{i}','device_id':d['id'],'platform':'roborock' if i==0 else 'matter'} for i,d in enumerate(devices)]
        return _load_discovery().discover_descriptors(entities, devices,{})

    def test_same_registry_device_is_counted_once(self):
        ds=self.descriptors([{'id':'same'},{'id':'same'}])
        self.assertEqual(len(build_vacuum_devices({}, {},ds)),1)

    def test_same_mac_across_registry_devices_is_counted_once(self):
        ds=self.descriptors([{'id':'one','connections':[['mac','AA:BB:CC:DD:EE:FF']]},{'id':'two','connections':[['mac','aa-bb-cc-dd-ee-ff']]}])
        self.assertEqual(len(build_vacuum_devices({}, {},ds)),1)

    def test_same_model_without_identity_proof_remains_two(self):
        ds=self.descriptors([{'id':'one','model':'same'},{'id':'two','model':'same'}])
        self.assertEqual(len(build_vacuum_devices({}, {},ds)),2)

    def test_split_registry_device_retains_prior_owner_without_merging_banks(self):
        before=self.descriptors([{'id':'old'}, {'id':'old'}])
        ds=self.descriptors([{'id':'one','composite_device_id':'old'},
                             {'id':'two','composite_device_id':'old'}])
        tanks={'vacuum.0': {'used_ml': 100}, 'vacuum.1': {'used_ml': 500}}
        previous=build_vacuum_devices({}, tanks, before)
        devices=build_vacuum_devices({}, tanks, ds)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['vacuum_entity'], previous[0]['vacuum_entity'])
        self.assertEqual(tanks['vacuum.0']['used_ml'], 100)
        self.assertEqual(tanks['vacuum.1']['used_ml'], 500)

    def test_distinct_decision_overrides_shared_registry_identity(self):
        ds=self.descriptors([{'id':'one','composite_device_id':'old'},
                             {'id':'two','composite_device_id':'old'}])
        devices=build_vacuum_devices({'robot_links': {'vacuum.1': 'distinct'}}, {}, ds)
        self.assertEqual({d['vacuum_entity'] for d in devices}, {'vacuum.0','vacuum.1'})

    def test_history_owner_wins_and_history_is_not_summed(self):
        ds=self.descriptors([{'id':'same'},{'id':'same'}])
        tanks={'vacuum.1':{'used_ml':100,'initialized':True}}
        devices=build_vacuum_devices({},tanks,ds)
        self.assertEqual([d['vacuum_entity'] for d in devices],['vacuum.1'])
        self.assertEqual(tanks['vacuum.1']['used_ml'],100)
