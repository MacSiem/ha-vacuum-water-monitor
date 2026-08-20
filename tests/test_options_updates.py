"""Regression tests for live config-entry option updates."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
import types
import unittest
from pathlib import Path


PKG_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "ha_vacuum_water_monitor"
)


def _load_integration_module():
    """Load the integration entry point with minimal Home Assistant stubs."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    frontend = types.ModuleType("homeassistant.components.frontend")
    frontend.add_extra_js_url = lambda *args, **kwargs: None
    http = types.ModuleType("homeassistant.components.http")
    http.StaticPathConfig = object
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.Platform = types.SimpleNamespace(SENSOR="sensor")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *args, **kwargs: None

    ha_modules = {
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.frontend": frontend,
        "homeassistant.components.http": http,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": ha_const,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.dispatcher": dispatcher,
        "homeassistant.helpers.event": event,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in ha_modules}
    sys.modules.update(ha_modules)

    package_name = "vwm_options_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PKG_DIR)]
    sys.modules[package_name] = package

    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", PKG_DIR / "const.py"
    )
    assert const_spec and const_spec.loader
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules[f"{package_name}.const"] = const_module
    const_spec.loader.exec_module(const_module)

    storage_module = types.ModuleType(f"{package_name}.storage")
    storage_module.VacuumWaterStorage = object
    sys.modules[storage_module.__name__] = storage_module

    tick_module = types.ModuleType(f"{package_name}.tick")

    async def _unused_tick(*args, **kwargs):
        return {}

    tick_module.async_tick_water_state = _unused_tick
    sys.modules[tick_module.__name__] = tick_module

    websocket_module = types.ModuleType(f"{package_name}.websocket_api")
    websocket_module.async_register_commands = lambda *args, **kwargs: None
    sys.modules[websocket_module.__name__] = websocket_module

    try:
        # SourceFileLoader avoids treating the source path's ``__init__.py`` as
        # another package level; relative imports must resolve to the stubs above.
        loader = importlib.machinery.SourceFileLoader(
            f"{package_name}.integration", str(PKG_DIR / "__init__.py")
        )
        spec = importlib.util.spec_from_loader(
            loader.name, loader, is_package=False
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


integration = _load_integration_module()


class OptionsUpdatedTest(unittest.TestCase):
    """Verify option writes notify every Store consumer with full settings."""

    def test_write_precedes_dispatcher_and_bus_events_with_full_settings(self) -> None:
        order = []
        full_settings = {
            "warning_threshold": 30,
            "critical_threshold": 8,
            "configured_devices": [{"vacuum_entity": "vacuum.downstairs"}],
            "maintenance_items": [{"name": "Clean sensor", "intervalDays": 14}],
        }

        class Storage:
            async def async_set_settings(self, patch):
                order.append(("write", patch))
                return full_settings

        class Bus:
            def async_fire(self, event_type, payload):
                order.append(("bus", event_type, payload))

        def send_dispatcher(hass, signal, payload):
            order.append(("dispatcher", signal, payload))

        integration.async_dispatcher_send = send_dispatcher
        hass = types.SimpleNamespace(
            data={integration.DOMAIN: {integration.DATA_STORAGE: Storage()}},
            bus=Bus(),
        )
        entry = types.SimpleNamespace(
            entry_id="entry-123",
            options={
                integration.CONF_WARNING_THRESHOLD: 30,
                integration.CONF_CRITICAL_THRESHOLD: 8,
                "unrelated_option": "ignored",
            },
        )

        asyncio.run(integration._async_options_updated(hass, entry))

        self.assertEqual([item[0] for item in order], ["write", "dispatcher", "bus"])
        self.assertEqual(
            order[0][1],
            {
                integration.CONF_WARNING_THRESHOLD: 30,
                integration.CONF_CRITICAL_THRESHOLD: 8,
            },
        )
        expected_payload = {"settings": full_settings}
        self.assertEqual(
            order[1],
            (
                "dispatcher",
                integration.signal_vacuum_water_updated(entry.entry_id),
                expected_payload,
            ),
        )
        self.assertEqual(
            order[2],
            ("bus", integration.EVENT_STATE_CHANGED, expected_payload),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
