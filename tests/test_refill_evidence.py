"""5.13.0: refill confirmation from several physical signals.

The sequences replay the Roborock S8 MaxV Ultra dock observed on 14.11 and
19.11.2026 (lid contact sensor plus the dock's clean/dirty tank-box binary
sensors, polled about every 30 s): the user lifts the lid, takes the clean tank
out, fills it to MAX and puts it back. Before 5.13.0 such a refill stayed
"full unconfirmed" and every calibration sample of the cycle was rejected.
"""

from __future__ import annotations

import importlib
import unittest

from test_beta_runtime_path import BASE, SIGNALS, _S, descriptor, effective, run

refill = importlib.import_module("vwmruntimepkg.refill")

LID = "binary_sensor.roborock_door_sensor"
CLEAN = "binary_sensor.robot_dock_clean_water_box"
DIRTY = "binary_sensor.robot_dock_dirty_water_box"
DOCK_SIGNALS = {**SIGNALS, CLEAN: "clean_box_empty", DIRTY: "dirty_box_full"}


def device(lid=True, boxes=True, **refill_settings):
    settings = {}
    if lid:
        refill_settings = {"lid_entity": LID, **refill_settings}
    if refill_settings:
        settings["refill_settings"] = {"vacuum.robot": refill_settings}
    return effective(settings, descriptor(signals=DOCK_SIGNALS if boxes else SIGNALS))


def step(lid="off", clean="off", dirty="off", gap=None, **kwargs):
    extra = {LID: _S(lid), CLEAN: _S(clean), DIRTY: _S(dirty)}
    result = dict(extra=extra, **kwargs)
    if gap is not None:
        result["_gap"] = gap
    return result


# 19.11 01:20:03 dirty on, :30 lid on, :34 dirty off + clean on, :55 lid off, 01:21:05 clean off.
REFILL_19_11 = [
    step(),
    step(dirty="on", gap=3_000),
    step(lid="on", dirty="on", gap=27_000),
    step(lid="on", clean="on", gap=4_000),
    step(clean="on", gap=21_000),
    step(gap=10_000),
]
# Lid opened only to empty the dirty tank: the clean tank never left the dock.
DIRTY_ONLY = [
    step(),
    step(dirty="on", gap=3_000),
    step(lid="on", dirty="on", gap=20_000),
    step(lid="on", gap=30_000),
    step(gap=20_000),
    step(gap=60_000),
    step(gap=60_000),
    step(gap=60_000),
]


class DockedLidRefillTests(unittest.TestCase):
    def test_device_binds_dock_tank_boxes(self):
        dev = device()
        self.assertEqual(dev.get("dock_clean_water_sensor"), CLEAN)
        self.assertEqual(dev.get("dock_dirty_water_sensor"), DIRTY)
        self.assertEqual(dev.get("reset_door_sensor"), LID)

    def test_observed_refill_with_tank_out_confirms_a_full_tank(self):
        state = run(device(), {**BASE, "used_ml": 1156.2}, REFILL_19_11)
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "lid")
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertFalse(state["refill_full_unconfirmed"])
        self.assertEqual(state["cycle_full_confirmation_source"], "lid_and_clean_tank_removed")
        record = state["refill_history"][0]
        self.assertEqual(record["evidence"], ["clean_tank_removed", "lid"])
        self.assertTrue(record["full_confirmed"])
        self.assertEqual(len(state["refill_history"]), 1)

    def test_clean_tank_reported_back_before_the_lid_closes(self):
        state = run(device(), {**BASE, "used_ml": 2665.3}, [
            step(), step(lid="on", gap=15_000), step(lid="on", clean="on", gap=16_000),
            step(lid="on", gap=29_000), step(gap=1_000)])
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertEqual(state["used_ml"], 0)

    def test_dirty_tank_service_is_not_a_clean_water_refill(self):
        state = run(device(), {**BASE, "used_ml": 475.7, "cycle_full_confirmed": True}, DIRTY_ONLY)
        self.assertEqual(state["used_ml"], 475.7)
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertNotIn("refill_history", state)
        self.assertNotIn("pending_lid_close_ts", state)

    def test_lid_without_any_tank_signal_stays_an_unconfirmed_refill(self):
        state = run(device(), {**BASE, "used_ml": 900},
                    [step(), step(lid="on", gap=10_000), step(gap=20_000), step(gap=60_000), step(gap=60_000),
                     step(gap=60_000)])
        self.assertEqual(state["used_ml"], 0)
        self.assertTrue(state["refill_full_unconfirmed"])
        self.assertFalse(state["cycle_full_confirmed"])

    def test_declared_full_refill_practice_still_confirms_a_plain_lid(self):
        state = run(device(full_refill_practice_confirmed=True), {**BASE, "used_ml": 900},
                    [step(), step(lid="on", gap=10_000), step(gap=20_000), step(gap=180_000)])
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertEqual(state["cycle_full_confirmation_source"], "declared_full_refill_practice")

    def test_lid_refill_after_the_empty_alarm_confirms_a_full_tank(self):
        dev = device(boxes=False)
        state = run(dev, {**BASE, "used_ml": 3700, "cycle_full_confirmed": True}, [
            dict(dock_err="water_empty", extra={LID: _S("off")}),
            dict(dock_err="water_empty", extra={LID: _S("off")}),
            dict(dock_err="water_empty", extra={LID: _S("on")}),
            dict(dock_err="water_empty", extra={LID: _S("off")}),
        ])
        self.assertEqual(state["used_ml"], 0)
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertEqual(state["cycle_full_confirmation_source"], "refill_after_empty")


