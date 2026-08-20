"""Regression tests for bounded state-changing WebSocket commands and Store data."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


PKG_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "ha_vacuum_water_monitor"
)


def _load_websocket_module():
    """Load websocket_api.py with the Home Assistant surface stubbed."""
    vol = types.ModuleType("voluptuous")
    vol.Required = lambda key: key

    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    ws = types.ModuleType("homeassistant.components.websocket_api")
    ws.ActiveConnection = object
    ws.websocket_command = lambda _schema: lambda func: func
    ws.async_response = lambda func: func
    ws.async_register_command = lambda *args, **kwargs: None
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda func: func
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    dispatcher.async_dispatcher_send = lambda *args, **kwargs: None

    modules = {
        "voluptuous": vol,
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.websocket_api": ws,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.dispatcher": dispatcher,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)

    package_name = "vwm_command_boundaries_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PKG_DIR)]
    sys.modules[package_name] = package

    const = types.ModuleType(f"{package_name}.const")
    const.DOMAIN = "ha_vacuum_water_monitor"
    const.EVENT_STATE_CHANGED = "ha_vacuum_water_monitor_state_changed"
    const.signal_vacuum_water_updated = lambda entry_id: f"updated_{entry_id}"
    sys.modules[const.__name__] = const

    storage = types.ModuleType(f"{package_name}.storage")
    storage.VacuumWaterStorage = object
    sys.modules[storage.__name__] = storage

    tick = types.ModuleType(f"{package_name}.tick")
    tick.list_vacuums = lambda _hass: []
    sys.modules[tick.__name__] = tick

    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.websocket_api", PKG_DIR / "websocket_api.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in previous.items():
            if old_module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


def _load_storage_module():
    """Load storage.py with an in-memory replacement for HA's Store."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    storage_helper = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args, **kwargs) -> None:
            self.loaded = None
            self.saves = []

        async def async_load(self):
            return deepcopy(self.loaded)

        async def async_save(self, data) -> None:
            self.saves.append(deepcopy(data))

    storage_helper.Store = Store
    modules = {
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage_helper,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)

    package_name = "vwm_storage_boundaries_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PKG_DIR)]
    sys.modules[package_name] = package

    const = types.ModuleType(f"{package_name}.const")
    const.DEFAULT_CRITICAL_THRESHOLD = 10
    const.DEFAULT_WARNING_THRESHOLD = 20
    const.STORAGE_KEY = "ha_vacuum_water_monitor"
    const.STORAGE_VERSION = 1
    sys.modules[const.__name__] = const

    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.storage", PKG_DIR / "storage.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in previous.items():
            if old_module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


websocket_api = _load_websocket_module()
storage_module = _load_storage_module()


class _Connection:
    def __init__(self) -> None:
        self.results = []
        self.errors = []

    def send_result(self, msg_id, payload=None) -> None:
        self.results.append((msg_id, payload))

    def send_error(self, msg_id, code, message) -> None:
        self.errors.append((msg_id, code, message))


class _States:
    def __init__(self, states=None) -> None:
        self._states = dict(states or {})

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_entity_ids(self, domain=None):
        entity_ids = list(self._states)
        if domain is None:
            return entity_ids
        prefix = f"{domain}."
        return [entity_id for entity_id in entity_ids if entity_id.startswith(prefix)]


class _CommandStorage:
    def __init__(self) -> None:
        self.reset_calls = []
        self.settings_reads = 0
        self.settings_writes = []

    async def async_reset_tank(self, vacuum_entity, when_iso, when_ts):
        self.reset_calls.append((vacuum_entity, when_iso, when_ts))
        return {
            "used_ml": 0,
            "last_reset_iso": when_iso,
            "last_reset_ts": when_ts,
        }

    async def async_get_settings(self):
        self.settings_reads += 1
        return {"intro_dismissed": {"existing-intro": True}}

    async def async_set_settings(self, patch):
        self.settings_writes.append(deepcopy(patch))
        return deepcopy(patch)


def _command_hass(storage, states=None):
    return types.SimpleNamespace(
        data={websocket_api.DOMAIN: {"storage": storage}},
        states=_States(states),
    )


