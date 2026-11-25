"""Manual refill measurements use only the completed tick's exposure."""
import asyncio
from copy import deepcopy

import pytest
from test_user_device_removal import storage
from test_local_measurements import measurement
from test_beta_runtime_path import effective, descriptor


def observation(ts, area, count):
    return {'id': 'split.' + str(ts),
            'identity': {'robot': 'vacuum.a', 'station': 'dock1', 'reservoir': 'dock_clean',
                         'floor_context': {'water_level': 'wet'}, 'wash_context': {'wash_mode': 'normal'}},
            'quality': {'boundaries_confirmed': True, 'uninterrupted': True, 'exposure_complete': True,
                        'settings_constant': True, 'same_reservoir': True,
                        'intervening_refill': False, 'unmeasured_transfer': False},
            'area_m2': area, 'wash_count': count}


def test_manual_refill_persists_private_sample_and_qualifies_rate():
    async def run():
        st = storage.VacuumWaterStorage(None)
        for ts in range(1, 5):
            obs = observation(ts, ts * 10, 0)
            await st.async_set_tank_state('vacuum.a', {'automatic_sessions': [{'ts': ts, 'split_observation': obs}]})
            values = {**measurement(), 'observed_ml': ts * 20, 'resolution_ml': 1,
                      'purpose': 'validation' if ts == 4 else 'training', 'area_m2': 999}
            result = await st.async_save_measurement('vacuum.a', 0, ts, values)
        assert result['split_calibration']['floor_ml_per_m2'] == 2
        assert result['split_calibration']['wash_ml_per_completed_action'] is None
        settings = await st.async_get_settings()
        assert settings['split_measurements']['vacuum.a'][0]['area_m2'] == 10
        with pytest.raises(ValueError):
            await st.async_save_measurement('vacuum.a', 0, 4, values)
        with pytest.raises(ValueError):
            await st.async_set_settings({'split_measurements': {}})
        device = effective(settings, descriptor())
        # Descriptor belongs to another robot; no sample can cross devices.
        assert 'split_measurements' not in device
    asyncio.run(run())


def test_bad_tick_record_cannot_be_confirmed_by_payload():
    async def run():
        st = storage.VacuumWaterStorage(None)
        bad = observation(1, 10, 1)
        bad['quality']['same_reservoir'] = False
        await st.async_set_tank_state('vacuum.a', {'automatic_sessions': [{'ts': 1, 'split_observation': bad}]})
        with pytest.raises(ValueError):
            await st.async_save_measurement('vacuum.a', 0, 1, measurement())
        bad = deepcopy(bad)
        bad['quality']['same_reservoir'] = True
        bad['identity']['robot'] = 'vacuum.other'
        await st.async_set_tank_state('vacuum.a', {'automatic_sessions': [{'ts': 1, 'split_observation': bad}]})
        with pytest.raises(ValueError):
            await st.async_save_measurement('vacuum.a', 0, 1, measurement())
    asyncio.run(run())


def test_rename_preserves_recorded_identity_and_proves_projection():
    saved = {**observation(1, 10, 0), 'device_id': 'vacuum.a', 'identity_scope': 'vacuum.a'}
    data = {'settings': {'split_measurements': {'vacuum.a': [saved]}}, 'tank_states': {}}
    storage._move_vacuum_references(data, 'vacuum.a', 'vacuum.renamed')
    origin, proven = storage.measurement_identity(data, 'vacuum.renamed')
    record = data['settings']['split_measurements']['vacuum.renamed'][0]
    assert storage.measurement_belongs(record, origin, proven)
    assert storage.measurement_projection(record, origin, proven)['identity']['robot'] == origin
    assert record['identity']['robot'] == 'vacuum.a'


def test_websocket_refreshes_when_split_rate_qualifies():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    path = Path(__file__).parents[1] / 'custom_components/ha_vacuum_water_monitor/websocket_api.py'
    tree = ast.parse(path.read_text())
    handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_ws_save_measurement')
    handler.decorator_list = []
    async def run():
        st = storage.VacuumWaterStorage(None)
        refreshed = []
        async def refresh(_):
            refreshed.append(True)
            return True
        ns = {'_storage': lambda _: st, '_notify_store_updated': lambda *args: None, '_refresh_bindings': refresh}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), 'exec'), ns)
        results, errors = [], []
        connection = SimpleNamespace(send_result=lambda *args: results.append(args), send_error=lambda *args: errors.append(args))
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: object()))
        for ts in range(1, 5):
            await st.async_set_tank_state('vacuum.a', {'automatic_sessions': [{'ts': ts, 'split_observation': observation(ts, ts * 10, 0)}]})
            values = {**measurement(), 'observed_ml': ts * 20, 'resolution_ml': 1,
                      'purpose': 'validation' if ts == 4 else 'training'}
            await ns['_ws_save_measurement'](hass, connection, {'id': ts, 'vacuum_entity': 'vacuum.a',
                'session_index': 0, 'session_ts': ts, 'measurement': values})
        assert not errors
        assert refreshed == [True]
        assert results[-1][1]['split_calibration']['floor_ml_per_m2'] == 2
    asyncio.run(run())
