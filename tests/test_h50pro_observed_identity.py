import unittest
from test_beta_estimation import profiles
from test_beta_runtime_path import discovery, effective
import test_signal_mapping as mapping

class H50ObservedIdentityTests(unittest.TestCase):
    def test_reported_miot_model_only_recognizes_h50_pro(self):
        entities, devices, states = mapping.XiaomiHomeSignalMappingTests()._fixture()
        devices[0]["model"]="xiaomi.vacuum.ov42gl"
        devices[0]["model_id"]="xiaomi.vacuum.ov42gl"
        devices[0]["name"]="Робот-уборщик"
        device=effective({}, discovery.discover_descriptors(entities,devices,states)[0])
        self.assertEqual(device.get("profile_key"),"xiaomi_h50_pro")
        self.assertEqual(device["mop_system"],"rotating_pads")
        self.assertTrue(device.get("mop_intensity_entity"))
        self.assertEqual(device["accounting_evidence"],"labeled_estimate")

    def test_unknown_sibling_model_is_not_guessed(self):
        p=profiles.resolve_profile({"manufacturer":"Xiaomi","model":"xiaomi.vacuum.ov43gl"})
        self.assertNotEqual(p["profile_key"],"xiaomi_h50_pro")
