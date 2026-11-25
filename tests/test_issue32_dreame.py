"""Issue 32 registry identities, profile refresh, and bridge handling."""
import asyncio
import unittest
from test_beta_runtime_path import discovery, effective, sc
from test_sprint_storage import storage


def descriptors():
    return discovery.discover_descriptors([
        {'entity_id': 'vacuum.native', 'platform': 'dreame_vacuum', 'device_id': 'native'},
        {'entity_id': 'vacuum.matter', 'platform': 'matter', 'device_id': 'matter'},
    ], [
        {'id': 'native', 'manufacturer': 'Dreametech™', 'model': 'dreame.vacuum.r2538z'},
        {'id': 'matter', 'manufacturer': 'Dreame', 'model': 'R2538Z (98)'},
    ], {})


class Issue32Tests(unittest.TestCase):
    def test_registry_to_configuration_and_bridge(self):
        found = {d['entity_id']: d for d in descriptors()}
        for d in found.values():
            self.assertEqual(d['profile_key'], 'dreame_x50_ultra')
            cfg = effective({}, d)
            self.assertEqual(cfg['tracked_capacity_ml'], 4500)
            self.assertIsNone(cfg['reservoirs_ml']['robot_clean'])
            self.assertFalse(cfg.get('usage_ml_per_m2'))
            self.assertIsNone(cfg.get('wash_volume_ml'))
        self.assertEqual(found['vacuum.matter']['possible_duplicate_of'], 'vacuum.native')
        linked = sc.build_vacuum_devices({'robot_links': {'vacuum.matter': 'vacuum.native'}}, {}, list(found.values()))
        self.assertEqual([d['vacuum_entity'] for d in linked], ['vacuum.native'])

    def test_refresh_preserves_user_data_and_uses_new_discovery(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.native', 'profile_key': 'generic', 'tracked_capacity_ml': 1234, 'config_provenance': {'authored_fields': ['vacuum_entity', 'tracked_capacity_ml']}}]})
            await st.async_set_tank_state('vacuum.native', {'used_ml': 123})
            await st.async_reprofile('vacuum.native')
            return await st.async_get_state()
        state = asyncio.run(run())
        desc = next(d for d in descriptors() if d['entity_id'] == 'vacuum.native')
        cfg = effective(state['settings'], desc)
        self.assertEqual(cfg['profile_key'], 'dreame_x50_ultra')
        self.assertEqual(cfg['tracked_capacity_ml'], 1234)
        self.assertEqual(state['tank_states']['vacuum.native']['used_ml'], 123)

    def test_identifiers_are_scoped_and_exact(self):
        for manufacturer, model in [('Dreame', 'R2538Z (99)'), ('Dreame', 'dreame.vacuum.r2538a'), ('Other', 'dreame.vacuum.r2538z'), ('Other', 'R2538Z (98)')]:
            d = discovery.discover_descriptors([{'entity_id': 'vacuum.other', 'device_id': 'd'}], [{'id': 'd', 'manufacturer': manufacturer, 'model': model}], {})[0]
            self.assertIsNone(d['profile_key'])
