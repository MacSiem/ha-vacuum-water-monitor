"""5.8.0: one source for the tank size, and one health report per robot.

The report drives the card's setup wizard, the "Is everything working?" panel
and Home Assistant Repairs, so these tests pin what a new user sees.
"""

from __future__ import annotations

import importlib
import math
import unittest

from test_beta_runtime_path import BASE, descriptor, discovery, effective, run, sc

health = importlib.import_module("vwmruntimepkg.health")
options = importlib.import_module("vwmruntimepkg.device_options")

S8 = "vacuum.robot"


def report(settings=None, tank=None, desc=None, **kwargs):
    settings = settings or {}
    desc = desc or descriptor()
    device = sc.build_vacuum_devices(settings, {}, [desc])[0]
    eff = sc.apply_custom_calibration(device, settings)
    state = {"initialized": False, **(tank or {})}
    estimate = sc.estimate_water_state(device, state, settings)
    _cap, source = sc.water_capacity(device, settings)
    return health.robot_health(device, eff, state, estimate, capacity_source=source,
                               model_capacity_ml=sc._model_tank_ml(device), **kwargs)


def ids(result):
    return [check["id"] for check in result["checks"]]


class TankSizeOptionTests(unittest.TestCase):
    def test_option_wins_over_card_and_model_and_drives_the_engine(self):
        card = {"vacuum_entity": S8, "water_total_ml": 4000,
                "config_provenance": {"authored_fields": ["vacuum_entity", "water_total_ml"]}}
        settings = {"configured_devices": [card], "device_options": {S8: {"capacity_ml": 3000}}}
        device = sc.build_vacuum_devices(settings, {}, [descriptor()])[0]
        self.assertEqual(sc.water_capacity(device, settings), (3000.0, "user_option"))
        self.assertEqual(effective(settings, descriptor())["tracked_capacity_ml"], 3000.0)
        self.assertEqual(sc.estimate_water_state(device, {"initialized": True, "used_ml": 1500}, settings)["remaining_percent"], 50)

    def test_without_option_the_card_then_the_model_decide(self):
        card = {"vacuum_entity": S8, "water_total_ml": 3500,
                "config_provenance": {"authored_fields": ["vacuum_entity", "water_total_ml"]}}
        device = sc.build_vacuum_devices({"configured_devices": [card]}, {}, [descriptor()])[0]
        self.assertEqual(sc.water_capacity(device, {}), (3500.0, "card"))
        device = sc.build_vacuum_devices({}, {}, [descriptor()])[0]
        capacity, source = sc.water_capacity(device, {})
        self.assertEqual(source, "model")
        self.assertGreater(capacity, 0)

    def test_the_dock_anchor_and_auto_refill_survive_a_custom_size(self):
        device = effective({"device_options": {S8: {"capacity_ml": 3000}}}, descriptor())
        self.assertTrue(device.get("refill_on_clear"))
        self.assertEqual(health.refill_method(device), "dock_auto")

    def test_option_validation(self):
        for bad in (True, "abc", float("nan"), 50, 20000):
            with self.assertRaises(ValueError):
                options.merge_options({}, {"capacity_ml": bad})
        self.assertEqual(options.merge_options({"capacity_ml": 3000}, {"capacity_ml": None}), {})
        self.assertEqual(options.merge_options({}, {"capacity_ml": "2750"}), {"capacity_ml": 2750.0})
        with self.assertRaises(ValueError):
            options.merge_options({}, {"colour": "red"})

    def test_a_broken_stored_option_is_ignored_not_fatal(self):
        settings = {"device_options": {S8: {"capacity_ml": "garbage"}}}
        device = sc.build_vacuum_devices(settings, {}, [descriptor()])[0]
        self.assertEqual(sc.water_capacity(device, settings)[1], "model")

    def test_anchor_target_follows_the_option(self):
        device = effective({"device_options": {S8: {"capacity_ml": 3000}}}, descriptor())
        state = run(device, {**BASE, "used_ml": 2400}, [dict(dock_err="water_empty")] * 3)
        # The empty tank closes at the usable volume of the chosen size (5% residual).
        self.assertTrue(math.isclose(state["used_ml"], 2850, abs_tol=1))


