import json,re
from pathlib import Path
import unittest
class FrontendCatalogTests(unittest.TestCase):
    def test_card_rates_are_always_labelled_and_capacities_match_backend(self):
        root=Path(__file__).parents[1]
        catalog=json.loads((root/'custom_components/ha_vacuum_water_monitor/model_profiles.json').read_text())['profiles']
        source=(root/'ha-vacuum-water-monitor.js').read_text()
        client=json.loads(re.search(r'const CALIBRATION_DATA = (\{.*?\n\});',source,re.S)[1])
        for key,value in client.items():
            if value.get('water_per_m2') or value.get('mop_wash_ml'):
                self.assertTrue(value.get('estimate_basis'),key)
                self.assertTrue(value.get('uncertainty_percent'),key)
            if key in catalog:
                caps=catalog[key]['reservoirs_ml']
                declared=catalog[key]['tracked_capacity_ml']
                self.assertEqual(value.get('tank_ml'),declared if declared else (caps['dock_clean'] or caps['robot_clean']))
        self.assertIsNone(client['generic']['tank_ml'])
        self.assertIsNone(client['generic']['estimate_basis'])
        t90 = client['ecovacs_deebot_t90_pro_omni']
        self.assertEqual(t90['tank_ml'], 4000)
        self.assertEqual(t90['water_per_m2'], {})
        self.assertIsNone(t90['mop_wash_ml'])
        self.assertIsNone(t90['estimate_basis'])
        self.assertIn('No verified automatic empty-tank signal', t90['notes'])
        self.assertIn('confirm refills manually', t90['notes'])
        self.assertEqual(t90['profile_descriptor']['usage_ml_per_m2'], {})

    def test_card_does_not_bypass_server_with_legacy_water_sensor(self):
        source=(Path(__file__).parents[1]/'ha-vacuum-water-monitor.js').read_text()
        calculation=source.split('  _calcDeviceData(device) {',1)[1].split('  _',1)[0]
        self.assertNotIn('_getStateValue(device.water_sensor)',calculation)
        self.assertIn("tankState.last_accounting_source === 'real_sensor'",calculation)
