"""Issue 26: reported identity and catalog capacities do not invent doses."""
import unittest
from test_beta_runtime_path import _Hass, _S, discovery, effective, sc, tick, descriptor


class Issue26Tests(unittest.TestCase):
    def test_discovery_to_balance_uses_no_implicit_rate(self):
        entities = [
            {"entity_id": "vacuum.eco", "platform": "ecovacs", "device_id": "one"},
            {"entity_id": "sensor.area", "platform": "ecovacs", "device_id": "one", "translation_key": "stats_area"},
            {"entity_id": "select.mode", "platform": "ecovacs", "device_id": "one", "translation_key": "work_mode"},
        ]
        device = {"id": "one", "manufacturer": "Ecovacs", "model_id": "k2iwaq", "sw_version": "1.103.0"}
        desc = discovery.discover_descriptors(entities, [device], {})[0]
        self.assertEqual(desc["profile_key"], "ecovacs_deebot_t90_pro_omni")
        eff = effective({}, desc)
        self.assertEqual(eff["tracked_capacity_ml"], 4000)
        self.assertEqual(eff["reservoirs_ml"]["dock_dirty"], 2200)
        self.assertFalse(eff.get("usage_ml_per_m2"))
        self.assertFalse(eff.get("usage_ml_per_active_minute"))
        self.assertIsNone(eff.get("wash_volume_ml"))
        self.assertFalse(eff.get("refill_on_clear"))
        self.assertIsNone(eff.get("water_anchor_reservoir"))
        state, _ = tick.tick_device(_Hass({"vacuum.eco": _S("cleaning"),
            "sensor.area": _S("12", {"unit_of_measurement": "m²"}),
            "select.mode": _S("vacuum_and_mop")}), eff,
            {"initialized": True, "used_ml": 100, "last_area": 10,
             "last_status": "cleaning", "last_tick_ts": 1000000, "last_reset_ts": 900000}, now_ts=1060000)
        self.assertEqual(state["used_ml"], 100)
        self.assertIsNone(sc.estimate_water_state(eff, state, {})["remaining_ml"])
        self.assertTrue(effective({}, descriptor())["usage_ml_per_m2"])

    def test_explicit_user_rate_survives(self):
        desc = discovery.discover_descriptors(
            [{"entity_id": "vacuum.eco", "platform": "ecovacs", "device_id": "one"}],
            [{"id": "one", "manufacturer": "Ecovacs", "model_id": "k2iwaq"}], {})[0]
        cfg = {"vacuum_entity": "vacuum.eco", "usage_ml_per_m2": {"default": 2},
               "config_provenance": {"authored_fields": ["vacuum_entity", "usage_ml_per_m2"]}}
        self.assertEqual(effective({"configured_devices": [cfg]}, desc)["usage_ml_per_m2"]["default"], 2)

    def test_foreign_manufacturer_does_not_claim_id(self):
        d = discovery.discover_descriptors(
            [{"entity_id": "vacuum.other", "platform": "ecovacs", "device_id": "other"}],
            [{"id": "other", "manufacturer": "Unrelated vendor", "model_id": "k2iwaq"}], {})[0]
        self.assertIsNone(d["profile_key"])