class TankReinsertedWithoutLidTests(unittest.TestCase):
    def test_tank_out_and_back_while_idle_is_a_refill(self):
        state = run(device(lid=False), {**BASE, "used_ml": 1800}, [
            step(), step(clean="on", gap=20_000), step(clean="on", gap=30_000), step(gap=30_000)])
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "tank_reinserted")
        # Taking the tank out alone does not prove it went back full.
        self.assertTrue(state["refill_full_unconfirmed"])

    def test_tank_out_during_a_mop_wash_is_not_a_refill(self):
        washing = dict(status="washing_the_mop", vac="docked")
        state = run(device(lid=False), {**BASE, "used_ml": 1800, "last_status": "washing_the_mop"}, [
            step(**washing), step(clean="on", gap=20_000, **washing), step(gap=30_000, **washing)])
        self.assertNotEqual(state.get("last_reset_source"), "tank_reinserted")


class DocklessRobotTankTests(unittest.TestCase):
    BOX = "binary_sensor.robot_water_box_attached"

    def _device(self, reservoir):
        dev = dict(device(lid=False, boxes=False))
        dev.update(tracked_reservoir=reservoir, water_box_attached_sensor=self.BOX)
        return dev

    def _steps(self, *values):
        return [dict(extra={self.BOX: _S(v)}, _gap=30_000) for v in values]

    def test_robot_tank_out_and_back_refills_a_dockless_robot(self):
        state = run(self._device("robot_clean"), {**BASE, "used_ml": 180}, self._steps("on", "off", "off", "on"))
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "tank_reinserted")

    def test_after_the_tank_was_reported_empty_it_confirms_a_full_tank(self):
        state = run(self._device("robot_clean"), {**BASE, "used_ml": 180, "user_empty_active": True,
                                                  "water_empty_active": True, "water_anchor_source": "user_empty",
                                                  "water_anchor_kind": "empty"}, self._steps("on", "off", "on"))
        self.assertTrue(state["cycle_full_confirmed"])

    def test_dock_robots_ignore_their_onboard_tank(self):
        state = run(self._device("dock_clean"), {**BASE, "used_ml": 180}, self._steps("on", "off", "on"))
        self.assertEqual(state["used_ml"], 180)


class DecisionTests(unittest.TestCase):
    def test_single_automatic_signal_is_not_full(self):
        for source in ("lid", "dock_cleared", "tank_reinserted"):
            self.assertEqual(refill.full_refill_decision({}, source), (False, None), source)

    def test_second_signal_of_the_same_refill_confirms_it(self):
        state = {"used_ml": 0, "refill_full_unconfirmed": True, "last_reset_source": "lid",
                 "refill_history": [{"ts": 1, "source": "lid", "evidence": ["lid"]}]}
        self.assertTrue(refill.confirm_same_refill(state, "tank_reinserted"))
        self.assertTrue(state["cycle_full_confirmed"])
        self.assertEqual(state["refill_history"][0]["full_reason"], "lid_and_clean_tank_removed")

    def test_history_record_is_replaced_not_mutated(self):
        record = {"ts": 1, "source": "lid", "evidence": ["lid"]}
        state = {"refill_full_unconfirmed": True, "last_reset_source": "lid", "refill_history": [record]}
        refill.confirm_same_refill(state, "dock_cleared")
        self.assertEqual(record, {"ts": 1, "source": "lid", "evidence": ["lid"]})


if __name__ == "__main__":
    unittest.main()