class StateChangingCommandBoundaryTest(unittest.TestCase):
    """Untrusted command arguments must not create arbitrary stored keys."""

    def _run_reset(self, entity_id, states=None):
        storage = _CommandStorage()
        connection = _Connection()
        notifications = []
        websocket_api._notify_store_updated = (
            lambda _hass, payload: notifications.append(deepcopy(payload))
        )
        asyncio.run(
            websocket_api._ws_reset_tank(
                _command_hass(storage, states),
                connection,
                {"id": 41, "vacuum_entity": entity_id},
            )
        )
        return storage, connection, notifications

    def _run_dismiss(self, tag):
        storage = _CommandStorage()
        connection = _Connection()
        notifications = []
        websocket_api._notify_store_updated = (
            lambda _hass, payload: notifications.append(deepcopy(payload))
        )
        asyncio.run(
            websocket_api._ws_dismiss_intro(
                _command_hass(storage),
                connection,
                {"id": 42, "tag": tag},
            )
        )
        return storage, connection, notifications

    def test_reset_rejects_malformed_and_nonexistent_entities_atomically(self) -> None:
        invalid_entities = (
            "",
            "sensor.kitchen",
            "vacuum.Kitchen-Robot",
            " vacuum.kitchen",
            "vacuum.kitchen robot",
            "vacuum.missing",
        )
        live_states = {
            "vacuum.kitchen": types.SimpleNamespace(
                entity_id="vacuum.kitchen", state="docked"
            )
        }

        for entity_id in invalid_entities:
            with self.subTest(entity_id=entity_id):
                storage, connection, notifications = self._run_reset(
                    entity_id, live_states
                )
                self.assertEqual(storage.reset_calls, [])
                self.assertEqual(connection.results, [])
                self.assertEqual(notifications, [])
                self.assertEqual(len(connection.errors), 1)
                self.assertEqual(connection.errors[0][0], 41)
                self.assertTrue(connection.errors[0][1])
                self.assertTrue(connection.errors[0][2])

    def test_reset_accepts_a_canonical_live_vacuum_entity(self) -> None:
        live_state = types.SimpleNamespace(
            entity_id="vacuum.kitchen", state="docked"
        )
        storage, connection, notifications = self._run_reset(
            "vacuum.kitchen", {"vacuum.kitchen": live_state}
        )

        self.assertEqual(len(storage.reset_calls), 1)
        entity_id, when_iso, when_ts = storage.reset_calls[0]
        self.assertEqual(entity_id, "vacuum.kitchen")
        self.assertIsInstance(when_iso, str)
        self.assertGreater(when_ts, 0)
        state = connection.results[0][1]["state"]
        self.assertEqual(connection.errors, [])
        self.assertEqual(connection.results, [(41, {"state": state})])
        self.assertEqual(
            notifications,
            [{"tank_states": {"vacuum.kitchen": state}}],
        )

    def test_dismiss_intro_rejects_malformed_and_overlong_tags(self) -> None:
        invalid_tags = (
            "",
            " leading-space",
            "ha/vacuum-water-monitor",
            "<script>alert(1)</script>",
            "x" * 10_000,
        )

        for tag in invalid_tags:
            with self.subTest(tag=tag[:80]):
                storage, connection, notifications = self._run_dismiss(tag)
                self.assertEqual(storage.settings_writes, [])
                self.assertEqual(connection.results, [])
                self.assertEqual(notifications, [])
                self.assertEqual(len(connection.errors), 1)
                self.assertEqual(connection.errors[0][0], 42)
                self.assertTrue(connection.errors[0][1])
                self.assertTrue(connection.errors[0][2])


class StorageBoundaryTest(unittest.TestCase):
    """Persistent state stays within the integration's fixed storage budget."""

    def _storage(self, loaded=None):
        instance = storage_module.VacuumWaterStorage(None)
        instance._store.loaded = deepcopy(loaded)
        return instance

    def test_tank_states_are_capped_at_one_hundred_entries(self) -> None:
        self.assertEqual(storage_module.MAX_TANK_STATES, 100)
        existing = {
            f"vacuum.robot_{index:03d}": {"used_ml": index}
            for index in range(100)
        }
        storage = self._storage({"tank_states": existing})

        async def scenario():
            before = await storage.async_get_state()
            with self.assertRaises(ValueError):
                await storage.async_set_tank_state(
                    "vacuum.one_too_many", {"used_ml": 1}
                )
            after = await storage.async_get_state()
            return before, after

        before, after = asyncio.run(scenario())

        self.assertEqual(len(before["tank_states"]), 100)
        self.assertEqual(after, before)
        self.assertEqual(storage._store.saves, [])

    def test_writes_cannot_grow_serialized_state_beyond_one_megabyte(self) -> None:
        self.assertEqual(storage_module.MAX_STORAGE_BYTES, 1_000_000)
        storage = self._storage()
        oversized_tanks = {
            f"vacuum.robot_{index:03d}": {
                "used_ml": index,
                "legacy_blob": "x" * 11_000,
            }
            for index in range(100)
        }
        candidate = storage_module._default_state()
        candidate["tank_states"] = oversized_tanks
        self.assertGreater(
            storage_module._serialized_bytes(candidate),
            storage_module.MAX_STORAGE_BYTES,
        )

        async def scenario():
            before = await storage.async_get_state()
            with self.assertRaises(ValueError):
                await storage.async_set_tank_states(oversized_tanks)
            after = await storage.async_get_state()
            return before, after

        before, after = asyncio.run(scenario())

        self.assertEqual(after, before)
        self.assertEqual(storage._store.saves, [])

    def test_size_reducing_write_is_allowed_for_oversized_legacy_state(self) -> None:
        loaded = {
            "settings": {
                "future_blob": "x" * 1_020_000,
                "future_note": "legacy",
            },
            "tank_states": {},
        }
        storage = self._storage(loaded)

        async def scenario():
            before = await storage.async_get_state()
            settings = await storage.async_set_settings(
                {"future_blob": "x" * 1_010_000}
            )
            after = await storage.async_get_state()
            return before, settings, after

        before, settings, after = asyncio.run(scenario())

        compact_size = lambda value: len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        self.assertGreater(compact_size(before), 1_000_000)
        self.assertGreater(compact_size(after), 1_000_000)
        self.assertLess(compact_size(after), compact_size(before))
        self.assertEqual(settings["future_blob"], "x" * 1_010_000)
        self.assertEqual(storage._store.saves, [after])


if __name__ == "__main__":
    unittest.main(verbosity=2)
