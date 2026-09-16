"""Pure registry-fixture tests for same-device vacuum signal discovery."""

from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path
import sys
import types

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _load_discovery():
    profile_path = PKG_DIR / "profiles.py"
    discovery_path = PKG_DIR / "discovery.py"
    if not profile_path.is_file() or not discovery_path.is_file():
        return None
    package = types.ModuleType("vwmdiscovery")
    package.__path__ = [str(PKG_DIR)]
    sys.modules["vwmdiscovery"] = package
    for name, path in (("profiles", profile_path), ("discovery", discovery_path)):
        spec = importlib.util.spec_from_file_location(f"vwmdiscovery.{name}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"vwmdiscovery.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["vwmdiscovery.discovery"]


class VacuumDiscoveryTests(unittest.TestCase):
    """Registry-shaped inputs exercise the real descriptor boundary."""

    def test_setting_contracts_bind_only_enabled_same_device_entities(self):
        discovery = _load_discovery()
        for adapter, key, role, domain in (("ecovacs", "clean_count", "passes_entity", "number"),
                                           ("roborock", "cleaning_route", "route_entity", "select")):
            with self.subTest(adapter=adapter):
                entity = {"entity_id": f"{domain}.option", "platform": adapter,
                          "device_id": "one", "translation_key": key}
                def resolve(record):
                    return discovery._signals_for_device({'one'}, adapter, [record], {})[0]
                self.assertEqual(resolve(entity).get(role), f"{domain}.option")
                self.assertNotIn(role, resolve({**entity, 'device_id': 'other'}))
                self.assertNotIn(role, resolve({**entity, 'disabled_by': 'integration'}))
                self.assertNotIn(role, resolve({**entity, 'entity_id': 'button.option'}))

    def test_registry_firmware_is_retained_for_upgrade_applicability(self):
        discovery = _load_discovery()
        result = discovery.discover_descriptors(
            [{"entity_id":"vacuum.test","platform":"roborock","device_id":"a"}],
            [{"id":"a","manufacturer":"Roborock","sw_version":"1.2.3"}], {})[0]
        self.assertEqual(result.get("observed_firmware"), "1.2.3")

    def test_roborock_links_only_same_device_raw_status_and_area(self) -> None:
        # Moving the sibling records to another device_id must make this fail.
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.kitchen", "platform": "roborock", "unique_id": "vac-1", "device_id": "dev-1"},
            {"entity_id": "sensor.kitchen_status", "platform": "roborock", "unique_id": "status-1", "device_id": "dev-1", "translation_key": "status"},
            {"entity_id": "sensor.kitchen_area", "platform": "roborock", "unique_id": "area-1", "device_id": "dev-1", "translation_key": "cleaning_area"},
            {"entity_id": "select.kitchen_mop_mode", "platform": "roborock", "unique_id": "mode-1", "device_id": "dev-1", "translation_key": "mop_mode"},
            {"entity_id": "select.kitchen_mop_intensity", "platform": "roborock", "unique_id": "intensity-1", "device_id": "dev-1", "translation_key": "mop_intensity"},
            {"entity_id": "binary_sensor.kitchen_water_shortage", "platform": "roborock", "unique_id": "shortage-1", "device_id": "dev-1", "translation_key": "water_shortage"},
            {"entity_id": "binary_sensor.kitchen_mop_attached", "platform": "roborock", "unique_id": "mop-1", "device_id": "dev-1", "translation_key": "mop_attached"},
            {"entity_id": "sensor.living_status", "platform": "roborock", "unique_id": "status-2", "device_id": "dev-2", "translation_key": "status"},
        ]
        devices = [
            {"id": "dev-1", "manufacturer": "Roborock", "model": "Qrevo 5AE", "model_id": "a170"},
            {"id": "dev-2", "manufacturer": "Roborock", "model": "Qrevo Curv", "model_id": "a245"},
        ]
        states = {
            "vacuum.kitchen": {"state": "docked", "attributes": {"friendly_name": "Kitchen", "battery_level": 82}},
            "sensor.kitchen_status": {"state": "washing_the_mop", "attributes": {}},
            "sensor.kitchen_area": {"state": "14.2", "attributes": {}},
            "select.kitchen_mop_mode": {"state": "standard", "attributes": {}},
            "select.kitchen_mop_intensity": {"state": "medium", "attributes": {}},
            "binary_sensor.kitchen_water_shortage": {"state": "off", "attributes": {}},
            "binary_sensor.kitchen_mop_attached": {"state": "on", "attributes": {}},
            "sensor.living_status": {"state": "cleaning", "attributes": {}},
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertEqual(descriptor["source_id"], "device:dev-1")
        self.assertEqual(descriptor["profile_key"], "roborock_qrevo_5ae")
        self.assertEqual(
            descriptor["signals"],
            {
                "status_sensor": "sensor.kitchen_status",
                "area_sensor": "sensor.kitchen_area",
                "mop_mode_entity": "select.kitchen_mop_mode",
                "mop_intensity_entity": "select.kitchen_mop_intensity",
                "water_shortage_sensor": "binary_sensor.kitchen_water_shortage",
                "mop_attached_sensor": "binary_sensor.kitchen_mop_attached",
            },
        )
        self.assertEqual(states[descriptor["signals"]["status_sensor"]]["state"], "washing_the_mop")

    def test_disabled_and_ambiguous_siblings_are_omitted(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.kitchen", "platform": "roborock", "unique_id": "vac-1", "device_id": "dev-1"},
            {"entity_id": "sensor.disabled_status", "platform": "roborock", "unique_id": "status-1", "device_id": "dev-1", "translation_key": "status", "disabled_by": "user"},
            {"entity_id": "sensor.area_one", "platform": "roborock", "unique_id": "area-1", "device_id": "dev-1", "translation_key": "cleaning_area"},
            {"entity_id": "sensor.area_two", "platform": "roborock", "unique_id": "area-2", "device_id": "dev-1", "translation_key": "cleaning_area"},
        ]
        devices = [{"id": "dev-1", "manufacturer": "Roborock", "model_id": "a170"}]
        states = {
            "vacuum.kitchen": {"state": "docked", "attributes": {}},
            "sensor.disabled_status": {"state": "washing_the_mop", "attributes": {}},
            "sensor.area_one": {"state": "3", "attributes": {}},
            "sensor.area_two": {"state": "4", "attributes": {}},
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertEqual(descriptor["signals"], {})

    def test_entity_name_substrings_do_not_invent_water_capabilities(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptor = discovery.discover_descriptors(
            [
                {"entity_id": "vacuum.robot", "platform": "vendor_cloud", "unique_id": "vac", "device_id": "robot-dev"},
                {"entity_id": "sensor.robot_water_tank_level", "platform": "vendor_cloud", "unique_id": "level", "device_id": "robot-dev"},
                {"entity_id": "sensor.robot_clean_water_emptyish", "platform": "vendor_cloud", "unique_id": "emptyish", "device_id": "robot-dev"},
            ],
            [{"id": "robot-dev", "manufacturer": "Example", "model": "Unknown"}],
            {
                "vacuum.robot": {"state": "cleaning", "attributes": {}},
                "sensor.robot_water_tank_level": {"state": "80", "attributes": {}},
                "sensor.robot_clean_water_emptyish": {"state": "off", "attributes": {}},
            },
        )[0]

        self.assertEqual(descriptor["signals"], {})

    def test_tapo_matter_descriptor_uses_operational_and_clean_mode_signals(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptors = discovery.discover_descriptors(
            [
                {"entity_id": "vacuum.opaque", "platform": "matter", "unique_id": "matter-vac", "device_id": "tapo-device"},
                {"entity_id": "sensor.opaque_operational_state", "platform": "matter", "unique_id": "matter-state", "device_id": "tapo-device", "translation_key": "operational_state"},
                {"entity_id": "select.opaque_clean_mode", "platform": "matter", "unique_id": "matter-mode", "device_id": "tapo-device", "translation_key": "clean_mode"},
            ],
            [{"id": "tapo-device", "manufacturer": "TP-Link", "model": "RV50 Pro Omni (1797)", "model_id": "1797"}],
            {
                "vacuum.opaque": {"state": "docked", "attributes": {}},
                "sensor.opaque_operational_state": {"state": "docked", "attributes": {}},
                "select.opaque_clean_mode": {"state": "Auto, Vacuum and Mop", "attributes": {}},
            },
        )

        descriptor = descriptors[0]
        self.assertEqual(descriptor["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(descriptor["tracked_capacity_ml"], 5000)
        self.assertEqual(descriptor["capability"], "automatic_estimate")
        self.assertEqual(
            descriptor["signals"],
            {
                "status_sensor": "sensor.opaque_operational_state",
                "cleaning_mode_entity": "select.opaque_clean_mode",
            },
        )

    def test_registry_identifier_pair_resolves_without_model_or_entity_alias(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None

        descriptor = discovery.discover_descriptors(
            [{"entity_id": "vacuum.opaque", "platform": "roborock", "unique_id": "vac-1", "device_id": "dev-1"}],
            [{"id": "dev-1", "manufacturer": "Roborock", "model": "unhelpful", "identifiers": {("roborock", "a170")}}],
            {"vacuum.opaque": {"state": "docked", "attributes": {}}},
        )[0]

        self.assertEqual(descriptor["profile_key"], "roborock_qrevo_5ae")
        self.assertEqual(descriptor["profile_source"], "catalog_identifier")

    def test_roborock_vendor_translation_key_is_ranked_for_its_platform(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.kitchen", "platform": "roborock", "unique_id": "vac-1", "device_id": "dev-1"},
            {"entity_id": "sensor.kitchen_a01_status", "platform": "roborock", "unique_id": "status-1", "device_id": "dev-1", "translation_key": "a01_status"},
            {"entity_id": "sensor.kitchen_clean_area", "platform": "roborock", "unique_id": "area-1", "device_id": "dev-1", "translation_key": "clean_area"},
            {"entity_id": "select.kitchen_mop_mode", "platform": "roborock", "unique_id": "mode-1", "device_id": "dev-1", "translation_key": "mop_mode"},
            {"entity_id": "select.kitchen_water_box_mode", "platform": "roborock", "unique_id": "intensity-1", "device_id": "dev-1", "translation_key": "water_box_mode"},
            {"entity_id": "sensor.foreign_status", "platform": "other", "unique_id": "status-2", "device_id": "dev-1", "translation_key": "status"},
        ]
        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "dev-1", "manufacturer": "Roborock", "model_id": "a170"}],
            {
                "vacuum.kitchen": {"state": "docked", "attributes": {}},
                "sensor.kitchen_a01_status": {"state": "washing_the_mop", "attributes": {}},
                "sensor.kitchen_clean_area": {"state": "12.3", "attributes": {}},
                "select.kitchen_mop_mode": {"state": "standard", "attributes": {}},
                "select.kitchen_water_box_mode": {"state": "medium", "attributes": {}},
                "sensor.foreign_status": {"state": "cleaning", "attributes": {}},
            },
        )[0]

        self.assertEqual(
            descriptor["signals"],
            {
                "status_sensor": "sensor.kitchen_a01_status",
                "area_sensor": "sensor.kitchen_clean_area",
                "mop_mode_entity": "select.kitchen_mop_mode",
                "mop_intensity_entity": "select.kitchen_water_box_mode",
            },
        )

    def test_xiaomi_miio_uses_official_conditional_water_and_run_signals(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.xiaomi", "platform": "xiaomi_miio", "unique_id": "vac", "device_id": "xiaomi-dev"},
            {"entity_id": "sensor.xiaomi_area", "platform": "xiaomi_miio", "unique_id": "area", "device_id": "xiaomi-dev", "translation_key": "clean_area"},
            {"entity_id": "sensor.xiaomi_time", "platform": "xiaomi_miio", "unique_id": "time", "device_id": "xiaomi-dev", "translation_key": "clean_time"},
            {"entity_id": "sensor.xiaomi_water_level", "platform": "xiaomi_miio", "unique_id": "water", "device_id": "xiaomi-dev", "translation_key": "water_level"},
            {"entity_id": "binary_sensor.xiaomi_mop", "platform": "xiaomi_miio", "unique_id": "mop", "device_id": "xiaomi-dev", "translation_key": "is_water_box_carriage_attached"},
            {"entity_id": "binary_sensor.xiaomi_box", "platform": "xiaomi_miio", "unique_id": "box", "device_id": "xiaomi-dev", "translation_key": "is_water_box_attached"},
            {"entity_id": "binary_sensor.xiaomi_shortage", "platform": "xiaomi_miio", "unique_id": "shortage", "device_id": "xiaomi-dev", "translation_key": "is_water_shortage"},
        ]
        states = {
            "vacuum.xiaomi": {"state": "cleaning", "attributes": {}},
            "sensor.xiaomi_area": {"state": "8.4", "attributes": {"unit_of_measurement": "m²"}},
            "sensor.xiaomi_time": {"state": "720", "attributes": {"unit_of_measurement": "s"}},
            "sensor.xiaomi_water_level": {"state": "medium", "attributes": {}},
            "binary_sensor.xiaomi_mop": {"state": "on", "attributes": {}},
            "binary_sensor.xiaomi_box": {"state": "on", "attributes": {}},
            "binary_sensor.xiaomi_shortage": {"state": "off", "attributes": {}},
        }

        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "xiaomi-dev", "manufacturer": "Xiaomi", "model": "Mi Robot Vacuum"}],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "xiaomi_miio")
        self.assertEqual(
            descriptor["signals"],
            {
                "area_sensor": "sensor.xiaomi_area",
                "duration_sensor": "sensor.xiaomi_time",
                "mop_attached_sensor": "binary_sensor.xiaomi_mop",
                "water_box_attached_sensor": "binary_sensor.xiaomi_box",
                "water_shortage_sensor": "binary_sensor.xiaomi_shortage",
            },
        )
        self.assertNotIn("sensor.xiaomi_water_level", descriptor["signals"].values())

    def test_ecovacs_uses_area_time_water_mode_and_station_machine_keys(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.deebot", "platform": "ecovacs", "unique_id": "vac", "device_id": "ecovacs-dev"},
            {"entity_id": "sensor.deebot_area", "platform": "ecovacs", "unique_id": "area", "device_id": "ecovacs-dev", "translation_key": "stats_area"},
            {"entity_id": "sensor.deebot_time", "platform": "ecovacs", "unique_id": "time", "device_id": "ecovacs-dev", "translation_key": "stats_time"},
            {"entity_id": "select.deebot_water", "platform": "ecovacs", "unique_id": "water", "device_id": "ecovacs-dev", "translation_key": "water_amount"},
            {"entity_id": "select.deebot_mode", "platform": "ecovacs", "unique_id": "mode", "device_id": "ecovacs-dev", "translation_key": "work_mode"},
            {"entity_id": "binary_sensor.deebot_mop", "platform": "ecovacs", "unique_id": "mop", "device_id": "ecovacs-dev", "translation_key": "water_mop_attached"},
            {"entity_id": "sensor.deebot_station", "platform": "ecovacs", "unique_id": "station", "device_id": "ecovacs-dev", "translation_key": "station_state"},
            {"entity_id": "sensor.deebot_error", "platform": "ecovacs", "unique_id": "error", "device_id": "ecovacs-dev", "translation_key": "error"},
        ]
        states = {record["entity_id"]: {"state": "idle", "attributes": {}} for record in entities}

        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "ecovacs-dev", "manufacturer": "Ecovacs", "model": "Deebot"}],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "ecovacs")
        self.assertEqual(
            descriptor["signals"],
            {
                "area_sensor": "sensor.deebot_area",
                "duration_sensor": "sensor.deebot_time",
                "mop_intensity_entity": "select.deebot_water",
                "cleaning_mode_entity": "select.deebot_mode",
                "mop_attached_sensor": "binary_sensor.deebot_mop",
                "dock_status_sensor": "sensor.deebot_station",
                "dock_error_sensor": "sensor.deebot_error",
            },
        )

    def test_roomba_exposes_documented_vacuum_attributes_but_keeps_tank_semantics_unconfirmed(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptor = discovery.discover_descriptors(
            [
                {"entity_id": "vacuum.braava", "platform": "roomba", "unique_id": "vac", "device_id": "roomba-dev"},
                {"entity_id": "sensor.braava_tank", "platform": "roomba", "unique_id": "tank", "device_id": "roomba-dev", "translation_key": "tank_level"},
                {"entity_id": "sensor.braava_dock_tank", "platform": "roomba", "unique_id": "dock-tank", "device_id": "roomba-dev", "translation_key": "dock_tank_level"},
            ],
            [{"id": "roomba-dev", "manufacturer": "iRobot", "model": "Braava"}],
            {
                "vacuum.braava": {"state": "cleaning", "attributes": {"cleaned_area": 12, "cleaning_time": 20, "tank_present": True, "fan_speed": "Standard-2"}},
                "sensor.braava_tank": {"state": "80", "attributes": {"unit_of_measurement": "%"}},
                "sensor.braava_dock_tank": {"state": "50", "attributes": {"unit_of_measurement": "%"}},
            },
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "roomba")
        self.assertEqual(descriptor["area_attribute"], "cleaned_area")
        self.assertEqual(descriptor["duration_attribute"], "cleaning_time")
        self.assertEqual(descriptor["duration_attribute_unit"], "min")
        self.assertEqual(descriptor["mop_intensity_attribute"], "fan_speed")
        self.assertEqual(descriptor["water_box_attached_attribute"], "tank_present")
        self.assertFalse(descriptor["tank_semantics_confirmed"])
        self.assertEqual(descriptor["signals"]["tank_level_sensor"], "sensor.braava_tank")
        self.assertEqual(descriptor["signals"]["dock_tank_level_sensor"], "sensor.braava_dock_tank")

    def test_smartthings_uses_water_spray_and_cleaning_type_without_inventing_tank_telemetry(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.jetbot", "platform": "smartthings", "unique_id": "vac", "device_id": "jetbot-dev"},
            {"entity_id": "select.jetbot_water", "platform": "smartthings", "unique_id": "water", "device_id": "jetbot-dev", "translation_key": "robot_cleaner_water_spray_level"},
            {"entity_id": "select.jetbot_type", "platform": "smartthings", "unique_id": "type", "device_id": "jetbot-dev", "translation_key": "robot_cleaner_cleaning_type"},
        ]
        states = {record["entity_id"]: {"state": "cleaning", "attributes": {}} for record in entities}

        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "jetbot-dev", "manufacturer": "Samsung", "model": "Jet Bot"}],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "smartthings")
        self.assertEqual(
            descriptor["signals"],
            {
                "mop_intensity_entity": "select.jetbot_water",
                "cleaning_mode_entity": "select.jetbot_type",
            },
        )

    def test_uncontracted_platform_does_not_invent_robot_water_signals(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.robot", "platform": "home_connect", "unique_id": "robot", "device_id": "robot-dev"},
            {"entity_id": "select.robot_mode", "platform": "home_connect", "unique_id": "mode", "device_id": "robot-dev", "translation_key": "cleaning_mode"},
            {"entity_id": "binary_sensor.coffee_water", "platform": "home_connect", "unique_id": "coffee-water", "device_id": "coffee-dev", "translation_key": "water_tank_empty"},
        ]
        states = {
            "vacuum.robot": {"state": "cleaning", "attributes": {}},
            "select.robot_mode": {"state": "vacuum_and_mop", "attributes": {}},
            "binary_sensor.coffee_water": {"state": "on", "attributes": {}},
        }

        descriptor = discovery.discover_descriptors(
            entities,
            [
                {"id": "robot-dev", "manufacturer": "Bosch", "model": "Cleaning Robot"},
                {"id": "coffee-dev", "manufacturer": "Bosch", "model": "Coffee Maker"},
            ],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "home_connect")
        # HA Core's Home Connect integration does not expose a vacuum platform.
        # A synthetic/third-party vacuum using that platform must fail closed,
        # and a coffee maker's similarly named water state must never leak in.
        self.assertEqual(descriptor["signals"], {})

    def test_dreame_custom_adapter_uses_documented_machine_keys(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.dreame", "platform": "dreame_vacuum", "unique_id": "vac", "device_id": "dreame-dev"},
            {"entity_id": "sensor.dreame_status", "platform": "dreame_vacuum", "unique_id": "status", "device_id": "dreame-dev", "translation_key": "status"},
            {"entity_id": "sensor.dreame_state", "platform": "dreame_vacuum", "unique_id": "state", "device_id": "dreame-dev", "translation_key": "state"},
            {"entity_id": "sensor.dreame_area", "platform": "dreame_vacuum", "unique_id": "area", "device_id": "dreame-dev", "translation_key": "cleaned_area"},
            {"entity_id": "sensor.dreame_time", "platform": "dreame_vacuum", "unique_id": "time", "device_id": "dreame-dev", "translation_key": "cleaning_time"},
            {"entity_id": "select.dreame_water", "platform": "dreame_vacuum", "unique_id": "water", "device_id": "dreame-dev", "translation_key": "water_volume"},
            {"entity_id": "select.dreame_mode", "platform": "dreame_vacuum", "unique_id": "mode", "device_id": "dreame-dev", "translation_key": "cleaning_mode"},
            {"entity_id": "sensor.dreame_tank", "platform": "dreame_vacuum", "unique_id": "tank", "device_id": "dreame-dev", "translation_key": "water_tank"},
            {"entity_id": "sensor.dreame_base", "platform": "dreame_vacuum", "unique_id": "base", "device_id": "dreame-dev", "translation_key": "self_wash_base_status"},
            {"entity_id": "sensor.dreame_error", "platform": "dreame_vacuum", "unique_id": "error", "device_id": "dreame-dev", "translation_key": "error"},
        ]
        states = {record["entity_id"]: {"state": "ok", "attributes": {}} for record in entities}
        states["sensor.dreame_state"]["state"] = "washing"
        states["sensor.dreame_area"]["state"] = "12.5"
        states["sensor.dreame_time"]["state"] = "24"
        states["select.dreame_water"]["state"] = "unavailable"

        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "dreame-dev", "manufacturer": "Dreame", "model": "L20 Ultra"}],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "dreame_vacuum")
        self.assertEqual(descriptor["signals"]["status_sensor"], "sensor.dreame_state")
        self.assertEqual(descriptor["signals"]["area_sensor"], "sensor.dreame_area")
        self.assertEqual(descriptor["signals"]["duration_sensor"], "sensor.dreame_time")
        self.assertEqual(descriptor["signals"]["mop_intensity_entity"], "select.dreame_water")
        self.assertEqual(descriptor["signals"]["cleaning_mode_entity"], "select.dreame_mode")
        self.assertEqual(descriptor["signals"]["water_box_attached_sensor"], "sensor.dreame_tank")
        self.assertEqual(descriptor["signals"]["dock_status_sensor"], "sensor.dreame_base")
        self.assertEqual(descriptor["signals"]["dock_error_sensor"], "sensor.dreame_error")
        self.assertTrue(descriptor["mop_evidence_required"])

    def test_tplink_exposes_run_statistics_but_not_unpublished_mop_features(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptor = discovery.discover_descriptors(
            [
                {"entity_id": "vacuum.tapo", "platform": "tplink", "unique_id": "vac", "device_id": "tapo-dev"},
                {"entity_id": "sensor.tapo_area", "platform": "tplink", "unique_id": "area", "device_id": "tapo-dev", "translation_key": "clean_area"},
                {"entity_id": "sensor.tapo_time", "platform": "tplink", "unique_id": "time", "device_id": "tapo-dev", "translation_key": "clean_time"},
                # python-kasa implements these features, but current HA Core
                # does not publish them. A fabricated entity must not bind.
                {"entity_id": "select.tapo_water", "platform": "tplink", "unique_id": "water", "device_id": "tapo-dev", "translation_key": "mop_waterlevel"},
            ],
            [{"id": "tapo-dev", "manufacturer": "TP-Link", "model": "RV50 Pro Omni"}],
            {
                "vacuum.tapo": {"state": "cleaning", "attributes": {}},
                "sensor.tapo_area": {"state": "12", "attributes": {"unit_of_measurement": "m²"}},
                "sensor.tapo_time": {"state": "600", "attributes": {"unit_of_measurement": "s"}},
                "select.tapo_water": {"state": "medium", "attributes": {}},
            },
        )[0]

        self.assertEqual(
            descriptor["signals"],
            {
                "area_sensor": "sensor.tapo_area",
                "duration_sensor": "sensor.tapo_time",
            },
        )
        self.assertTrue(descriptor["mop_evidence_required"])

    def test_valetudo_mqtt_adapter_maps_retained_machine_signals(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.local_robot", "platform": "mqtt", "unique_id": "valetudo-vac", "device_id": "valetudo-dev"},
            {"entity_id": "sensor.local_robot_current_statistics_area", "platform": "mqtt", "unique_id": "area", "device_id": "valetudo-dev", "original_name": "Current Statistics Area"},
            {"entity_id": "sensor.local_robot_current_statistics_time", "platform": "mqtt", "unique_id": "time", "device_id": "valetudo-dev", "original_name": "Current Statistics Time"},
            {"entity_id": "select.local_robot_water", "platform": "mqtt", "unique_id": "water", "device_id": "valetudo-dev", "original_name": "Water"},
            {"entity_id": "binary_sensor.local_robot_mop", "platform": "mqtt", "unique_id": "mop", "device_id": "valetudo-dev", "original_name": "Mop"},
            {"entity_id": "sensor.local_robot_water_tank_clean", "platform": "mqtt", "unique_id": "fresh", "device_id": "valetudo-dev", "original_name": "Freshwater"},
            {"entity_id": "sensor.local_robot_water_tank_dirty", "platform": "mqtt", "unique_id": "waste", "device_id": "valetudo-dev", "original_name": "Wastewater"},
        ]
        states = {record["entity_id"]: {"state": "ok", "attributes": {}} for record in entities}

        descriptor = discovery.discover_descriptors(
            entities,
            [{"id": "valetudo-dev", "manufacturer": "Valetudo", "model": "local"}],
            states,
        )[0]

        self.assertEqual(descriptor["integration_adapter"], "valetudo")
        self.assertEqual(descriptor["signals"]["area_sensor"], "sensor.local_robot_current_statistics_area")
        self.assertEqual(descriptor["signals"]["duration_sensor"], "sensor.local_robot_current_statistics_time")
        self.assertEqual(descriptor["signals"]["mop_intensity_entity"], "select.local_robot_water")
        self.assertEqual(descriptor["signals"]["mop_attached_sensor"], "binary_sensor.local_robot_mop")
        self.assertEqual(descriptor["signals"]["dock_clean_water_sensor"], "sensor.local_robot_water_tank_clean")
        self.assertEqual(descriptor["signals"]["dock_dirty_water_sensor"], "sensor.local_robot_water_tank_dirty")

    def test_matter_operational_error_is_kept_separate_from_generic_status(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptor = discovery.discover_descriptors(
            [
                {"entity_id": "vacuum.matter_robot", "platform": "matter", "unique_id": "vac", "device_id": "matter-dev"},
                {"entity_id": "sensor.matter_robot_error", "platform": "matter", "unique_id": "error", "device_id": "matter-dev", "translation_key": "operational_error"},
            ],
            [{"id": "matter-dev", "manufacturer": "TP-Link", "model_id": "1797"}],
            {
                "vacuum.matter_robot": {"state": "error", "attributes": {}},
                "sensor.matter_robot_error": {"state": "water_tank_empty", "attributes": {}},
            },
        )[0]

        self.assertEqual(
            descriptor["signals"],
            {"water_error_sensor": "sensor.matter_robot_error"},
        )

    def test_roborock_links_one_verified_separate_dock_from_the_same_config_entry(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        entities = [
            {"entity_id": "vacuum.robot", "platform": "roborock", "unique_id": "vac", "device_id": "robot-dev"},
            {"entity_id": "sensor.robot_status", "platform": "roborock", "unique_id": "status", "device_id": "robot-dev", "translation_key": "status"},
            {"entity_id": "binary_sensor.verified_clean", "platform": "roborock", "unique_id": "clean", "device_id": "dock-dev", "translation_key": "clean_box_empty"},
            {"entity_id": "binary_sensor.verified_dirty", "platform": "roborock", "unique_id": "dirty", "device_id": "dock-dev", "translation_key": "dirty_box_full"},
            {"entity_id": "sensor.verified_dock_error", "platform": "roborock", "unique_id": "error", "device_id": "dock-dev", "translation_key": "dock_error"},
            {"entity_id": "binary_sensor.unrelated_clean", "platform": "roborock", "unique_id": "other", "device_id": "other-dock", "translation_key": "clean_box_empty"},
        ]
        states = {record["entity_id"]: {"state": "ok", "attributes": {}} for record in entities}
        descriptor = discovery.discover_descriptors(
            entities,
            [
                {"id": "robot-dev", "manufacturer": "Roborock", "model": "roborock.vacuum.a97", "model_id": "roborock.vacuum.a97", "config_entries": {"entry-1"}},
                {"id": "dock-dev", "manufacturer": "Roborock", "model": "roborock.vacuum.a97 Dock", "model_id": "10", "config_entries": {"entry-1"}},
                {"id": "other-dock", "manufacturer": "Roborock", "model": "roborock.vacuum.a97 Dock", "model_id": "10", "config_entries": {"entry-2"}},
            ],
            states,
        )[0]

        self.assertEqual(descriptor["related_dock_confidence"], "high")
        self.assertEqual(descriptor["signals"]["status_sensor"], "sensor.robot_status")
        self.assertEqual(
            descriptor["signals"]["dock_clean_water_sensor"],
            "binary_sensor.verified_clean",
        )
        self.assertEqual(
            descriptor["signals"]["dock_dirty_water_sensor"],
            "binary_sensor.verified_dirty",
        )
        self.assertEqual(
            descriptor["signals"]["dock_error_sensor"],
            "sensor.verified_dock_error",
        )
        self.assertNotIn("binary_sensor.unrelated_clean", descriptor["signals"].values())


if __name__ == "__main__":
    unittest.main(verbosity=2)
