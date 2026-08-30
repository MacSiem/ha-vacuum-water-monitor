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

    def test_tapo_matter_descriptor_has_capacity_but_no_invented_signals(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery, "discovery module must exist")
        assert discovery is not None
        descriptors = discovery.discover_descriptors(
            [{"entity_id": "vacuum.opaque", "platform": "matter", "unique_id": "matter-vac", "device_id": "tapo-device"}],
            [{"id": "tapo-device", "manufacturer": "TP-Link", "model": "RV50 Pro Omni (1797)", "model_id": "1797"}],
            {"vacuum.opaque": {"state": "docked", "attributes": {}}},
        )

        descriptor = descriptors[0]
        self.assertEqual(descriptor["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(descriptor["tracked_capacity_ml"], 5000)
        self.assertEqual(descriptor["capability"], "manual_only")
        self.assertEqual(descriptor["signals"], {})

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
