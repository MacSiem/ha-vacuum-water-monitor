"""5.7 labelled estimates, reservoir inference and the empty-tank calibrator."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

from test_tick import _Hass, _State, tick
from test_sensor_calculations import apply_custom_calibration, estimate_water_state

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/ha_vacuum_water_monitor"
_spec = importlib.util.spec_from_file_location("vwm_beta_profiles", PKG / "profiles.py")
profiles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profiles)
estimation = profiles.estimation


def resolve(model_id, manufacturer="Roborock"):
    return profiles.resolve_profile({"manufacturer": manufacturer, "model_id": model_id})


class LabelledEstimateResolutionTests(unittest.TestCase):
    def test_owner_device_estimate_for_s8_maxv_ultra(self):
        r = profiles.resolve_profile({"profile_key": "roborock_s8_maxv_ultra"})
        self.assertEqual(r["capability"], "automatic_estimate")
        self.assertEqual(r["estimate_basis"], "owner_device")
        self.assertEqual(r["accounting_evidence"], "labeled_estimate")
        self.assertEqual((r["usage_ml_per_m2"]["fast"], r["usage_ml_per_m2"]["standard"],
                          r["usage_ml_per_m2"]["deep"]), (4, 6, 9))
        self.assertEqual(r["intensity_factor"]["high"], 1.3)
        self.assertEqual(r["wash_volume_ml"], 150)
        self.assertEqual(r["calibration_scope"], "floor_only")
        self.assertEqual(r["uncertainty_percent"], 20)
        self.assertEqual((r["tracked_reservoir"], r["tracked_capacity_ml"]), ("dock_clean", 4000))
        self.assertEqual(r["water_anchor_reservoir"], "dock_clean")
        self.assertTrue(r["refill_on_clear"])

    def test_issue_12_roller_model_has_capacity_and_class_prior(self):
        r = resolve("roborock.vacuum.a245", "Beijing Roborock Technology Co., Ltd.")
        self.assertEqual(r["profile_key"], "roborock_qrevo_curv_2_flow")
        self.assertEqual(r["mop_system"], "roller")
        self.assertEqual(r["estimate_basis"], "class_prior")
        self.assertEqual(r["uncertainty_percent"], 50)
        self.assertEqual((r["tracked_reservoir"], r["tracked_capacity_ml"]), ("dock_clean", 4000))
        self.assertEqual(r["reservoirs_ml"]["dock_dirty"], 3000)

    def test_rotating_pad_model_and_generic_prior(self):
        self.assertEqual(resolve("roborock.vacuum.a170")["mop_system"], "rotating_pads")
        dreame = profiles.resolve_profile({"profile_key": "dreame_x40_ultra"})
        self.assertEqual(dreame["estimate_basis"], "generic_prior")
        self.assertEqual(dreame["uncertainty_percent"], 65)
        self.assertTrue(dreame["usage_ml_per_m2"])

    def test_unrecognised_model_still_fails_closed(self):
        self.assertEqual(profiles.resolve_profile({"model": "unlisted"})["capability"], "unknown")

    def test_invalid_estimates_are_rejected(self):
        base = json.loads((PKG / "model_profiles.json").read_text())
        mutations = [
            ("basis", "guess"),
            ("sources", []),
            ("usage_ml_per_m2", {"default": 0}),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                payload = json.loads(json.dumps(base))
                payload["profiles"]["roborock_s8_maxv_ultra"]["estimate"][field] = value
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as handle:
                    json.dump(payload, handle)
                    handle.flush()
                    with self.assertRaises(profiles.CatalogValidationError):
                        profiles.load_catalog(handle.name)
        payload = json.loads(json.dumps(base))
        payload["profiles"]["roborock_s8_maxv_ultra"]["mop_system"] = "sponge"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as handle:
            json.dump(payload, handle)
            handle.flush()
            with self.assertRaises(profiles.CatalogValidationError):
                profiles.load_catalog(handle.name)

    def test_user_calibration_replaces_estimate_bands(self):
        effective = apply_custom_calibration(
            {"vacuum_entity": "vacuum.s8", "profile_key": "roborock_s8_maxv_ultra"},
            {"custom_calibration": {"entity:vacuum.s8": {"usage_ml_per_m2": {"default": 8}}}},
        )
        self.assertNotIn("fast", effective["usage_ml_per_m2"])
        self.assertEqual(effective["usage_ml_per_m2"]["default"], 8)
        self.assertNotEqual(effective.get("accounting_evidence"), "labeled_estimate")


A245_SIGNALS = {
    "status_sensor": "sensor.chappie_etat",
    "area_sensor": "sensor.chappie_surface",
    "mop_mode_entity": "select.chappie_parcours",
    "mop_intensity_entity": "select.chappie_intensite",
    "mop_attached_sensor": "binary_sensor.chappie_serpilliere",
    "dock_error_sensor": "sensor.chappie_dock_erreur",
}


def a245_hass(status, area, vac="cleaning", dock_err="ok"):
    return _Hass({
        "vacuum.chappie": _State(vac, {"status": status}),
        "sensor.chappie_etat": _State(status),
        "sensor.chappie_surface": _State(str(area), {"unit_of_measurement": "m²"}),
        "select.chappie_parcours": _State("standard"),
        "select.chappie_intensite": _State("medium"),
        "binary_sensor.chappie_serpilliere": _State("on"),
        "sensor.chappie_dock_erreur": _State(dock_err),
    }, length_unit="km")


def a245_device():
    return apply_custom_calibration({
        "vacuum_entity": "vacuum.chappie",
        "manufacturer": "Beijing Roborock Technology Co., Ltd.",
        "model_id": "roborock.vacuum.a245",
        **A245_SIGNALS,
    }, {})


class EndToEndEstimateTests(unittest.TestCase):
    def test_issue_12_session_produces_a_labelled_number(self):
        device = a245_device()
        state = {"used_ml": 0, "initialized": True, "last_area": 30.0, "last_status": "charging",
                 "last_tick_ts": 9_940_000}
        ts = 10_000_000
        for status, area, vac in (("cleaning", 0, "cleaning"), ("cleaning", 5.0, "cleaning"),
                                  ("cleaning", 10.0, "cleaning"), ("washing_the_mop", 10.0, "docked"),
                                  ("charging", 10.0, "docked")):
            ts += 60_000
            state, _ = tick.tick_device(a245_hass(status, area, vac), device, state, now_ts=ts)
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertAlmostEqual(state["used_ml"], 10.0 * 10 + 200, places=1)
        result = estimate_water_state(device, state, {})
        self.assertEqual(result["source"], "stored_estimate")
        self.assertEqual(result["estimate_basis"], "class_prior")
        self.assertEqual(result["uncertainty_percent"], 50)
        self.assertEqual(result["remaining_ml"], 3700)
        self.assertEqual(state["automatic_sessions"][0]["water"], 300)


class CalibratorTests(unittest.TestCase):
    def _tank(self, device, state, predicted, ts):
        state = {**state, "used_ml": predicted, "water_empty_active": False, "last_dock_err": "ok",
                 "initialized": True, "last_status": "charging", "last_area": 10.0}
        state, _ = tick.tick_device(a245_hass("charging", 10.0, "docked", "water_empty"), device, state, now_ts=ts)
        state, _ = tick.tick_device(a245_hass("charging", 10.0, "docked", "ok"), device, state, now_ts=ts + 120_000)
        return state

    def test_median_calibration_outlier_gate_and_history(self):
        device = a245_device()
        state = {"calibration_factor": 1.0, "calibration_samples": 0}
        ts = 20_000_000
        for predicted in (3000, 3100, 2950):
            before = state.get("calibration_factor", 1.0)
            state = self._tank(device, state, predicted * before, ts)
            ts += 10_000_000
        self.assertEqual(state["calibration_samples"], 3)
        # Estimated dock tanks close at capacity minus the default 5% unusable residual.
        self.assertAlmostEqual(state["calibration_factor"], 3800 / 3000, delta=0.02)
        self.assertEqual(state["used_ml"], 0, "exact empty cleared to OK must be an automatic refill")
        self.assertTrue(state["calibration_history"][0]["accepted"])
        first_error = state["calibration_history"][-1]["error_percent"]
        self.assertAlmostEqual(first_error, (3000 - 3800) / 3800 * 100, delta=0.1)
        outlier = self._tank(device, state, 1300, ts)
        self.assertEqual(outlier["calibration_samples"], 3)
        self.assertFalse(outlier["calibration_history"][0]["accepted"])
        self.assertEqual(outlier["calibration_history"][0]["reason"], "calibration_sample_outlier")

    def test_incomplete_cycle_is_not_a_calibration_sample(self):
        device = a245_device()
        state = self._tank(device, {"accounting_incomplete": True}, 3000, 30_000_000)
        self.assertEqual(state.get("calibration_samples", 0), 0)
        self.assertEqual(state["calibration_history"][0]["reason"], "calibration_sample_incomplete_cycle")

    def test_uncertainty_shrinks_with_consistent_tanks(self):
        device = a245_device()
        uncalibrated = estimate_water_state(device, {"initialized": True, "used_ml": 100}, {})
        calibrated = estimate_water_state(device, {"initialized": True, "used_ml": 100,
                                                   "calibration_log_factors": [0.29, 0.28, 0.3]}, {})
        self.assertEqual(uncalibrated["uncertainty_percent"], 50)
        self.assertLess(calibrated["uncertainty_percent"], 10)

    def test_inferred_dock_contract_does_not_trust_robot_error_or_lid(self):
        device = {**a245_device(), "water_error_sensor": "sensor.robot_error", "reset_door_sensor": "binary_sensor.lid"}
        h = _Hass({"vacuum.chappie": _State("docked"), "sensor.robot_error": _State("water_tank_empty"),
                   "binary_sensor.lid": _State("off")})
        state, _ = tick.tick_device(h, device, {"initialized": True, "used_ml": 1000, "last_door": "on",
                                                "last_reset_ts": 0}, now_ts=40_000_000)
        self.assertEqual(state["used_ml"], 1000)



class AuthoredContractTests(unittest.TestCase):
    def test_explicit_anchor_contract_is_not_marked_inferred(self):
        effective = apply_custom_calibration({"vacuum_entity": "vacuum.s8", "profile_key": "roborock_s8_maxv_ultra",
                                              "water_anchor_reservoir": "dock_clean", "refill_on_clear": False}, {})
        self.assertNotIn("water_anchor_reservoir_inferred", effective)
        self.assertNotIn("refill_on_clear_inferred", effective)
        self.assertFalse(effective["refill_on_clear"])
        inferred = apply_custom_calibration({"vacuum_entity": "vacuum.s8", "profile_key": "roborock_s8_maxv_ultra"}, {})
        self.assertTrue(inferred["water_anchor_reservoir_inferred"])
        self.assertTrue(inferred["refill_on_clear_inferred"])


if __name__ == "__main__":
    unittest.main()
