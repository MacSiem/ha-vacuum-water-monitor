"""Registry-fixture tests for MIoT-aware signal mapping and manual overrides.

These cover the failure reported in issue #11 (Xiaomi H50 Pro): a vacuum whose
integration is not HA Core ``xiaomi_miio`` resolved zero signals, because role
matching required an exact ``translation_key`` on a known platform.  The
official ``xiaomi_home`` integration publishes no ``translation_key`` at all,
and ``xiaomi_miot`` prefixes it with the MIoT service name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _load_discovery():
    profile_path = PKG_DIR / "profiles.py"
    discovery_path = PKG_DIR / "discovery.py"
    if not profile_path.is_file() or not discovery_path.is_file():
        return None
    package = types.ModuleType("vwmsignalmap")
    package.__path__ = [str(PKG_DIR)]
    sys.modules["vwmsignalmap"] = package
    for name, path in (("profiles", profile_path), ("discovery", discovery_path)):
        spec = importlib.util.spec_from_file_location(f"vwmsignalmap.{name}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"vwmsignalmap.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["vwmsignalmap.discovery"]


def _state(value: str, **attributes: object) -> dict[str, object]:
    return {"state": value, "attributes": dict(attributes)}


class XiaomiHomeSignalMappingTests(unittest.TestCase):
    """The official XiaoMi/ha_xiaomi_home integration exposes no translation_key.

    Its only machine-stable handle is the generated entity_id (which equals
    unique_id): ``<platform>.<model>_<cloud>_<did>_<miot_property>_p_<siid>_<piid>``.
    """

    def _fixture(self) -> tuple[list[dict], list[dict], dict]:
        entities = [
            {
                "entity_id": "vacuum.xiaomi_cn_9911_ov42gl_robot_cleaner_p_2_1",
                "platform": "xiaomi_home",
                "unique_id": "vacuum.xiaomi_cn_9911_ov42gl_robot_cleaner_p_2_1",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_status_p_2_2",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_status_p_2_2",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_cleaning_time_p_2_7",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_cleaning_time_p_2_7",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "select.xiaomi_cn_9911_ov42gl_mop_water_output_level_p_2_10",
                "platform": "xiaomi_home",
                "unique_id": "select.xiaomi_cn_9911_ov42gl_mop_water_output_level_p_2_10",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_water_tank_status_p_2_98",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_water_tank_status_p_2_98",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_sewage_tank_status_p_2_97",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_sewage_tank_status_p_2_97",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_base_station_water_tank_status_p_2_100",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_base_station_water_tank_status_p_2_100",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            # Consumable — must never be mistaken for a cleaning-duration signal.
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_mop_left_time_p_9_2",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_mop_left_time_p_9_2",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
        ]
        devices = [
            {
                "id": "h50pro-dev",
                "manufacturer": "Xiaomi",
                "model": "Xiaomi Robot Vacuum H50 Pro",
                "model_id": "xiaomi.vacuum.ov42gl",
            }
        ]
        states = {
            "vacuum.xiaomi_cn_9911_ov42gl_robot_cleaner_p_2_1": _state(
                "cleaning", friendly_name="H50 Pro"
            ),
            "sensor.xiaomi_cn_9911_ov42gl_status_p_2_2": _state("sweeping"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6": _state("12.5"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_time_p_2_7": _state(
                "600", unit_of_measurement="s", device_class="duration"
            ),
            "select.xiaomi_cn_9911_ov42gl_mop_water_output_level_p_2_10": _state("2"),
            "sensor.xiaomi_cn_9911_ov42gl_water_tank_status_p_2_98": _state("not-empty"),
            "sensor.xiaomi_cn_9911_ov42gl_sewage_tank_status_p_2_97": _state("not-full"),
            "sensor.xiaomi_cn_9911_ov42gl_base_station_water_tank_status_p_2_100": _state(
                "not-empty"
            ),
            "sensor.xiaomi_cn_9911_ov42gl_mop_left_time_p_9_2": _state(
                "180", unit_of_measurement="min", device_class="duration"
            ),
        }
        return entities, devices, states

    def test_miot_property_suffix_resolves_core_accounting_roles(self) -> None:
        discovery = _load_discovery()
        self.assertIsNotNone(discovery)
        assert discovery is not None
        entities, devices, states = self._fixture()

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]
        signals = descriptor["signals"]

        self.assertEqual(descriptor["integration_adapter"], "xiaomi_home")
        self.assertEqual(
            signals.get("area_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6",
        )
        self.assertEqual(
            signals.get("duration_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_time_p_2_7",
        )
        self.assertEqual(
            signals.get("status_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_status_p_2_2",
        )
        self.assertEqual(
            signals.get("mop_intensity_entity"),
            "select.xiaomi_cn_9911_ov42gl_mop_water_output_level_p_2_10",
        )

    def test_dock_and_robot_tanks_are_not_confused(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()

        signals = discovery.discover_descriptors(entities, devices, states)[0]["signals"]

        self.assertEqual(
            signals.get("water_box_attached_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_water_tank_status_p_2_98",
        )
        self.assertEqual(
            signals.get("dock_dirty_water_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_sewage_tank_status_p_2_97",
        )
        self.assertEqual(
            signals.get("dock_clean_water_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_base_station_water_tank_status_p_2_100",
        )

    def test_lifetime_counters_never_become_current_run_signals(self) -> None:
        """MIoT publishes lifetime totals beside the per-run values.

        A suffix match alone accepts ``total_clean_area`` as ``clean_area``,
        which both reads a monotonically growing total as one session and
        creates a tie that drops the real per-run sensor entirely.
        """
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()
        entities += [
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_total_clean_area_p_8_1",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_total_clean_area_p_8_1",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
            {
                "entity_id": "sensor.xiaomi_cn_9911_ov42gl_statistical_clean_time_p_8_2",
                "platform": "xiaomi_home",
                "unique_id": "sensor.xiaomi_cn_9911_ov42gl_statistical_clean_time_p_8_2",
                "device_id": "h50pro-dev",
                "translation_key": None,
            },
        ]
        states["sensor.xiaomi_cn_9911_ov42gl_total_clean_area_p_8_1"] = _state("980")
        states["sensor.xiaomi_cn_9911_ov42gl_statistical_clean_time_p_8_2"] = _state(
            "72000"
        )

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]
        signals = descriptor["signals"]

        self.assertEqual(
            signals.get("area_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6",
        )
        self.assertEqual(
            signals.get("duration_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_time_p_2_7",
        )
        self.assertNotIn("area_sensor", descriptor["ambiguous_roles"])
        self.assertNotIn("duration_sensor", descriptor["ambiguous_roles"])

    def test_unrelated_mode_entities_are_not_claimed_as_cleaning_mode(self) -> None:
        """A bare ``mode`` alias would match dnd_mode, carpet_mode, water_mode."""
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()
        for name, siid in (("dnd_mode", "8_1"), ("carpet_mode", "2_30")):
            entity_id = f"select.xiaomi_cn_9911_ov42gl_{name}_p_{siid}"
            entities.append(
                {
                    "entity_id": entity_id,
                    "platform": "xiaomi_home",
                    "unique_id": entity_id,
                    "device_id": "h50pro-dev",
                    "translation_key": None,
                }
            )
            states[entity_id] = _state("off")

        signals = discovery.discover_descriptors(entities, devices, states)[0]["signals"]

        self.assertNotIn(
            signals.get("cleaning_mode_entity"),
            {
                "select.xiaomi_cn_9911_ov42gl_dnd_mode_p_8_1",
                "select.xiaomi_cn_9911_ov42gl_carpet_mode_p_2_30",
            },
        )

    def test_other_status_entities_do_not_displace_the_run_status(self) -> None:
        """Many MIoT properties end in ``status``.

        Suffix matching alone makes every one of them a candidate for the run
        status, which previously produced a tie and dropped the role.
        """
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()
        for name, siid in (("task_status", "2_9"), ("dust_bag_status", "19_1")):
            entity_id = f"sensor.xiaomi_cn_9911_ov42gl_{name}_p_{siid}"
            entities.append(
                {
                    "entity_id": entity_id,
                    "platform": "xiaomi_home",
                    "unique_id": entity_id,
                    "device_id": "h50pro-dev",
                    "translation_key": None,
                }
            )
            states[entity_id] = _state("ok")

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertEqual(
            descriptor["signals"].get("status_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_status_p_2_2",
        )
        self.assertNotIn("status_sensor", descriptor["ambiguous_roles"])

    def test_home_assistant_collision_suffix_still_resolves(self) -> None:
        """HA appends ``_2`` when a generated entity_id is already taken."""
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()
        for entry in entities:
            if entry["entity_id"].endswith("_cleaning_area_p_2_6"):
                old = entry["entity_id"]
                entry["entity_id"] = f"{old}_2"
                entry["unique_id"] = f"{old}_2"
                states[f"{old}_2"] = states.pop(old)

        signals = discovery.discover_descriptors(entities, devices, states)[0]["signals"]

        self.assertEqual(
            signals.get("area_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_cleaning_area_p_2_6_2",
        )

    def test_consumable_countdown_never_becomes_duration_signal(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()

        signals = discovery.discover_descriptors(entities, devices, states)[0]["signals"]

        self.assertNotEqual(
            signals.get("duration_sensor"),
            "sensor.xiaomi_cn_9911_ov42gl_mop_left_time_p_9_2",
        )


class XiaomiMiotSignalMappingTests(unittest.TestCase):
    """al-one/hass-xiaomi-miot prefixes translation_key with the MIoT service."""

    def test_service_prefixed_translation_key_resolves_roles(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities = [
            {
                "entity_id": "vacuum.xiaomi_ov42gl_ab12",
                "platform": "xiaomi_miot",
                "unique_id": "dev-uid-vacuum",
                "device_id": "miot-dev",
            },
            {
                "entity_id": "sensor.xiaomi_ov42gl_ab12_cleaning_area",
                "platform": "xiaomi_miot",
                "unique_id": "dev-uid-vacuum-2.cleaning_area-6",
                "device_id": "miot-dev",
                "translation_key": "vacuum-cleaning_area",
            },
            {
                "entity_id": "sensor.xiaomi_ov42gl_ab12_cleaning_time",
                "platform": "xiaomi_miot",
                "unique_id": "dev-uid-vacuum-2.cleaning_time-7",
                "device_id": "miot-dev",
                "translation_key": "vacuum-cleaning_time",
            },
            {
                "entity_id": "sensor.xiaomi_ov42gl_ab12_status",
                "platform": "xiaomi_miot",
                "unique_id": "dev-uid-vacuum-2.status-2",
                "device_id": "miot-dev",
                "translation_key": "vacuum-status",
            },
            {
                "entity_id": "binary_sensor.xiaomi_ov42gl_ab12_mop_status",
                "platform": "xiaomi_miot",
                "unique_id": "dev-uid-vacuum-2.mop_status-11",
                "device_id": "miot-dev",
                "translation_key": "vacuum-mop_status",
            },
        ]
        devices = [
            {
                "id": "miot-dev",
                "manufacturer": "Xiaomi",
                "model": "xiaomi.vacuum.ov42gl",
                "model_id": "xiaomi.vacuum.ov42gl",
            }
        ]
        states = {
            "vacuum.xiaomi_ov42gl_ab12": _state("cleaning"),
            "sensor.xiaomi_ov42gl_ab12_cleaning_area": _state("9.1"),
            "sensor.xiaomi_ov42gl_ab12_cleaning_time": _state("420"),
            "sensor.xiaomi_ov42gl_ab12_status": _state("sweeping"),
            "binary_sensor.xiaomi_ov42gl_ab12_mop_status": _state("on"),
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]
        signals = descriptor["signals"]

        self.assertEqual(descriptor["integration_adapter"], "xiaomi_miot")
        self.assertEqual(
            signals.get("area_sensor"), "sensor.xiaomi_ov42gl_ab12_cleaning_area"
        )
        self.assertEqual(
            signals.get("duration_sensor"), "sensor.xiaomi_ov42gl_ab12_cleaning_time"
        )
        self.assertEqual(
            signals.get("status_sensor"), "sensor.xiaomi_ov42gl_ab12_status"
        )
        self.assertEqual(
            signals.get("mop_attached_sensor"),
            "binary_sensor.xiaomi_ov42gl_ab12_mop_status",
        )


class DuplicateRoleCandidateTests(unittest.TestCase):
    """HA Core xiaomi_miio creates two entities with the same translation_key.

    ``is_water_box_attached`` is registered twice for mop-capable models, so the
    old "exactly one candidate" rule dropped the role silently for every Xiaomi
    vacuum with a mop.
    """

    def _fixture(self) -> tuple[list[dict], list[dict], dict]:
        entities = [
            {
                "entity_id": "vacuum.xiaomi_s7",
                "platform": "xiaomi_miio",
                "unique_id": "vac",
                "device_id": "s7-dev",
            },
            {
                "entity_id": "binary_sensor.xiaomi_s7_water_box_attached",
                "platform": "xiaomi_miio",
                "unique_id": "box-a",
                "device_id": "s7-dev",
                "translation_key": "is_water_box_attached",
            },
            {
                "entity_id": "binary_sensor.xiaomi_s7_water_box_attached_2",
                "platform": "xiaomi_miio",
                "unique_id": "box-b",
                "device_id": "s7-dev",
                "translation_key": "is_water_box_attached",
            },
        ]
        devices = [{"id": "s7-dev", "manufacturer": "Xiaomi", "model": "Mi Robot Vacuum"}]
        states = {
            "vacuum.xiaomi_s7": _state("cleaning"),
            "binary_sensor.xiaomi_s7_water_box_attached": _state("on"),
            "binary_sensor.xiaomi_s7_water_box_attached_2": _state("on"),
        }
        return entities, devices, states

    def test_duplicate_candidates_resolve_instead_of_vanishing(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertIn(
            "water_box_attached_sensor",
            descriptor["signals"],
            "a duplicated vendor translation_key must not drop the role",
        )

    def test_resolution_is_deterministic_regardless_of_registry_order(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()
        reversed_entities = [entities[0], entities[2], entities[1]]

        first = discovery.discover_descriptors(entities, devices, states)[0]
        second = discovery.discover_descriptors(reversed_entities, devices, states)[0]

        self.assertEqual(
            first["signals"].get("water_box_attached_sensor"),
            second["signals"].get("water_box_attached_sensor"),
        )

    def test_measurement_roles_still_refuse_to_guess(self) -> None:
        """Two different area sensors are not interchangeable evidence.

        Resolving a binary duplicate is safe; resolving between two distinct
        measurements would invent a consumption figure, so that stays closed.
        """
        discovery = _load_discovery()
        assert discovery is not None
        entities = [
            {
                "entity_id": "vacuum.kitchen",
                "platform": "roborock",
                "unique_id": "vac",
                "device_id": "dev-1",
            },
            {
                "entity_id": "sensor.area_one",
                "platform": "roborock",
                "unique_id": "a1",
                "device_id": "dev-1",
                "translation_key": "cleaning_area",
            },
            {
                "entity_id": "sensor.area_two",
                "platform": "roborock",
                "unique_id": "a2",
                "device_id": "dev-1",
                "translation_key": "cleaning_area",
            },
        ]
        devices = [{"id": "dev-1", "manufacturer": "Roborock", "model_id": "a170"}]
        states = {
            "vacuum.kitchen": _state("docked"),
            "sensor.area_one": _state("3"),
            "sensor.area_two": _state("4"),
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertNotIn("area_sensor", descriptor["signals"])
        self.assertIn("area_sensor", descriptor["ambiguous_roles"])

    def test_ambiguous_role_is_reported_for_the_card(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities, devices, states = self._fixture()

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertIn("water_box_attached_sensor", descriptor.get("ambiguous_roles", []))


class ManualMappingCandidateTests(unittest.TestCase):
    """The card needs sibling metadata to offer a manual entity assignment."""

    def test_descriptor_exposes_assignable_sibling_entities(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities = [
            {
                "entity_id": "vacuum.unknown_brand",
                "platform": "some_hacs_integration",
                "unique_id": "vac",
                "device_id": "unknown-dev",
            },
            {
                "entity_id": "sensor.unknown_brand_area_cleaned",
                "platform": "some_hacs_integration",
                "unique_id": "area",
                "device_id": "unknown-dev",
                "original_name": "Area cleaned",
            },
        ]
        devices = [{"id": "unknown-dev", "manufacturer": "Unknown", "model": "X1"}]
        states = {
            "vacuum.unknown_brand": _state("cleaning"),
            "sensor.unknown_brand_area_cleaned": _state(
                "11.0", unit_of_measurement="m²", device_class="area"
            ),
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]
        siblings = descriptor.get("sibling_entities")

        self.assertIsInstance(siblings, list)
        assert isinstance(siblings, list)
        match = [
            item
            for item in siblings
            if item.get("entity_id") == "sensor.unknown_brand_area_cleaned"
        ]
        self.assertTrue(match, "unmapped siblings must be offered for manual mapping")
        self.assertEqual(match[0].get("device_class"), "area")
        self.assertEqual(match[0].get("unit_of_measurement"), "m²")

    def test_unknown_platform_still_lists_siblings_even_with_no_signals(self) -> None:
        discovery = _load_discovery()
        assert discovery is not None
        entities = [
            {
                "entity_id": "vacuum.mystery",
                "platform": "mystery_integration",
                "unique_id": "vac",
                "device_id": "mystery-dev",
            },
            {
                "entity_id": "sensor.mystery_thing",
                "platform": "mystery_integration",
                "unique_id": "thing",
                "device_id": "mystery-dev",
            },
        ]
        devices = [{"id": "mystery-dev", "manufacturer": "Mystery", "model": "M"}]
        states = {
            "vacuum.mystery": _state("docked"),
            "sensor.mystery_thing": _state("3"),
        }

        descriptor = discovery.discover_descriptors(entities, devices, states)[0]

        self.assertEqual(descriptor["signals"], {})
        self.assertTrue(descriptor.get("sibling_entities"))


if __name__ == "__main__":
    unittest.main()
