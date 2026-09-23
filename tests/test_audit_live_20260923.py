"""Reproductions of defects seen on the live 5.7.0-beta.2 test (audit 2026-09-23).

Each test states the behaviour stable 5.7.0 must have. Tests marked
``expectedFailure`` reproduce a live defect in beta.2 and must pass (and lose
the marker) once it is fixed. Evidence: recorder history of 2026-09-19 on the
owner's S8 MaxV Ultra; see the audit note in the project vault.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import unittest

from test_beta_runtime_path import BASE, _S, descriptor, effective, hass, run, sc, tick

storage = importlib.import_module("vwmruntimepkg.storage")
ROOT = Path(__file__).resolve().parents[1]
S8 = effective({}, descriptor())


def run_persisted(device, stored, steps, ts=10_000_000, step=60_000):
    """Like the integration: each pass starts from the Store and is kept only when dirty."""
    for kwargs in steps:
        kwargs = dict(kwargs)
        ts += kwargs.pop("_gap", step)
        state = storage.VacuumWaterStorage.default_tank_state()
        state.update(stored)
        new_state, dirty = tick.tick_device(hass(**kwargs), device, state, now_ts=ts)
        if dirty:
            stored = new_state
    return stored


def final_wash_sequence():
    """The end of the 2026-09-19 run: one 4 min wash, bin emptying, a 2 s wash status flicker."""
    area = dict(area="20", intensity="extreme")
    return [
        dict(status="cleaning", vac="cleaning", **area),
        dict(status="returning_home", vac="returning", _gap=5_000, **area),
        dict(status="washing_the_mop", vac="docked", _gap=56_000, **area),   # t0: the real wash
        dict(status="washing_the_mop", vac="docked", _gap=60_000, **area),   # heartbeat
        dict(status="washing_the_mop", vac="docked", _gap=60_000, **area),   # heartbeat
        dict(status="washing_the_mop", vac="docked", _gap=60_000, **area),   # heartbeat
        dict(status="emptying_the_bin", vac="docked", _gap=56_000, **area),  # t0 + 236 s
        dict(status="emptying_the_bin", vac="docked", _gap=6_000, **area),   # heartbeat, t0 + 242 s
        dict(status="washing_the_mop", vac="docked", _gap=20_000, **area),   # 2 s flicker
        dict(status="charging", vac="docked", _gap=2_000, **area),
    ]


CLEANING_ON = {"binary_sensor.robot_cleaning": _S("on")}
S8_TASK_FLAG = {**S8, "cleaning_active_sensor": "binary_sensor.robot_cleaning"}


class WashSequenceTests(unittest.TestCase):
    def start(self, device):
        return run(device, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme", extra=CLEANING_ON),
                                        dict(status="cleaning", vac="cleaning", area="20", intensity="extreme", extra=CLEANING_ON)])

    def test_without_a_task_flag_the_flicker_is_not_a_second_wash(self):
        for runner in (run, run_persisted):
            with self.subTest(runner=runner.__name__):
                state = self.start(S8)
                before = state["used_ml"]
                state = runner(S8, state, final_wash_sequence())
                self.assertAlmostEqual(state["used_ml"] - before, 150, places=1)

    @unittest.expectedFailure
    def test_task_flag_on_at_the_dock_does_not_end_the_wash_sequence(self):
        # Live 2026-09-19 06:52-06:57: Roborock's binary_sensor.*_cleaning stays
        # "on" until the task ends, _is_cleaning() treats that as "resumed", the
        # sequence ends at emptying_the_bin and a 2 s washing_the_mop flicker is
        # charged as a second wash (+150 ml). Reproduced on recorded history.
        steps = [dict(s, extra=CLEANING_ON) for s in final_wash_sequence()[:-1]] + [final_wash_sequence()[-1]]
        state = self.start(S8_TASK_FLAG)
        before = state["used_ml"]
        state = run_persisted(S8_TASK_FLAG, state, steps)
        self.assertAlmostEqual(state["used_ml"] - before, 150, places=1)


class SessionHistoryTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_setting_change_during_a_run_keeps_the_session_water(self):
        # Live 2026-09-19 16:48: mop intensity changed while returning; the whole
        # session was stored with water=None and accounting_valid=False.
        steps = [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                 dict(status="returning_home", vac="returning", area="10", intensity="off"),
                 dict(status="charging", vac="docked", area="10", intensity="off")]
        state = run(S8, dict(BASE), steps)
        self.assertIsNotNone(state["automatic_sessions"][0]["water"])

    @unittest.expectedFailure
    def test_area_in_the_interval_of_a_setting_change_is_charged(self):
        state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="standard"),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity="standard")])
        before = state["used_ml"]
        state = run(S8, state, [dict(status="cleaning", vac="cleaning", area="14", intensity="extreme")], ts=10_200_000)
        self.assertGreater(state["used_ml"] - before, 0)


class CapacityTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_sensor_and_engine_use_one_capacity(self):
        # Live: the card stored water_total_ml 3000; sensors show 3000 while the
        # engine anchors calibration to the profile's tracked_capacity_ml 4000.
        settings = {"configured_devices": [{"vacuum_entity": "vacuum.robot", "water_total_ml": 3000}]}
        device = effective(settings, descriptor())
        self.assertEqual(sc._water_capacity_ml(device, settings), device.get("tracked_capacity_ml"))


class StoreWriteTests(unittest.TestCase):
    def test_idle_heartbeat_is_dirty_only_because_of_last_tick_ts(self):
        # Diagnosis, passes on beta.2. Live 2026-09-23: docked and charging, every
        # heartbeat pass is dirty and the heartbeat path saves the whole Store
        # (~35 KB) without delay: ~1440 writes a day. The fix belongs in the save
        # policy (tick-timestamp-only passes -> delayed save), not in dropping
        # last_tick_ts, which gap detection needs.
        state = run(S8, dict(BASE), [dict(status="charging", vac="docked", area="0")] * 3)
        new_state, dirty = tick.tick_device(hass(status="charging", vac="docked", area="0"), S8,
                                            dict(state), now_ts=10_300_000)
        changed = {k for k in set(state) | set(new_state) if state.get(k) != new_state.get(k)}
        self.assertTrue(dirty)
        self.assertEqual(changed, {"last_tick_ts"})


class ShadowReplayToolTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_history_request_has_an_end_time(self):
        # Without end_time HA returns one day from start, so --days N replays 24 h.
        source = (ROOT / "scripts" / "shadow_capture.py").read_text(encoding="utf-8")
        self.assertIn("end_time", source)


if __name__ == "__main__":
    unittest.main()
