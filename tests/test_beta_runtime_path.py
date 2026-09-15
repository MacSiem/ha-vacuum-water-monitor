"""5.7 regressions through the real runtime path: discovery descriptor ->
build_vacuum_devices -> apply_custom_calibration -> tick_device -> sensor state."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
import unittest

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "ha_vacuum_water_monitor"


def _load():
    ha = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
    core.HomeAssistant = getattr(core, "HomeAssistant", object)
    helpers = sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    store_mod = sys.modules.setdefault("homeassistant.helpers.storage", types.ModuleType("homeassistant.helpers.storage"))
    if not hasattr(store_mod, "Store"):
        class _Store:
            def __init__(self, *args, **kwargs):
                self._data = None

            async def async_load(self):
                return self._data

            async def async_save(self, data):
                self._data = data
        store_mod.Store = _Store
    ha.core, ha.helpers, helpers.storage = core, helpers, store_mod
    pkg = types.ModuleType("vwmruntimepkg")
    pkg.__path__ = [str(PKG)]
    sys.modules["vwmruntimepkg"] = pkg
    return (importlib.import_module("vwmruntimepkg.tick"), importlib.import_module("vwmruntimepkg.sensor_calculations"),
            importlib.import_module("vwmruntimepkg.discovery"))


tick, sc, discovery = _load()


class _S:
    def __init__(self, state, attributes=None):
        self.state, self.attributes = state, attributes or {}


class _Hass:
    def __init__(self, values):
        self.states = types.SimpleNamespace(get=values.get)
        self.config = types.SimpleNamespace(units=types.SimpleNamespace(length_unit="km"))


SIGNALS = {"sensor.robot_status": "status", "sensor.robot_area": "cleaning_area", "select.robot_mop_mode": "mop_mode",
           "select.robot_mop_intensity": "mop_intensity", "sensor.robot_dock_error": "dock_error",
           "binary_sensor.robot_mop_attached": "mop_attached"}


def descriptor(model_id="a97", signals=SIGNALS):
    entities = [{"entity_id": "vacuum.robot", "platform": "roborock", "unique_id": "v1", "device_id": "d1"}]
    entities += [{"entity_id": e, "platform": "roborock", "unique_id": e, "device_id": "d1", "translation_key": k}
                 for e, k in signals.items()]
    devices = [{"id": "d1", "manufacturer": "Roborock", "model_id": model_id, "model": "roborock.vacuum." + model_id}]
    states = {e["entity_id"]: {"state": "1", "attributes": {}} for e in entities}
    return discovery.discover_descriptors(entities, devices, states)[0]


def effective(settings, desc):
    return [sc.apply_custom_calibration(d, settings) for d in sc.build_vacuum_devices(settings, {}, [desc])][0]


def hass(status="charging", vac="docked", area="45.5", intensity="medium", dock_err="ok", mop="on", extra=None):
    values = {"sensor.robot_status": _S(status), "sensor.robot_area": _S(str(area), {"unit_of_measurement": "m²"}),
              "select.robot_mop_mode": _S("standard"), "select.robot_mop_intensity": _S(intensity),
              "sensor.robot_dock_error": _S(dock_err), "binary_sensor.robot_mop_attached": _S(mop),
              "vacuum.robot": _S(vac, {"status": status})}
    values.update(extra or {})
    return _Hass(values)


def run(device, state, steps, ts=10_000_000, step=60_000):
    for kwargs in steps:
        kwargs = dict(kwargs)
        ts += kwargs.pop("_gap", step)
        state, _ = tick.tick_device(hass(**kwargs), device, state, now_ts=ts)
    return state


BASE = {"used_ml": 0, "initialized": True, "last_area": 45.5, "last_status": "charging", "last_tick_ts": 9_940_000,
        "last_reset_ts": 0}


class RuntimePathTests(unittest.TestCase):
    def test_vacuum_only_run_with_water_level_off_uses_no_water(self):
        device = effective({}, descriptor())
        state = run(device, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="off", mop="unknown")]
                    + [dict(status="cleaning", vac="cleaning", area=str(a), intensity="off", mop="unknown") for a in (10, 20)])
        self.assertEqual(state["used_ml"], 0)

    def test_authored_refill_contract_from_settings_is_not_restricted(self):
        cfg = {"vacuum_entity": "vacuum.robot", "refill_on_clear": True, "water_anchor_reservoir": "dock_clean",
               "tracked_reservoir": "dock_clean", "reset_door_sensor": "binary_sensor.lid",
               "config_provenance": {"authored_fields": ["vacuum_entity", "refill_on_clear", "water_anchor_reservoir",
                                                         "tracked_reservoir", "reset_door_sensor"]}}
        device = effective({"configured_devices": [cfg]}, descriptor())
        self.assertNotIn("refill_on_clear_inferred", device)
        state = run(device, {**BASE, "used_ml": 3000},
                    [dict(extra={"binary_sensor.lid": _S("on")}), dict(extra={"binary_sensor.lid": _S("off")})])
        self.assertEqual(state["last_accounting_reason"], "refill_detected")

    def test_automatic_refill_clears_an_incomplete_balance_and_calibration_resumes(self):
        device = effective({}, descriptor())
        state = {**BASE, "used_ml": 3000, "accounting_incomplete": True, "last_dock_err": "ok"}
        state = run(device, state, [dict(dock_err="water_empty"), dict(dock_err="ok")])
        self.assertFalse(state["accounting_incomplete"])
        self.assertEqual(state["used_ml"], 0)
        state = run(device, {**state, "used_ml": 3000}, [dict(dock_err="water_empty"), dict(dock_err="ok")], ts=20_000_000)
        self.assertEqual(state["calibration_samples"], 1)

    def test_session_run_entirely_while_unobserved_is_reported(self):
        device = effective({}, descriptor())
        state = run(device, dict(BASE), [dict(vac="unavailable"), dict(area="20", _gap=3_600_000)])
        self.assertTrue(state["accounting_incomplete"])
        docked = run(device, dict(BASE), [dict(vac="unavailable"), dict(area="45.5", _gap=3_600_000)])
        self.assertFalse(docked.get("accounting_incomplete"))

    def test_authored_capacity_different_from_model_does_not_infer_dock_anchor(self):
        cfg = {"vacuum_entity": "vacuum.robot", "tracked_capacity_ml": 350,
               "config_provenance": {"authored_fields": ["vacuum_entity", "tracked_capacity_ml"]}}
        device = effective({"configured_devices": [cfg]}, descriptor("a245"))
        self.assertIsNone(device.get("water_anchor_reservoir"))
        self.assertFalse(device.get("refill_on_clear"))

    def test_whole_cycle_user_rate_neither_double_counts_washes_nor_flags_them(self):
        settings = {"custom_calibration": {"entity:vacuum.robot": {"usage_ml_per_m2": {"default": 8},
                                                                    "calibration_scope": "whole_cycle"}}}
        device = effective(settings, descriptor())
        steps = [dict(status="cleaning", vac="cleaning", area="0")] + [dict(status="cleaning", vac="cleaning", area=str(a)) for a in (10, 20)]
        steps += [dict(status="washing_the_mop", area="20"), dict(status="cleaning", vac="cleaning", area="20"),
                  dict(status="washing_the_mop", area="20"), dict(status="charging", area="20")]
        state = run(device, dict(BASE), steps)
        self.assertEqual(state["used_ml"], 160)
        self.assertFalse(state.get("accounting_incomplete"))
        result = sc.estimate_water_state(device, state, {})
        self.assertIsNone(result["estimate_basis"])
        self.assertIsNone(result["uncertainty_percent"])

    def test_estimate_without_any_mop_signal_is_not_shown_as_a_full_tank(self):
        desc = descriptor("a97", signals={"sensor.robot_status": "status", "sensor.robot_area": "cleaning_area"})
        device = effective({}, desc)
        result = sc.estimate_water_state(device, {**BASE, "used_ml": 0}, {})
        self.assertEqual(result["state_reason"], "mop_signal_unbound")
        self.assertIsNone(result["remaining_percent"])



class ReviewFollowUpTests(unittest.TestCase):
    def test_counter_reset_to_zero_while_unavailable_in_dock_is_not_exposure(self):
        device = effective({}, descriptor())
        state = run(device, dict(BASE), [dict(vac="unavailable"), dict(area="0", _gap=3_600_000), dict(area="0")])
        self.assertFalse(state.get("accounting_incomplete"))

    def test_empty_tank_displays_zero_remaining(self):
        device = effective({}, descriptor())
        state = run(device, {**BASE, "used_ml": 3000, "last_dock_err": "ok"}, [dict(dock_err="water_empty")])
        result = sc.estimate_water_state(device, state, {})
        self.assertEqual(result["remaining_ml"], 0)
        self.assertEqual(result["state_reason"], "water_empty")


if __name__ == "__main__":
    unittest.main()
