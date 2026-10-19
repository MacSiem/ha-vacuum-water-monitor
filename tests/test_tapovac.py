"""TapoVac-ADV producer-shaped telemetry, without invented physical rates."""
import unittest
from test_discovery import _load_discovery
from test_tick import tick, _Hass, _State


def descriptor(unit="m²", select_patch=None):
    entities = [dict(entity_id="vacuum.test", platform="tapo_rv30", unique_id="entry_vacuum", device_id="robot"),
                {**dict(entity_id="select.area_unit", platform="tapo_rv30", unique_id="entry_area_unit", device_id="robot"), **(select_patch or {})}]
    return _load_discovery().discover_descriptors(entities, [dict(id="robot", manufacturer="Tapo", model="RV50 Pro Omni")],
        {"select.area_unit": _State(unit)})[0]


def device():
    desc = descriptor()
    return {**desc, **desc["signals"], "vacuum_entity": "vacuum.test",
            "cleaning_mode_entity": "select.mode", "usage_ml_per_m2": {"low": 2, "high": 4},
            "usage_ml_per_active_minute": {"low": 3, "high": 6},
            "rate_signal": "mop_intensity", "accounting_evidence": "user_measured"}


def observe(dev, previous=None, *, mode="Vacuum and Mop;Deep Clean", code=1, area=0, minutes=0,
            water="low", attached=True, unit="m²", now=1_000_000):
    hass = _Hass({"vacuum.test": _State("cleaning", {"status_code": code, "clean_area": area,
                  "clean_time_min": minutes, "water_level": water, "mop_attached": attached}),
                  "select.mode": _State(mode), "select.area_unit": _State(unit)})
    return tick.tick_device(hass, dev, previous or {"used_ml": 0, "initialized": True}, now_ts=now)[0]


class TapoVacTests(unittest.TestCase):
    def test_attribute_counters_feed_area_accounting_with_explicit_mop_mode(self):
        dev = device()
        first = observe(dev)
        result = observe(dev, first, area=10, minutes=1, now=1_060_000)
        self.assertEqual(result["used_ml"], 20)
        self.assertEqual(result["last_duration_seconds"], 60)

    def test_attached_and_high_never_prove_mopping(self):
        for mode in ("unavailable", "unknown", "Vacuum", "Vacuum then Mop"):
            with self.subTest(mode=mode):
                dev = device()
                first = observe(dev, mode=mode, water="high")
                result = observe(dev, first, mode=mode, water="high", area=10, minutes=1, now=1_060_000)
                self.assertEqual(result["used_ml"], 0)

    def test_mapping_off_detached_and_unknown_status_never_consume(self):
        for patch in ({"code": 2}, {"code": 999}, {"code": None}, {"water": "off"}, {"attached": False}):
            with self.subTest(patch=patch):
                dev = device()
                first = observe(dev, **patch)
                result = observe(dev, first, area=10, minutes=1, now=1_060_000, **patch)
                self.assertEqual(result["used_ml"], 0)

    def test_unverified_area_units_use_observed_minutes_instead(self):
        for unit in ("ft²", "unavailable", "unknown"):
            with self.subTest(unit=unit):
                dev = device()
                first = observe(dev, unit=unit)
                result = observe(dev, first, area=100, minutes=1, unit=unit, now=1_060_000)
                self.assertEqual(result["used_ml"], 3)

    def test_units_binding_uses_exact_same_device_machine_id(self):
        self.assertEqual(descriptor()["signals"].get("area_unit_entity"), "select.area_unit")
        for patch in ({"device_id": "other"}, {"unique_id": "other_area_unit"},
                      {"disabled_by": "user"}, {"platform": "tplink"}, {"entity_id": "sensor.area_unit"}):
            with self.subTest(patch=patch):
                self.assertNotIn("area_unit_entity", descriptor(select_patch=patch)["signals"])

    def test_missing_counters_do_not_fall_back_to_unobserved_wall_time(self):
        dev = device()
        first = observe(dev, area=None, minutes=None)
        result = observe(dev, first, area=None, minutes=None, now=1_060_000)
        self.assertEqual(result["used_ml"], 0)
