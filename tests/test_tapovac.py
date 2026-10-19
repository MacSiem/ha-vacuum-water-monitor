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
            "accounting_evidence": "user_measured"}


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

    def test_entering_mapping_does_not_charge_retained_counters(self):
        dev = device()
        first = observe(dev)
        result = observe(dev, first, code=2, area=10, minutes=1, now=1_060_000)
        self.assertEqual(result["used_ml"], 0)

    def test_counter_reset_does_not_double_count_or_go_negative(self):
        dev = device()
        state = observe(dev)
        state = observe(dev, state, area=10, minutes=1, now=1_060_000)
        state = observe(dev, state, area=0, minutes=0, now=1_120_000)
        state = observe(dev, state, area=3, minutes=1, now=1_180_000)
        self.assertEqual(state["used_ml"], 26)

    def test_missing_mode_after_a_valid_interval_does_not_charge_new_area(self):
        dev = device()
        state = observe(dev)
        state = observe(dev, state, area=2, minutes=1, now=1_060_000)
        result = observe(dev, state, mode="unavailable", area=10, minutes=2, now=1_120_000)
        self.assertEqual(result["used_ml"], 4)

    def test_changed_intensity_rebaselines_before_using_new_coefficient(self):
        dev = device()
        state = observe(dev)
        state = observe(dev, state, area=2, minutes=1, now=1_060_000)
        state = observe(dev, state, area=3, minutes=2, water="high", now=1_120_000)
        result = observe(dev, state, area=5, minutes=3, water="high", now=1_180_000)
        self.assertEqual(result["used_ml"], 12)

    def test_duplicate_unit_contract_fails_closed(self):
        d = _load_discovery()
        entities = [dict(entity_id="vacuum.test", platform="tapo_rv30", unique_id="entry_vacuum", device_id="robot")]
        entities += [dict(entity_id=f"select.unit_{n}", platform="tapo_rv30", unique_id="entry_area_unit", device_id="robot") for n in range(2)]
        result = d.discover_descriptors(entities, [dict(id="robot")], {})[0]
        self.assertNotIn("area_unit_entity", result["signals"])

    def test_confirmed_matter_link_binds_mode_without_yaml_or_importing_bank(self):
        from test_sensor_calculations import build_vacuum_devices
        native = descriptor()
        matter = {"entity_id": "vacuum.bridge", "integration_adapter": "matter", "identity_group": "bridge",
                  "signals": {"cleaning_mode_entity": "select.bridge_mode"}}
        separate = build_vacuum_devices({}, {}, [native, matter])
        self.assertEqual(len(separate), 2)
        linked = build_vacuum_devices({"robot_links": {"vacuum.bridge": "vacuum.test"}}, {}, [native, matter])
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["vacuum_entity"], "vacuum.test")
        self.assertEqual(linked[0].get("cleaning_mode_entity"), "select.bridge_mode")
        self.assertEqual(linked[0]["signals"]["cleaning_mode_entity"], "select.bridge_mode")
        self.assertEqual(linked[0].get("linked_mode_source"), "vacuum.bridge")
        self.assertEqual(linked[0]["area_unit_entity"], "select.area_unit")

    def test_mode_binding_is_recomputed_after_unlink_without_mutating_discovery(self):
        from test_sensor_calculations import build_vacuum_devices
        native = descriptor()
        matter = {"entity_id": "vacuum.bridge", "integration_adapter": "matter", "identity_group": "bridge",
                  "signals": {"cleaning_mode_entity": "select.bridge_mode"}}
        discovered = [native, matter]
        linked = build_vacuum_devices({"robot_links": {"vacuum.bridge": "vacuum.test"}}, {}, discovered)
        self.assertEqual(linked[0].get("cleaning_mode_entity"), "select.bridge_mode")
        self.assertNotIn("cleaning_mode_entity", native["signals"])
        for settings in ({}, {"robot_links": {"vacuum.bridge": "distinct"}}):
            result = build_vacuum_devices(settings, {}, discovered)
            self.assertEqual(len(result), 2)
            self.assertNotIn("cleaning_mode_entity", next(d for d in result if d["vacuum_entity"] == "vacuum.test"))

    def test_suggested_duplicate_never_authorizes_mode_import(self):
        from test_sensor_calculations import build_vacuum_devices
        native = descriptor()
        matter = {"entity_id": "vacuum.bridge", "integration_adapter": "matter", "possible_duplicate_of": "vacuum.test",
                  "signals": {"cleaning_mode_entity": "select.bridge_mode"}}
        result = build_vacuum_devices({}, {}, [native, matter])
        self.assertNotIn("cleaning_mode_entity", next(d for d in result if d["vacuum_entity"] == "vacuum.test"))

    def test_ambiguous_linked_matter_sources_do_not_pick_a_mode(self):
        from test_sensor_calculations import build_vacuum_devices
        sources = [{"entity_id": "vacuum.bridge"+str(n), "integration_adapter": "matter",
                    "signals": {"cleaning_mode_entity": "select.mode"+str(n)}} for n in (1, 2)]
        settings = {"robot_links": {d["entity_id"]: "vacuum.test" for d in sources}}
        result = build_vacuum_devices(settings, {}, [descriptor(), *sources])
        self.assertEqual(len(result), 1)
        self.assertNotIn("cleaning_mode_entity", result[0])

    def test_explicit_native_mode_wins_over_linked_mode(self):
        from test_sensor_calculations import build_vacuum_devices
        matter = {"entity_id": "vacuum.bridge", "integration_adapter": "matter",
                  "signals": {"cleaning_mode_entity": "select.bridge_mode"}}
        settings = {"robot_links": {"vacuum.bridge": "vacuum.test"},
                    "configured_devices": [{"vacuum_entity": "vacuum.test", "cleaning_mode_entity": "select.authored"}]}
        self.assertEqual(build_vacuum_devices(settings, {}, [descriptor(), matter])[0]["cleaning_mode_entity"], "select.authored")

    def test_automatic_linked_mode_controls_native_accounting(self):
        from test_sensor_calculations import build_vacuum_devices
        matter = {"entity_id": "vacuum.bridge", "integration_adapter": "matter",
                  "signals": {"cleaning_mode_entity": "select.mode", "area_sensor": "sensor.foreign_area"}}
        settings = {"robot_links": {"vacuum.bridge": "vacuum.test"},
                    "configured_devices": [{"vacuum_entity": "vacuum.test", "usage_ml_per_m2": {"high": 4}, "accounting_evidence": "user_measured"}]}
        dev = build_vacuum_devices(settings, {}, [descriptor(), matter])[0]
        self.assertEqual(dev.get("cleaning_mode_entity"), "select.mode")
        self.assertNotIn("area_sensor", dev)
        state = observe(dev, mode="Vacuum", water="high")
        state = observe(dev, state, mode="Vacuum", water="high", area=2, minutes=1, now=1_060_000)
        self.assertEqual(state["used_ml"], 0)
        state = observe(dev, state, water="high", area=2, minutes=1, now=1_120_000)
        state = observe(dev, state, water="high", area=4, minutes=2, now=1_180_000)
        self.assertEqual(state["used_ml"], 8)

    def test_time_fallback_and_recovered_area_do_not_charge_twice(self):
        dev = device()
        state = observe(dev)
        state = observe(dev, state, area=2, minutes=1, now=1_060_000)
        state = observe(dev, state, area=4, minutes=2, unit="unavailable", now=1_120_000)
        state = observe(dev, state, area=6, minutes=3, now=1_180_000)
        self.assertEqual(state["used_ml"], 10)  # 4 ml area + 2 observed minutes * 3

    def test_attribute_water_level_overrides_declared_calibration_context(self):
        dev = device()
        dev["consumption_context"] = {"model_id": "test", "reservoir": "dock_clean",
                                      "settings": {"water_level": "low"}}
        state = observe(dev, water="high")
        context = state["last_consumption_context"]
        self.assertEqual(context["settings"]["water_level"], "high")
        self.assertEqual(context["field_sources"]["water_level"], "observed")

    def test_native_counter_can_learn_from_full_tanks_without_manual_rates(self):
        from importlib import import_module
        apply_refill = import_module(tick.__package__ + '.refill').apply_refill
        dev = device()
        dev.pop("usage_ml_per_m2")
        dev.pop("usage_ml_per_active_minute")
        state = {}
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            apply_refill(state, now, 'service', rebaseline=True)
            state = observe(dev, state, code=5, now=now)
            state = observe(dev, state, now=now+60_000)
            for minute in range(1, 11):
                state = observe(dev, state, minutes=minute, area=minute, now=now+60_000+minute*60_000)
            state = observe(dev, state, code=5, minutes=10, area=10, now=now+720_000)
            state["user_empty_active"] = True
            state = observe(dev, state, code=5, minutes=10, area=10, now=now+780_000)
        self.assertEqual(state.get("nominal_time_resolution", {}).get("status"), "active", {"resolution": state.get("nominal_time_resolution"), "learning": state.get("nominal_time_learning"), "capacity": dev.get("tracked_capacity_ml"), "adapter": dev.get("integration_adapter")})
        self.assertEqual(state["nominal_time_resolution"]["sample_count"], 3)
        now += 2_000_000
        apply_refill(state, now, 'service', rebaseline=True)
        state = observe(dev, state, code=5, now=now)
        state = observe(dev, state, now=now+60_000)
        state = observe(dev, state, minutes=1, area=1, now=now+120_000)
        self.assertAlmostEqual(state["used_ml"], 475)

    def test_unconfigured_native_profile_never_imports_class_prior_doses(self):
        from test_sensor_calculations import build_vacuum_devices, apply_custom_calibration
        dev = apply_custom_calibration(build_vacuum_devices({}, {}, [descriptor()])[0], {})
        self.assertEqual(dev["tracked_capacity_ml"], 5000)
        self.assertFalse(dev.get("usage_ml_per_m2"))
        self.assertFalse(dev.get("usage_ml_per_active_minute"))
        self.assertFalse(dev.get("wash_volume_ml"))
        self.assertFalse(dev.get("intensity_factor"))

    def test_unknown_status_gap_is_not_billed_after_recovery(self):
        dev = device()
        state = observe(dev)
        state = observe(dev, state, code=999, area=4, minutes=1, now=1_060_000)
        state = observe(dev, state, area=6, minutes=2, now=1_120_000)
        result = observe(dev, state, area=8, minutes=3, now=1_180_000)
        self.assertEqual(result["used_ml"], 4)

    def test_explicit_mop_mode_alone_observes_counter_and_unknown_invalidates(self):
        from importlib import import_module
        apply_refill = import_module(tick.__package__ + '.refill').apply_refill
        dev = device()
        dev.pop("cleaning_mode_entity")
        dev.pop("usage_ml_per_m2")
        dev.pop("usage_ml_per_active_minute")
        dev["mop_mode_entity"] = "select.mode"
        state = {}
        apply_refill(state, 1_000_000, 'service', rebaseline=True)
        state = observe(dev, state, code=5, mode="mopping")
        state = observe(dev, state, now=1_060_000, mode="mopping")
        state = observe(dev, state, minutes=1, area=1, now=1_120_000, mode="mopping")
        self.assertEqual(state.get("nominal_time_learning", {}).get("cycle", {}).get("active_minutes"), 1)
        state = observe(dev, state, minutes=2, area=2, now=1_180_000, mode="unknown")
        self.assertIsNone(state["nominal_time_learning"]["cycle"])
