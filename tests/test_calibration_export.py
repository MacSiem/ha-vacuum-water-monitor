"""Public drafts must never turn private history or estimates into measurements."""
import importlib.util
from pathlib import Path
import json
import unittest
import ast
import asyncio
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('calibration_export', Path(__file__).parents[1] / 'custom_components/ha_vacuum_water_monitor/calibration.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CalibrationExportTests(unittest.TestCase):
    def test_websocket_preview_reads_state_without_mutation(self):
        # Execute the actual handler with only its HA boundary substituted.
        path = Path(__file__).parents[1] / 'custom_components/ha_vacuum_water_monitor/websocket_api.py'
        tree = ast.parse(path.read_text())
        handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_ws_calibration_preview')
        handler.decorator_list = []
        state = {'tank_states': {'vacuum.test': {'automatic_sessions': [{'ts': 100, 'area': 25, 'water': 80}]}}, 'settings': {'secret': 'PRIVATE'}}
        before = json.dumps(state)
        async def get_state():
            return state
        namespace = {'_storage': lambda _: SimpleNamespace(async_get_state=get_state),
                     'build_contribution_draft': module.build_contribution_draft,
                     'select_recorded_cycle': module.select_recorded_cycle}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), 'exec'), namespace)
        results, errors = [], []
        connection = SimpleNamespace(send_result=lambda *x: results.append(x), send_error=lambda *x: errors.append(x))
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: object()))
        msg = {'id': 1, 'vacuum_entity': 'vacuum.test', 'session_ts': 100, 'observed_ml': 90, 'resolution_ml': 5}
        asyncio.run(namespace['_ws_calibration_preview'](hass, connection, msg))
        self.assertEqual(results[0][1]['measurement']['observed_ml'], 90)
        self.assertNotIn('PRIVATE', json.dumps(results))
        self.assertEqual(json.dumps(state), before)
        asyncio.run(namespace['_ws_calibration_preview'](hass, connection, {**msg, 'session_ts': 99}))
        self.assertEqual(errors[0][1], 'invalid_payload')
        self.assertEqual(len(results), 1)

    def test_new_cycle_cannot_silently_retarget_measurement(self):
        old = {'ts': 100, 'water': 10}
        self.assertIs(module.select_recorded_cycle([old], 0, 100), old)
        with self.assertRaises(ValueError):
            module.select_recorded_cycle([{'ts': 200}, old], 0, 100)
        for index in (-1, True, 50):
            with self.assertRaises(ValueError):
                module.select_recorded_cycle([old], index, 100)

    def test_corrupt_history_is_a_validation_error(self):
        for sessions in ({'ts': 100}, None, 'private', [None]):
            with self.subTest(sessions=sessions):
                with self.assertRaises(ValueError):
                    module.select_recorded_cycle(sessions, 0, 100)

    def test_only_numeric_summary_leaves_private_history(self):
        record = {'ts': 123456, 'started_ts': 123, 'name': 'PRIVATE_ROOM',
                  'device_id': 'PRIVATE_ID', 'map': {'secret': 'PRIVATE_MAP'},
                  'water': 150, 'area': 30, 'duration': 45,
                  'method': 'PRIVATE_METHOD', 'evidence': 'user_calibration'}
        result = module.build_contribution_draft(record, 200, 5)
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE', serialized)
        self.assertNotIn('123456', serialized)
        self.assertEqual(result['session']['estimated_water_ml'], 150)
        self.assertEqual(result['measurement']['observed_ml'], 200)
        self.assertFalse(result['runtime_eligible'])
        self.assertIn('historical_settings', result['missing'])

    def test_estimation_is_never_promoted_to_measurement(self):
        for evidence in ('measured_volume', 'device_calibrated', 'user_calibration', None):
            with self.subTest(evidence=evidence):
                result = module.build_contribution_draft({'water': 80, 'evidence': evidence})
                self.assertIsNone(result['measurement'])
                self.assertEqual(result['session']['estimated_water_ml'], 80)

    def test_bad_numbers_and_missing_resolution_rejected(self):
        for volume, resolution in ((100, None), (None, 5), (float('nan'), 1),
                                   (100, float('inf')), (True, 1), (-1, 1), (100, 0)):
            with self.subTest(volume=volume, resolution=resolution):
                with self.assertRaises(ValueError):
                    module.build_contribution_draft({}, volume, resolution)

    def test_free_text_and_nonfinite_history_become_unknown(self):
        result = module.build_contribution_draft({'area': 'sensor.private', 'duration': '45m', 'water': float('inf')})
        self.assertEqual(result['session'], {'area_delta_m2': None, 'elapsed_minutes': None, 'estimated_water_ml': None})
        json.dumps(result, allow_nan=False)
