import json
from pathlib import Path
import unittest
from test_discovery import _load_discovery
from test_tick import _State
class AdapterFixtureTests(unittest.TestCase):
    def test_each_documented_contract_binds_and_foreign_device_never_binds(self):
        corpus=json.loads((Path(__file__).parent/'fixtures/adapter_contracts.json').read_text())
        for case in corpus['cases']:
            with self.subTest(adapter=case['adapter']):
                d=_load_discovery();states={k:_State(**v) for k,v in case['states'].items()}
                desc=d.discover_descriptors(case['entities'],case['devices'],states)[0]
                self.assertEqual(desc['integration_adapter'],case['adapter'])
                for role,eid in case['expected_signals'].items():self.assertEqual(desc['signals'].get(role),eid)
                foreign=[{**e,'device_id':'other'} if not e['entity_id'].startswith('vacuum.') else e for e in case['entities']]
                desc=d.discover_descriptors(foreign,case['devices'],states)[0]
                self.assertEqual(desc['signals'],{})
