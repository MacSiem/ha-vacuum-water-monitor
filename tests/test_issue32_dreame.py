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
        {'id': 'matter', 'manufacturer': 'Dreame', 'model': 'R2538Z', 'model_id': '98'},
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
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.matter', 'profile_key': 'generic', 'tracked_capacity_ml': 1234, 'config_provenance': {'authored_fields': ['vacuum_entity', 'tracked_capacity_ml']}}]})
            await st.async_set_tank_state('vacuum.matter', {'used_ml': 123, 'refill_history': [{'ts': 1}]})
            await st.async_reprofile('vacuum.matter')
            return await st.async_get_state()
        state = asyncio.run(run())
        desc = next(d for d in descriptors() if d['entity_id'] == 'vacuum.matter')
        cfg = effective(state['settings'], desc)
        self.assertEqual(cfg['profile_key'], 'dreame_x50_ultra')
        self.assertEqual(cfg['tracked_capacity_ml'], 1234)
        self.assertEqual(state['tank_states']['vacuum.matter']['used_ml'], 123)
        self.assertEqual(state['tank_states']['vacuum.matter']['refill_history'], [{'ts': 1}])

    def test_composite_requires_all_registry_facts_and_retains_precedence(self):
        def resolve(**changes):
            record = {'id': 'd', 'manufacturer': 'Dreame', 'model': 'R2538Z', 'model_id': '98'}
            platform = changes.pop('platform', 'matter')
            record.update(changes)
            return discovery.discover_descriptors([{'entity_id': 'vacuum.other', 'device_id': 'd', 'platform': platform}], [record], {})[0]
        self.assertEqual(resolve()['profile_key'], 'dreame_x50_ultra')
        self.assertEqual(resolve(model='R2538Z (98)', model_id=None)['profile_key'], 'dreame_x50_ultra')
        for changes in ({'model_id': None}, {'model_id': '99'}, {'model': 'R2538A'},
                        {'manufacturer': 'Other'}, {'manufacturer': None}, {'platform': 'mqtt'}):
            self.assertIsNone(resolve(**changes)['profile_key'], changes)
        self.assertEqual(resolve(model_id='a97', manufacturer='Roborock')['profile_key'], 'roborock_s8_maxv_ultra')

    def test_distinct_strong_models_do_not_suggest_but_decisions_remain(self):
        entities = [{'entity_id': 'vacuum.native', 'platform': 'dreame_vacuum', 'device_id': 'n'},
                    {'entity_id': 'vacuum.matter', 'platform': 'matter', 'device_id': 'm'}]
        devices = [{'id': 'n', 'manufacturer': 'Dreame', 'model': 'dreame.vacuum.r2538z'},
                   {'id': 'm', 'manufacturer': 'Dreame', 'model': 'Dreame L10 Ultra'}]
        found = discovery.discover_descriptors(entities, devices, {})
        matter = next(d for d in found if d['entity_id'] == 'vacuum.matter')
        self.assertEqual(matter['profile_key'], 'dreame_l10_ultra')
        self.assertNotIn('possible_duplicate_of', matter)
        linked = sc.build_vacuum_devices({'robot_links': {'vacuum.matter': 'vacuum.native'}}, {}, found)
        self.assertEqual([d['vacuum_entity'] for d in linked], ['vacuum.native'])
        distinct = sc.build_vacuum_devices({'robot_links': {'vacuum.matter': 'distinct'}}, {}, found)
        self.assertEqual(len(distinct), 2)

    def test_identifiers_are_scoped_and_exact(self):
        for manufacturer, model in [('Dreame', 'R2538Z (99)'), ('Dreame', 'dreame.vacuum.r2538a'), ('Other', 'dreame.vacuum.r2538z'), ('Other', 'R2538Z (98)')]:
            d = discovery.discover_descriptors([{'entity_id': 'vacuum.other', 'device_id': 'd'}], [{'id': 'd', 'manufacturer': manufacturer, 'model': model}], {})[0]
            self.assertIsNone(d['profile_key'])
