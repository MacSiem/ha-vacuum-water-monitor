import json,re
from pathlib import Path
import unittest
class FrontendCatalogTests(unittest.TestCase):
    def test_card_never_reintroduces_unverified_rates_or_capacities(self):
        root=Path(__file__).parents[1]
        catalog=json.loads((root/'custom_components/ha_vacuum_water_monitor/model_profiles.json').read_text())['profiles']
        source=(root/'ha-vacuum-water-monitor.js').read_text()
        client=json.loads(re.search(r'const CALIBRATION_DATA = (\{.*?\n\});',source,re.S)[1])
        for key,value in client.items():
            self.assertFalse(value.get('water_per_m2'),key)
            self.assertFalse(value.get('mop_wash_ml'),key)
            if key in catalog:self.assertEqual(value.get('tank_ml'),catalog[key]['tracked_capacity_ml'])
        self.assertIsNone(client['generic']['tank_ml'])

    def test_card_does_not_bypass_server_with_legacy_water_sensor(self):
        source=(Path(__file__).parents[1]/'ha-vacuum-water-monitor.js').read_text()
        calculation=source.split('  _calcDeviceData(device) {',1)[1].split('  _',1)[0]
        self.assertNotIn('_getStateValue(device.water_sensor)',calculation)
        self.assertIn("tankState.last_accounting_source === 'real_sensor'",calculation)
