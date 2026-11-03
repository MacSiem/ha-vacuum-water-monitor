import asyncio
import unittest
from test_user_device_removal import storage

class SprintStorageTests(unittest.TestCase):
    def test_registry_rename_moves_typed_keys_preserving_history_and_stale_tick(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            history = {'used_ml': 432, 'automatic_sessions': [{'source_entity': 'vacuum.a'}]}
            await st.async_set_tank_state('vacuum.a', history)
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.a', 'name': 'A'}],
                'robot_links': {'vacuum.b': 'vacuum.a'},
                'custom_calibration': {'entity:vacuum.a': {'usage_ml_per_m2': {'default': 2}}},
                'local_measurements': {'vacuum.a': [{'historical_entity': 'vacuum.a'}]}})
            self.assertTrue(await st.async_rename_vacuum('vacuum.a', 'vacuum.renamed'))
            await st.async_set_tank_states({'vacuum.a': {'used_ml': 999}})
            return await st.async_get_state()
        result = asyncio.run(run())
        self.assertNotIn('vacuum.a', result['tank_states'])
        self.assertEqual(result['tank_states']['vacuum.renamed']['used_ml'], 432)
        self.assertEqual(result['tank_states']['vacuum.renamed']['automatic_sessions'][0]['source_entity'], 'vacuum.a')
        self.assertEqual(result['settings']['configured_devices'][0]['vacuum_entity'], 'vacuum.renamed')
        self.assertEqual(result['settings']['robot_links']['vacuum.b'], 'vacuum.renamed')
        self.assertIn('entity:vacuum.renamed', result['settings']['custom_calibration'])
        self.assertEqual(result['settings']['local_measurements']['vacuum.renamed'][0]['historical_entity'], 'vacuum.a')

    def test_registry_rename_conflict_keeps_both_banks_and_settings(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            await st.async_set_tank_state('vacuum.a', {'used_ml': 1})
            await st.async_set_tank_state('vacuum.b', {'used_ml': 2})
            before = await st.async_get_state()
            self.assertFalse(await st.async_rename_vacuum('vacuum.a', 'vacuum.b'))
            self.assertEqual(await st.async_get_state(), before)
        asyncio.run(run())

    def test_registry_rename_save_failure_keeps_memory_unchanged(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            await st.async_set_tank_state('vacuum.a', {'used_ml': 1})
            before = await st.async_get_state()
            async def fail(_data):
                raise OSError('synthetic store failure')
            st._store.async_save = fail
            with self.assertRaises(OSError):
                await st.async_rename_vacuum('vacuum.a', 'vacuum.b')
            self.assertEqual(await st.async_get_state(), before)
        asyncio.run(run())

    def test_origin_collision_is_detected_before_any_mutation(self):
        from copy import deepcopy
        data = {'tank_states': {'vacuum.a': {'used_ml': 123}},
                'settings': {'configured_devices': [{'vacuum_entity': 'vacuum.a'}],
                             'robot_links': {'vacuum.other': 'vacuum.a'}},
                'entity_origins': {'vacuum.a': 'vacuum.a', 'vacuum.b': 'vacuum.b'}}
        before = deepcopy(data)
        with self.assertRaises(ValueError):
            storage._move_vacuum_references(data, 'vacuum.a', 'vacuum.b')
        self.assertEqual(data, before)

    def test_offline_reuse_with_missing_original_holds_and_recovers_history(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            original = ['roborock', 'serial-a', 'entry-a']
            replacement = ['matter', 'serial-b', 'entry-b']
            await st.async_reconcile_registry({'vacuum.a': original})
            await st.async_set_tank_state('vacuum.a', {'used_ml': 432, 'history': ['keep']})
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.a', 'water_total_ml': 1234}]})
            await st.async_reconcile_registry({'vacuum.a': replacement})
            held = await st.async_get_state()
            self.assertNotIn('vacuum.a', held['tank_states'])
            self.assertEqual(held['registry_identity_conflicts'][0]['entity_id'], 'vacuum.a')
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.a', 'name': 'B'}]})
            await st.async_reconcile_registry({'vacuum.a': replacement, 'vacuum.renamed': original})
            return await st.async_get_state()
        result = asyncio.run(run())
        self.assertEqual(result['tank_states']['vacuum.renamed']['used_ml'], 432)
        self.assertEqual(result['tank_states']['vacuum.renamed']['history'], ['keep'])
        self.assertNotIn('vacuum.a', result['tank_states'])
        self.assertEqual({d['vacuum_entity'] for d in result['settings']['configured_devices']},
                         {'vacuum.a', 'vacuum.renamed'})

    def test_held_identity_returns_under_same_id_after_reuse_and_repeat(self):
        async def run():
            st = storage.VacuumWaterStorage(None)
            a, b = ['roborock', 'serial-a', 'entry-a'], ['matter', 'serial-b', 'entry-b']
            await st.async_reconcile_registry({'vacuum.a': a})
            await st.async_set_tank_state('vacuum.a', {'used_ml': 432})
            await st.async_set_settings({'configured_devices': [{'vacuum_entity': 'vacuum.a', 'name': 'A'}]})
            await st.async_reconcile_registry({'vacuum.a': b})
            await st.async_set_tank_state('vacuum.a', {'used_ml': 999})
            await st.async_reconcile_registry({'vacuum.a': a})
            await st.async_reconcile_registry({'vacuum.a': a})
            return await st.async_get_state()
        result = asyncio.run(run())
        self.assertEqual(result['tank_states']['vacuum.a']['used_ml'], 432)
        self.assertEqual(result['settings']['configured_devices'][0]['name'], 'A')
        self.assertEqual(result['entity_origins']['vacuum.a'], 'vacuum.a')

    def test_refill_breaks_old_counter_baselines_and_preserves_calibration(self):
        async def run():
            st=storage.VacuumWaterStorage(None)
            await st.async_set_tank_state('vacuum.a',{'used_ml':12,'last_area':99,'last_duration_seconds':44,'last_tick_ts':100,'last_water_volume_ml':200,'wash_sequence_active':True,'calibration_factor':1.2,'future_field':42})
            return await st.async_reset_tank('vacuum.a','2026-09-05T00:00:00Z',200)
        s=asyncio.run(run())
        self.assertIsNone(s['last_area']); self.assertIsNone(s['last_duration_seconds'])
        self.assertEqual(s['calibration_factor'],1.2); self.assertEqual(s['future_field'],42)
        self.assertTrue(s['wash_sequence_active'])

    def test_reprofile_preserves_authored_capacity_calibration_history_and_other_robot(self):
        async def run():
            st=storage.VacuumWaterStorage(None)
            await st.async_set_settings({'configured_devices':[{'vacuum_entity':'vacuum.a','tracked_capacity_ml':1234,'profile_key':'old','profile_locked':True,'config_provenance':{'authored_fields':['vacuum_entity','tracked_capacity_ml','profile_locked']}},{'vacuum_entity':'vacuum.b','tracked_capacity_ml':555}], 'custom_calibration':{'vacuum.a':{'wash_volume_ml':10}}})
            await st.async_set_tank_state('vacuum.a',{'used_ml':15})
            await st.async_reprofile('vacuum.a')
            return await st.async_get_state()
        self.assertTrue(hasattr(storage.VacuumWaterStorage,'async_reprofile'))
        s=asyncio.run(run());d=s['settings']['configured_devices'][0]
        self.assertEqual(d['tracked_capacity_ml'],1234);self.assertNotIn('profile_key',d);self.assertNotIn('profile_locked',d)
        self.assertEqual(s['tank_states']['vacuum.a']['used_ml'],15)
        self.assertEqual(s['settings']['custom_calibration']['vacuum.a']['wash_volume_ml'],10)
        self.assertEqual(s['settings']['configured_devices'][1]['tracked_capacity_ml'],555)

    def test_reset_rejects_non_vacuum_entity(self):
        async def run():
            st=storage.VacuumWaterStorage(None)
            with self.assertRaises(ValueError):await st.async_reset_tank('sensor.unrelated','2026-09-05T00:00:00Z',1)
        asyncio.run(run())

    def test_measurement_save_is_atomic_deduplicated_and_device_scoped(self):
        from test_local_measurements import cycle, measurement
        async def run():
            st=storage.VacuumWaterStorage(None)
            self.assertTrue(callable(getattr(st,'async_save_measurement',None)))
            await st.async_set_tank_state('vacuum.a',{'automatic_sessions':[cycle(1)]})
            await st.async_set_settings({'custom_calibration':{'vacuum.b':{'wash_volume_ml':15}}})
            await st.async_save_measurement('vacuum.a',0,1,measurement())
            with self.assertRaises(ValueError):
                await st.async_save_measurement('vacuum.a',0,1,measurement())
            with self.assertRaises(ValueError):
                await st.async_save_measurement('vacuum.a',0,2,measurement())
            return await st.async_get_state()
        s=asyncio.run(run())
        self.assertEqual(len(s['settings']['local_measurements']['vacuum.a']),1)
        self.assertEqual(s['settings']['custom_calibration']['vacuum.b']['wash_volume_ml'],15)

    def test_measured_profiles_for_multiple_settings_are_preserved(self):
        from test_local_measurements import cycle, measurement
        async def run():
            st=storage.VacuumWaterStorage(None)
            for ts in range(1,7):
                record=cycle(ts)
                if ts>3:record['context']['settings']['route']='deep'
                await st.async_set_tank_state('vacuum.a',{'automatic_sessions':[record]})
                await st.async_save_measurement('vacuum.a',0,ts,measurement())
            return await st.async_get_settings()
        settings=asyncio.run(run())
        profiles=settings['consumption_calibrations']['vacuum.a']
        self.assertIsInstance(profiles,list)
        self.assertEqual(len(profiles),2)
        self.assertEqual({p['context']['settings']['route'] for p in profiles},{'confirmed','deep'})

    def test_refill_invalidates_in_progress_measurement(self):
        async def run():
            st=storage.VacuumWaterStorage(None)
            await st.async_set_tank_state('vacuum.a',{'session_start_ts':1,'session_accounting_valid':True,'session_exposure_complete':True})
            return await st.async_reset_tank('vacuum.a','2026-09-05T00:00:00Z',200)
        state=asyncio.run(run())
        self.assertFalse(state['session_accounting_valid'])
        self.assertFalse(state['session_exposure_complete'])

    def test_refill_preserves_v2_identity_journal_and_other_vacuum(self):
        async def run():
            st=storage.VacuumWaterStorage(None)
            v2={'schema_version':2,'journal':{'baseline':{'id':'physical.1'},'hashes':['immutable']},'balances_ml':None,'status':'unknown'}
            await st.async_set_tank_state('vacuum.a',{'accounting_v2':v2})
            await st.async_set_tank_state('vacuum.b',{'used_ml':123})
            await st.async_reset_tank('vacuum.a','2026-09-05T00:00:00Z',200)
            state=await st.async_get_state()
            self.assertEqual(state['tank_states']['vacuum.a']['accounting_v2'],v2)
            self.assertEqual(state['tank_states']['vacuum.b']['used_ml'],123)
        asyncio.run(run())
