"""Explicit user-device removal bypasses the empty-list guard (issue #4).

The generic set_settings guard refuses empty-list patches to protect against
accidental frontend init writes. An explicit user delete of the last device
must still persist an empty list, which the remove_user_device command does
via async_replace_settings_key. These tests load storage.py with minimal
homeassistant stubs (no HA install needed), matching the repo's test style.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _stub_homeassistant() -> None:
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    storage_mod = types.ModuleType("homeassistant.helpers.storage")

    class _Store:
        def __init__(self, *args, **kwargs):
            self._d = None

        async def async_load(self):
            return self._d

        async def async_save(self, data):
            self._d = data

    storage_mod.Store = _Store
    ha.core = core
    ha.helpers = helpers
    helpers.storage = storage_mod
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.storage", storage_mod)


def _load_storage():
    _stub_homeassistant()
    pkg = types.ModuleType("vwmpkg")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["vwmpkg"] = pkg
    const = types.ModuleType("vwmpkg.const")
    const.DEFAULT_CRITICAL_THRESHOLD = 10
    const.DEFAULT_WARNING_THRESHOLD = 25
    const.STORAGE_KEY = "ha_vacuum_water_monitor"
    const.STORAGE_VERSION = 1
    sys.modules["vwmpkg.const"] = const
    spec = importlib.util.spec_from_file_location("vwmpkg.storage", PKG_DIR / "storage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vwmpkg.storage"] = mod
    spec.loader.exec_module(mod)
    return mod


storage = _load_storage()


def _remove(devices, entity):
    return [
        d
        for d in (devices or [])
        if not (isinstance(d, dict) and d.get("vacuum_entity") == entity)
    ]


class UserDeviceRemovalTest(unittest.TestCase):
    def test_guard_refuses_empty_via_set_settings(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            await st.async_set_settings({"user_devices": [{"vacuum_entity": "vacuum.a"}]})
            await st.async_set_settings({"user_devices": []})
            return await st.async_get_settings()

        s = asyncio.run(scenario())
        self.assertEqual(s["user_devices"], [{"vacuum_entity": "vacuum.a"}])

    def test_replace_key_persists_empty(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            await st.async_set_settings({"user_devices": [{"vacuum_entity": "vacuum.a"}]})
            await st.async_replace_settings_key("user_devices", [])
            return await st.async_get_settings()

        s = asyncio.run(scenario())
        self.assertEqual(s["user_devices"], [])

    def test_remove_command_flow_down_to_empty(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            await st.async_set_settings(
                {"user_devices": [{"vacuum_entity": "vacuum.a"}, {"vacuum_entity": "vacuum.b"}]}
            )
            cur = await st.async_get_settings()
            await st.async_replace_settings_key("user_devices", _remove(cur["user_devices"], "vacuum.a"))
            mid = await st.async_get_settings()
            await st.async_replace_settings_key("user_devices", _remove(mid["user_devices"], "vacuum.b"))
            return await st.async_get_settings()

        s = asyncio.run(scenario())
        self.assertEqual(s["user_devices"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