class HealthReportTests(unittest.TestCase):
    def test_new_s8_asks_one_question(self):
        result = report()
        self.assertEqual(result["status"], "action_needed")
        self.assertEqual(ids(result)[0], "awaiting_refill")
        first = result["checks"][0]
        self.assertEqual((first["fix"], first["repair"], first["params"]["auto_refill"]), ("confirm_full", True, True))
        self.assertEqual(result["refill_method"], "dock_auto")
        self.assertTrue(result["auto_refill_supported"])
        self.assertTrue(result["can_calibrate"])
        self.assertEqual(result["capacity_source"], "model")
        self.assertIsNotNone(result["uncertainty_percent"])

    def test_initialized_s8_is_ok(self):
        result = report(tank={"initialized": True, "used_ml": 100})
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c for c in result["checks"] if c["severity"] != "info"], [])

    def test_paused_count_asks_for_a_full_tank(self):
        result = report(tank={"initialized": True, "accounting_incomplete": True})
        self.assertEqual(ids(result)[0], "accounting_paused")

    def test_auto_refill_off_and_no_button_means_manual(self):
        result = report(settings={"refill_settings": {S8: {"auto_refill": False}}}, tank={"initialized": True})
        self.assertEqual(result["refill_method"], "manual")
        self.assertIn("manual_refill", ids(result))
        self.assertTrue(result["auto_refill_supported"])
        self.assertFalse(result["auto_refill"])
        self.assertEqual(result["status"], "ok")

    def test_unknown_model_with_a_mop_signal_needs_a_tank_size(self):
        desc = descriptor(model_id="zz999")
        result = report(desc=desc, tank={"initialized": True})
        self.assertIsNone(result["capacity_ml"])
        self.assertEqual(ids(result)[0], "unknown_capacity")
        self.assertEqual((result["checks"][0]["severity"], result["checks"][0]["fix"]), ("error", "set_capacity"))
        fixed = report(settings={"device_options": {S8: {"capacity_ml": 2500}}}, desc=desc, tank={"initialized": True})
        self.assertEqual((fixed["capacity_ml"], fixed["capacity_source"]), (2500, "user_option"))
        self.assertNotIn("unknown_capacity", ids(fixed))

    def test_robot_without_mop_or_tank_is_not_nagged(self):
        entities = [{"entity_id": "vacuum.plain", "platform": "xiaomi_miio", "device_id": "d9"}]
        devices = [{"id": "d9", "manufacturer": "Acme", "model": "sweeper-1"}]
        desc = discovery.discover_descriptors(entities, devices, {"vacuum.plain": {"state": "docked", "attributes": {}}})[0]
        result = report(desc=desc)
        self.assertEqual(ids(result), ["not_tracked"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(any(check["repair"] for check in result["checks"]))

    def test_adapter_attribute_names_alone_do_not_mean_a_mop(self):
        """5.8.0 review: Roomba maps water-box attributes even on sweep-only models."""
        entities = [{"entity_id": "vacuum.plain", "platform": "roomba", "device_id": "d9"}]
        devices = [{"id": "d9", "manufacturer": "iRobot", "model": "Roomba 980"}]
        desc = discovery.discover_descriptors(entities, devices, {"vacuum.plain": {"state": "docked", "attributes": {}}})[0]
        result = report(desc=desc)
        self.assertFalse(any(check["repair"] for check in result["checks"]), result["checks"])
        present = report(desc=desc, mop_attribute_present=True)
        self.assertTrue(present["tracks_water"])

    def test_suspected_duplicate_raises_only_that_question(self):
        result = report(duplicate_of="vacuum.s8", duplicate_of_name="S8")
        self.assertEqual(ids(result), ["possible_duplicate"])
        self.assertEqual(result["checks"][0]["params"], {"target": "vacuum.s8", "target_name": "S8"})

    def test_checks_are_ordered_by_severity(self):
        desc = descriptor(model_id="zz999")
        result = report(desc=desc)
        order = [check["severity"] for check in result["checks"]]
        self.assertEqual(order, sorted(order, key={"error": 0, "warning": 1, "info": 2}.get))


if __name__ == "__main__":
    unittest.main()


class IdleOffDockSessionTests(unittest.TestCase):
    """The task flag stays on while the robot waits off the dock (5.7 known limitation)."""

    def setUp(self):
        from test_beta_runtime_path import SIGNALS, _S
        signals = dict(SIGNALS)
        signals["binary_sensor.robot_in_cleaning"] = "in_cleaning"
        self.device = effective({}, descriptor(signals=signals))
        self.assertEqual(self.device.get("cleaning_active_sensor"), "binary_sensor.robot_in_cleaning")
        self.flag = {"binary_sensor.robot_in_cleaning": _S("on")}

    def step(self, status, vac, area, gap=60_000):
        return dict(status=status, vac=vac, area=str(area), extra=self.flag, _gap=gap)

    def test_a_run_paused_off_the_dock_is_closed_after_twenty_minutes(self):
        start = [self.step("cleaning", "cleaning", a) for a in (0, 5, 10)]
        paused = [self.step("paused", "idle", 10, gap=5 * 60_000) for _ in range(6)]
        state = run(self.device, dict(BASE), start + paused)
        sessions = state.get("automatic_sessions") or []
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(state.get("session_start_ts"))
        self.assertEqual(sessions[0]["area"], 10)
        # The run ends when the pause was first seen (7 min), not 20 min later.
        self.assertEqual(sessions[0]["duration"], 7.0)
        # Still paused with the flag on: no new run is opened.
        state = run(self.device, state, [self.step("paused", "idle", 10)])
        self.assertIsNone(state.get("session_start_ts"))
        # Cleaning again opens a new run that starts where the robot paused.
        state = run(self.device, state, [self.step("cleaning", "cleaning", 12)])
        self.assertIsNotNone(state.get("session_start_ts"))
        self.assertEqual(state.get("session_start_area"), 10)

    def test_a_short_pause_keeps_one_run(self):
        steps = ([self.step("cleaning", "cleaning", a) for a in (0, 5)] + [self.step("paused", "idle", 5, gap=5 * 60_000)]
                 + [self.step("cleaning", "cleaning", a) for a in (8, 12)] + [self.step("charging", "docked", 12)])
        state = run(self.device, dict(BASE), steps)
        self.assertEqual(state.get("session_idle_since_ts"), None)
        self.assertIsNotNone(state.get("session_start_ts"))  # the task flag keeps the run open at the dock

    def test_recharge_at_the_dock_mid_task_is_not_idle(self):
        steps = [self.step("cleaning", "cleaning", a) for a in (0, 5)] + [
            self.step("charging", "docked", 5, gap=15 * 60_000) for _ in range(4)]
        state = run(self.device, dict(BASE), steps)
        self.assertIsNotNone(state.get("session_start_ts"))
        self.assertFalse(state.get("automatic_sessions"))
