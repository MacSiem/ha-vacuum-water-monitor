"""Regression tests for structured settings accepted over WebSocket.

The card is available to every authenticated Home Assistant user, so the
``set_settings`` command is the trust boundary for values later rendered by
the card.  These tests exercise the command rather than a particular helper so
the normalization implementation can remain small and private.
"""

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
    """Load websocket_api.py with the small HA surface it imports stubbed."""
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

    package_name = "vwm_ws_validation_test_pkg"
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


def _load_tick_module():
    """Load the real tick calculations with their HA imports stubbed."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    modules = {
        "homeassistant": ha,
        "homeassistant.core": core,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)

    package_name = "vwm_tick_validation_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PKG_DIR)]
    sys.modules[package_name] = package

    calculations = types.ModuleType(f"{package_name}.sensor_calculations")
    calculations.build_vacuum_devices = lambda *args, **kwargs: []
    sys.modules[calculations.__name__] = calculations

    storage = types.ModuleType(f"{package_name}.storage")
    storage.VacuumWaterStorage = object
    sys.modules[storage.__name__] = storage

    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.tick", PKG_DIR / "tick.py"
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
    """Load the real storage wrapper with an inspectable in-memory Store."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    ha_storage = types.ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        next_loaded = None

        def __init__(self, *args, **kwargs) -> None:
            self.persisted = deepcopy(type(self).next_loaded)
            self.saves = []

        async def async_load(self):
            return deepcopy(self.persisted)

        async def async_save(self, data) -> None:
            saved = deepcopy(data)
            self.persisted = saved
            self.saves.append(saved)

    ha_storage.Store = FakeStore
    modules = {
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": ha_storage,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)

    package_name = "vwm_storage_validation_test_pkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PKG_DIR)]
    sys.modules[package_name] = package

    const = types.ModuleType(f"{package_name}.const")
    const.DEFAULT_CRITICAL_THRESHOLD = 10
    const.DEFAULT_WARNING_THRESHOLD = 25
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
        return module, FakeStore
    finally:
        for name, old_module in previous.items():
            if old_module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


websocket_api = _load_websocket_module()
tick_calculations = _load_tick_module()
storage_module, FakeStore = _load_storage_module()

MAX_DEVICES = websocket_api._MAX_DEVICES
MAX_SESSION_DEVICES = websocket_api._MAX_DEVICES
MAX_MAINTENANCE_ITEMS = websocket_api._MAX_MAINTENANCE_ITEMS
MAX_SESSIONS_PER_DEVICE = websocket_api._MAX_SESSIONS_PER_DEVICE
MAX_CALIBRATIONS = websocket_api._MAX_CALIBRATIONS
MAX_CALIBRATION_MODES = websocket_api._MAX_CALIBRATION_MODES
MAX_PATCH_DEPTH = websocket_api._MAX_PATCH_DEPTH
MAX_PATCH_NODES = websocket_api._MAX_PATCH_NODES
MAX_PATCH_TEXT_BYTES = websocket_api._MAX_PATCH_TEXT_BYTES
MAX_PATCH_STRING_BYTES = websocket_api._MAX_PATCH_STRING_BYTES
MAX_STORED_SETTINGS_BYTES = storage_module.MAX_SETTINGS_BYTES


class _Connection:
    def __init__(self) -> None:
        self.results = []
        self.errors = []

    def send_result(self, msg_id, payload=None) -> None:
        self.results.append((msg_id, payload))

    def send_error(self, msg_id, code, message) -> None:
        self.errors.append((msg_id, code, message))


class _Storage:
    def __init__(self) -> None:
        self.patches = []

    async def async_set_settings(self, patch):
        stored = deepcopy(patch)
        self.patches.append(stored)
        return stored


class WebsocketSettingsValidationTest(unittest.TestCase):
    """Define the compatibility and safety contract for set_settings."""

    def _set_settings(self, patch):
        storage = _Storage()
        connection = _Connection()
        notifications = []
        websocket_api._notify_store_updated = (
            lambda _hass, payload: notifications.append(deepcopy(payload))
        )
        hass = types.SimpleNamespace(
            data={websocket_api.DOMAIN: {"storage": storage}}
        )
        original = deepcopy(patch)
        asyncio.run(
            websocket_api._ws_set_settings(
                hass, connection, {"id": 17, "patch": patch}
            )
        )
        self.assertEqual(patch, original, "normalization must not mutate caller data")
        return storage, connection, notifications

    def _assert_rejected_atomically(self, patch) -> None:
        storage, connection, notifications = self._set_settings(patch)
        self.assertEqual(storage.patches, [])
        self.assertEqual(connection.results, [])
        self.assertEqual(notifications, [])
        self.assertEqual(len(connection.errors), 1)
        self.assertEqual(connection.errors[0][0:2], (17, "invalid_payload"))
        self.assertTrue(connection.errors[0][2])

    def test_valid_legacy_shapes_and_safe_icons_are_preserved(self) -> None:
        """Emoji, mdi icons, old name-based keys, and future fields survive."""
        patch = {
            "maintenance_items": [
                {
                    "name": "Wash mop pads",
                    "icon": "🧽",
                    "intervalDays": 7,
                    "lastDone": 1_725_000_000_000,
                    "future_scalar": "preserve me",
                },
                {
                    "name": "Clean dock",
                    "icon": "mdi:robot-vacuum",
                    "intervalDays": 365,
                    "lastDone": 4_102_444_800_000,
                },
                {
                    "name": "New filter",
                    "icon": "🔍",
                    "intervalDays": 30,
                    "lastDone": None,
                },
                {
                    "name": "Filter < 20%",
                    "icon": "⚠️",
                    "intervalDays": 14,
                    "lastDone": None,
                },
            ],
            "user_devices": [
                {
                    "vacuum_entity": "vacuum.upstairs",
                    "name": "Upstairs < North",
                    "icon": "🤖",
                    "future_scalar": 3,
                }
            ],
            "configured_devices": [
                {
                    "vacuum_entity": "vacuum.downstairs",
                    "label": "Downstairs > Hall",
                    "icon": "mdi:robot-vacuum",
                    "water_total_ml": 3_000,
                }
            ],
            "sessions": {
                "vacuum.upstairs": [
                    {
                        "ts": 1_725_000_000_000,
                        "area": 31.5,
                        "water": 180,
                        "duration": "45m",
                        "future_scalar": True,
                    }
                ],
                # v5 originally keyed local history by the display name.  A
                # migration/import may therefore contain a non-entity key.
                "Kitchen Robot": [
                    {
                        "ts": 4_102_444_800_000,
                        "area": 1_000_000_000,
                        "water": 0,
                        "duration": "1h 5m",
                    }
                ],
            },
            "future_setting": {"nested": ["preserve", 1]},
        }

        storage, connection, notifications = self._set_settings(patch)

        self.assertEqual(storage.patches, [patch])
        self.assertEqual(connection.errors, [])
        self.assertEqual(connection.results, [(17, {"settings": patch})])
        self.assertEqual(notifications, [{"settings": patch}])

    def test_unsafe_or_non_string_rendered_fields_are_removed(self) -> None:
        """Bad rendered fields are dropped without discarding their records."""
        patch = {
            "maintenance_items": [
                {
                    "name": "Keep maintenance",
                    "icon": "<img src=x onerror=alert(1)>",
                    "intervalDays": 30,
                },
                {"name": "Also keep", "icon": {"html": "not text"}},
                {
                    "name": "Bad schedule values are ignored",
                    "icon": "🔧",
                    "intervalDays": "weekly",
                    "lastDone": {"when": "today"},
                },
                {
                    "name": "Out-of-range schedule values are ignored",
                    "intervalDays": 366,
                    "lastDone": 4_102_444_800_001,
                },
            ],
            "user_devices": [
                {
                    "vacuum_entity": "vacuum.a",
                    "icon": "</button><script>alert(1)</script>",
                    "water_total_ml": 250,
                }
            ],
            "configured_devices": [
                {"vacuum_entity": "vacuum.b", "icon": ["not", "text"]}
            ],
            "sessions": {
                "vacuum.a": [
                    {
                        "ts": 1_725_000_000_000,
                        "area": 20,
                        "duration": "<svg onload=alert(1)>",
                    },
                    {
                        "ts": False,
                        "duration": {"html": "not text"},
                        "area": "not-a-number",
                        "water": {"ml": 90},
                        "future_scalar": "still here",
                    },
                    {
                        "ts": 4_102_444_800_001,
                        "area": -0.1,
                        "water": 1_000_000_000.1,
                        "duration": "2h",
                    },
                ]
            },
        }

        storage, connection, _notifications = self._set_settings(patch)

        self.assertEqual(connection.errors, [])
        saved = storage.patches[0]
        self.assertEqual(
            saved["maintenance_items"],
            [
                {
                    "name": "Keep maintenance",
                    "intervalDays": 30,
                },
                {"name": "Also keep"},
                {"name": "Bad schedule values are ignored", "icon": "🔧"},
                {"name": "Out-of-range schedule values are ignored"},
            ],
        )
        self.assertEqual(
            saved["user_devices"],
            [
                {
                    "vacuum_entity": "vacuum.a",
                    "water_total_ml": 250,
                }
            ],
        )
        self.assertEqual(
            saved["configured_devices"],
            [{"vacuum_entity": "vacuum.b"}],
        )
        self.assertEqual(
            saved["sessions"],
            {
                "vacuum.a": [
                    {"ts": 1_725_000_000_000, "area": 20},
                    {"future_scalar": "still here"},
                    {"duration": "2h"},
                ]
            },
        )

    def test_structured_collections_are_capped_without_reordering(self) -> None:
        maintenance = [
            {"name": f"Task {index}", "icon": "🔧"}
            for index in range(MAX_MAINTENANCE_ITEMS + 7)
        ]
        user_devices = [
            {"vacuum_entity": f"vacuum.user_{index}", "icon": "🤖"}
            for index in range(MAX_DEVICES + 7)
        ]
        configured_devices = [
            {"vacuum_entity": f"vacuum.config_{index}"}
            for index in range(MAX_DEVICES + 7)
        ]
        # The card stores newest first.  The boundary should retain that order
        # and discard only the tail beyond its per-device history limit.
        sessions = [
            {"ts": 2_000_000_000_000 - index, "area": index}
            for index in range(MAX_SESSIONS_PER_DEVICE + 9)
        ]

        storage, connection, _notifications = self._set_settings(
            {
                "maintenance_items": maintenance,
                "user_devices": user_devices,
                "configured_devices": configured_devices,
                "sessions": {"vacuum.a": sessions},
            }
        )

        self.assertEqual(connection.errors, [])
        saved = storage.patches[0]
        self.assertEqual(
            saved["maintenance_items"], maintenance[:MAX_MAINTENANCE_ITEMS]
        )
        self.assertEqual(saved["user_devices"], user_devices[:MAX_DEVICES])
        self.assertEqual(
            saved["configured_devices"],
            configured_devices[:MAX_DEVICES],
        )
        self.assertEqual(
            saved["sessions"]["vacuum.a"],
            sessions[:MAX_SESSIONS_PER_DEVICE],
        )

    def test_session_devices_and_custom_calibration_are_capped_in_order(self) -> None:
        self.assertEqual(MAX_SESSION_DEVICES, 100)
        self.assertEqual(MAX_CALIBRATIONS, 100)
        self.assertEqual(MAX_CALIBRATION_MODES, 32)
        session_keys = [
            f"vacuum.session_{index:03d}"
            for index in range(MAX_SESSION_DEVICES + 7)
        ]
        sessions = {
            key: [{"ts": 2_000_000_000_000 - index, "area": index}]
            for index, key in enumerate(session_keys)
        }

        calibration_keys = [
            f"vacuum.calibration_{index:03d}"
            for index in range(MAX_CALIBRATIONS + 7)
        ]
        water_mode_names = ["low < eco"] + [
            f"water_{index:02d}" for index in range(MAX_CALIBRATION_MODES + 6)
        ]
        mop_mode_names = [
            f"mop_{index:02d}" for index in range(MAX_CALIBRATION_MODES + 7)
        ]
        water_modes = {
            name: index + 1 for index, name in enumerate(water_mode_names)
        }
        mop_modes = {
            name: index + 1 for index, name in enumerate(mop_mode_names)
        }
        calibrations = {
            key: {"tank_ml": 3_000 + index}
            for index, key in enumerate(calibration_keys)
        }
        calibrations[calibration_keys[0]].update(
            {
                "water_per_m2": water_modes,
                "mop_modes": mop_modes,
                "future_note": "preserve this scalar",
            }
        )

        storage, connection, _notifications = self._set_settings(
            {"sessions": sessions, "custom_calibration": calibrations}
        )

        self.assertEqual(connection.errors, [])
        saved = storage.patches[0]
        self.assertEqual(
            list(saved["sessions"]), session_keys[:MAX_SESSION_DEVICES]
        )
        self.assertEqual(
            list(saved["custom_calibration"]),
            calibration_keys[:MAX_CALIBRATIONS],
        )
        first_calibration = saved["custom_calibration"][calibration_keys[0]]
        self.assertEqual(
            list(first_calibration["water_per_m2"]),
            water_mode_names[:MAX_CALIBRATION_MODES],
        )
        self.assertEqual(
            list(first_calibration["mop_modes"]),
            mop_mode_names[:MAX_CALIBRATION_MODES],
        )
        self.assertEqual(
            first_calibration["future_note"], "preserve this scalar"
        )

    def test_device_collections_require_canonical_vacuum_entity_ids(self) -> None:
        valid_patch = {
            "user_devices": [
                {
                    "vacuum_entity": "vacuum.foo_bar",
                    "name": "Foo Bar",
                    "icon": "🤖",
                }
            ],
            "configured_devices": [
                {
                    "vacuum_entity": "vacuum.downstairs_2",
                    "water_total_ml": 3_000,
                }
            ],
        }

        storage, connection, notifications = self._set_settings(valid_patch)

        self.assertEqual(storage.patches, [valid_patch])
        self.assertEqual(connection.errors, [])
        self.assertEqual(connection.results, [(17, {"settings": valid_patch})])
        self.assertEqual(notifications, [{"settings": valid_patch}])

        invalid_cases = (
            (
                "quoted",
                {"user_devices": [{"vacuum_entity": '"vacuum.foo_bar"'}]},
            ),
            (
                "leading whitespace",
                {"configured_devices": [{"vacuum_entity": " vacuum.foo_bar"}]},
            ),
            (
                "embedded whitespace",
                {"user_devices": [{"vacuum_entity": "vacuum.foo bar"}]},
            ),
            (
                "wrong domain",
                {"configured_devices": [{"vacuum_entity": "sensor.foo_bar"}]},
            ),
            (
                "invalid object id",
                {"user_devices": [{"vacuum_entity": "vacuum.Foo-Bar"}]},
            ),
            ("missing", {"configured_devices": [{"name": "No entity"}]}),
            ("null", {"user_devices": [{"vacuum_entity": None}]}),
        )

        for label, patch in invalid_cases:
            with self.subTest(case=label):
                self._assert_rejected_atomically(patch)

    def test_device_numeric_fields_are_bounded_and_maps_preserve_order(self) -> None:
        raw_usage_modes = {
            "safe_low": 4,
            "markup_amount": "<b>6</b>",
            "non_finite": "Infinity",
            "zero": 0,
            "too_large": 1_000_001,
            **{f"mode_{index:02d}": index + 1 for index in range(35)},
        }
        expected_usage_modes = {
            key: value
            for key, value in list(raw_usage_modes.items())[:MAX_CALIBRATION_MODES]
            if key not in {
                "markup_amount",
                "non_finite",
                "zero",
                "too_large",
            }
        }
        patch = {
            "user_devices": [
                {
                    "vacuum_entity": "vacuum.numeric_min",
                    "water_total_ml": 0.000001,
                    "wash_volume_ml": 0,
                    "usage_ml_per_m2": {"low < eco": 0.000001, "standard": 6},
                    "intensity_factor": {"low": 0.8, "maximum": 1_000},
                },
                {
                    "vacuum_entity": "vacuum.numeric_hostile",
                    "water_total_ml": "<script>3000</script>",
                    "wash_volume_ml": "NaN",
                    "usage_ml_per_m2": {"bad": "Infinity"},
                    "intensity_factor": {"bad": -1},
                    "future_scalar": "keep the device",
                },
            ],
            "configured_devices": [
                {
                    "vacuum_entity": "vacuum.numeric_filtered_map",
                    "water_total_ml": 1_000_000_001,
                    "wash_volume_ml": -1,
                    "usage_ml_per_m2": raw_usage_modes,
                    "intensity_factor": {
                        "medium": 1,
                        "markup_amount": "<i>1</i>",
                        "non_finite": "NaN",
                        "zero": 0,
                        "too_large": 1_001,
                    },
                },
                {
                    "vacuum_entity": "vacuum.numeric_max",
                    "water_total_ml": 1_000_000_000,
                    "wash_volume_ml": 1_000_000_000,
                    "usage_ml_per_m2": {"maximum": 1_000_000},
                    "intensity_factor": {"maximum": 1_000},
                },
            ],
        }

        storage, connection, notifications = self._set_settings(patch)

        self.assertEqual(connection.errors, [])
        expected = {
            "user_devices": [
                patch["user_devices"][0],
                {
                    "vacuum_entity": "vacuum.numeric_hostile",
                    "future_scalar": "keep the device",
                },
            ],
            "configured_devices": [
                {
                    "vacuum_entity": "vacuum.numeric_filtered_map",
                    "usage_ml_per_m2": expected_usage_modes,
                    "intensity_factor": {"medium": 1},
                },
                patch["configured_devices"][1],
            ],
        }
        self.assertEqual(storage.patches, [expected])
        self.assertEqual(connection.results, [(17, {"settings": expected})])
        self.assertEqual(notifications, [{"settings": expected}])

    def test_normalized_device_maps_feed_real_tick_mapping_lookup(self) -> None:
        patch = {
            "configured_devices": [
                {
                    "vacuum_entity": "vacuum.round_trip",
                    "usage_ml_per_m2": {
                        "low": 4,
                        "standard": 6.5,
                        "hostile": "Infinity",
                    },
                    "intensity_factor": {
                        "medium": 1.25,
                        "high": 1.5,
                        "invalid": 0,
                    },
                }
            ]
        }

        storage, connection, _notifications = self._set_settings(patch)

        self.assertEqual(connection.errors, [])
        stored_device = storage.patches[0]["configured_devices"][0]
        self.assertEqual(
            stored_device["usage_ml_per_m2"], {"low": 4, "standard": 6.5}
        )
        self.assertEqual(
            stored_device["intensity_factor"], {"medium": 1.25, "high": 1.5}
        )
        self.assertEqual(
            tick_calculations._mapping_number(
                stored_device["usage_ml_per_m2"], "standard", 99
            ),
            6.5,
        )
        self.assertEqual(
            tick_calculations._mapping_number(
                stored_device["intensity_factor"], "medium", 99
            ),
            1.25,
        )
        self.assertEqual(
            tick_calculations._mapping_number(
                stored_device["usage_ml_per_m2"], "missing", 99
            ),
            99,
        )

    def test_cumulative_settings_budget_rejects_second_patch_atomically(self) -> None:
        self.assertEqual(MAX_STORED_SETTINGS_BYTES, 512_000)
        chunk = "x" * 63_990
        first_patch = {f"a{index}": chunk for index in range(4)}
        second_patch = {f"b{index}": chunk for index in range(4)}

        # Both patches independently satisfy the public WebSocket tree budget.
        websocket_api._validate_patch_budget(first_patch)
        websocket_api._validate_patch_budget(second_patch)
        first_candidate = {
            **storage_module._default_state()["settings"],
            **first_patch,
        }
        merged_candidate = {**first_candidate, **second_patch}
        encoded = lambda value: len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        self.assertLess(encoded(first_candidate), MAX_STORED_SETTINGS_BYTES)
        self.assertGreater(encoded(merged_candidate), MAX_STORED_SETTINGS_BYTES)

        async def scenario():
            FakeStore.next_loaded = None
            storage = storage_module.VacuumWaterStorage(None)
            await storage.async_load()
            first_settings = await storage.async_set_settings(first_patch)
            persisted_after_first = deepcopy(storage._store.persisted)
            in_memory_after_first = deepcopy(storage._data)

            with self.assertRaises(ValueError):
                await storage.async_set_settings(second_patch)

            return (
                storage,
                first_settings,
                persisted_after_first,
                in_memory_after_first,
                await storage.async_get_settings(),
            )

        (
            storage,
            first_settings,
            persisted_after_first,
            in_memory_after_first,
            final_settings,
        ) = asyncio.run(scenario())

        self.assertEqual(final_settings, first_settings)
        self.assertEqual(storage._data, in_memory_after_first)
        self.assertEqual(storage._store.persisted, persisted_after_first)
        self.assertEqual(len(storage._store.saves), 1)
        for key in second_patch:
            self.assertNotIn(key, final_settings)

    def test_legacy_oversized_settings_allow_size_reducing_write(self) -> None:
        legacy_settings = {
            f"legacy_{index:02d}": "x" * 60_000 for index in range(10)
        }
        reducing_patch = {"legacy_00": "x" * 10_000}
        websocket_api._validate_patch_budget(reducing_patch)

        async def scenario():
            FakeStore.next_loaded = {"settings": legacy_settings}
            storage = storage_module.VacuumWaterStorage(None)
            before = await storage.async_get_settings()
            after = await storage.async_set_settings(reducing_patch)
            return storage, before, after

        storage, before, after = asyncio.run(scenario())
        encoded = lambda value: len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )

        self.assertGreater(encoded(before), MAX_STORED_SETTINGS_BYTES)
        self.assertGreater(encoded(after), MAX_STORED_SETTINGS_BYTES)
        self.assertLess(encoded(after), encoded(before))
        self.assertEqual(after["legacy_00"], reducing_patch["legacy_00"])
        self.assertEqual(storage._data["settings"], after)
        self.assertEqual(storage._store.persisted["settings"], after)
        self.assertEqual(len(storage._store.saves), 1)

    def test_legacy_oversized_settings_allow_equal_byte_size_write(self) -> None:
        legacy_settings = {
            "warning_threshold": 20,
            **{f"legacy_{index:02d}": "x" * 60_000 for index in range(10)},
        }
        same_width_patch = {"warning_threshold": 30}
        websocket_api._validate_patch_budget(same_width_patch)

        async def scenario():
            FakeStore.next_loaded = {"settings": legacy_settings}
            storage = storage_module.VacuumWaterStorage(None)
            before = await storage.async_get_settings()
            after = await storage.async_set_settings(same_width_patch)
            return storage, before, after

        storage, before, after = asyncio.run(scenario())
        before_size = storage_module._serialized_bytes(before)
        after_size = storage_module._serialized_bytes(after)

        self.assertGreater(before_size, MAX_STORED_SETTINGS_BYTES)
        self.assertEqual(after_size, before_size)
        self.assertEqual(before["warning_threshold"], 20)
        self.assertEqual(after["warning_threshold"], 30)
        self.assertEqual(after["legacy_09"], legacy_settings["legacy_09"])
        self.assertEqual(storage._data["settings"], after)
        self.assertEqual(storage._store.persisted["settings"], after)
        self.assertEqual(len(storage._store.saves), 1)

    def test_unknown_nested_payload_budget_is_rejected_atomically(self) -> None:
        too_deep = "leaf"
        # Patch root is depth zero and the unknown setting value starts at one.
        # This makes the leaf exactly one level beyond the accepted depth.
        for _index in range(MAX_PATCH_DEPTH):
            too_deep = [too_deep]

        valid_chunk = "x" * (MAX_PATCH_STRING_BYTES - 1)
        oversized_patches = (
            ("depth", {"future_setting": too_deep}),
            (
                "nodes",
                {"future_setting": [None] * MAX_PATCH_NODES},
            ),
            (
                "aggregate text",
                {"future_setting": [valid_chunk] * 4},
            ),
            (
                "single string",
                {"future_setting": "x" * (MAX_PATCH_STRING_BYTES + 1)},
            ),
            (
                "single key",
                {"future_setting": {"k" * (MAX_PATCH_STRING_BYTES + 1): 1}},
            ),
        )

        self.assertGreater(4 * len(valid_chunk.encode("utf-8")), MAX_PATCH_TEXT_BYTES)
        for label, patch in oversized_patches:
            with self.subTest(limit=label):
                self._assert_rejected_atomically(patch)

    def test_malformed_structured_values_are_rejected_atomically(self) -> None:
        malformed_patches = (
            {"maintenance_items": "not-a-list", "warning_threshold": 12},
            {"maintenance_items": [{"name": "valid"}, "bad-item"]},
            {"maintenance_items": [{"icon": "🔧", "intervalDays": 7}]},
            {"user_devices": {"vacuum.a": {}}, "warning_threshold": 12},
            {"configured_devices": [None], "warning_threshold": 12},
            {"sessions": [], "warning_threshold": 12},
            {"sessions": {"vacuum.a": "not-a-list"}},
            {"sessions": {"vacuum.a": [{"ts": 1}, "bad-item"]}},
            {"custom_calibration": []},
            {"custom_calibration": {"vacuum.a": []}},
            {"custom_calibration": {"vacuum.a": {"water_per_m2": []}}},
            {"custom_calibration": {"vacuum.a": {"mop_modes": "high"}}},
        )

        for patch in malformed_patches:
            with self.subTest(patch=patch):
                self._assert_rejected_atomically(patch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
