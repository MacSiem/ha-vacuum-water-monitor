"""Real Tapo/Matter profile: no invented dose and no misleading refill fix."""
import importlib
import unittest

from test_beta_runtime_path import _Hass, _S, discovery, effective, sc, tick

health = importlib.import_module("vwmruntimepkg.health")


class MatterMissingRateTests(unittest.TestCase):
    def test_actual_profile_reports_missing_rate_instead_of_a_refill(self):
        entities = [
            {"entity_id": "vacuum.robot", "platform": "matter", "device_id": "test", "unique_id": "vac"},
            {"entity_id": "sensor.status", "platform": "matter", "device_id": "test", "unique_id": "status", "translation_key": "operational_state"},
            {"entity_id": "select.mode", "platform": "matter", "device_id": "test", "unique_id": "mode", "translation_key": "clean_mode"},
        ]
        desc = discovery.discover_descriptors(entities, [
            {"id": "test", "manufacturer": "Tapo", "model": "RV50 Pro Omni (1797)", "model_id": "1797"}
        ], {})[0]
        device = sc.build_vacuum_devices({}, {}, [desc])[0]
        eff = effective({}, desc)
        self.assertEqual(desc["profile_key"], "tapo_rv50_pro_omni")
        self.assertEqual(eff.get("usage_ml_per_active_minute"), {})
        state, _ = tick.tick_device(_Hass({
            "vacuum.robot": _S("cleaning"), "sensor.status": _S("running"),
            "select.mode": _S("Vacuum and Mop;Deep Clean"),
        }), eff, {"initialized": True, "used_ml": 100, "last_tick_ts": 1000000,
                  "last_status": "running", "last_reset_ts": 900000}, now_ts=1060000)
        self.assertEqual(state["used_ml"], 100)
        self.assertEqual(state["last_accounting_reason"], "missing_time_rate")
        estimate = sc.estimate_water_state(device, state, {})
        self.assertIsNone(estimate["remaining_ml"])
        report = health.robot_health(device, eff, state, estimate)
        checks = {c["id"]: c for c in report["checks"]}
        self.assertIn("missing_usage_rate", checks)
        self.assertEqual(checks["missing_usage_rate"]["params"]["reason"], "missing_time_rate")
        self.assertFalse(checks["missing_usage_rate"]["repair"])
        self.assertFalse(any(c["fix"] == "confirm_full" for c in checks.values()))
        self.assertNotIn("no_empty_signal", checks)

    def test_missing_rate_is_distinct_from_an_incomplete_balance(self):
        for reason in ("missing_time_rate", "missing_area_rate", "missing_wash_rate", "missing_intensity_factor"):
            with self.subTest(reason=reason):
                result = health.robot_health({"vacuum_entity": "vacuum.robot"}, {},
                    {"last_accounting_reason": reason},
                    {"total_ml": 3000, "initialized": True, "state_reason": "accounting_incomplete"})
                self.assertEqual(result["checks"][0]["id"], "missing_usage_rate")
                self.assertEqual(result["status"], "action_needed")
                self.assertFalse(any(c["fix"] == "confirm_full" for c in result["checks"]))

