"""Reproductions of defects seen on the live 5.7.0-beta.2 test (audit 2026-09-23).

Each test states the behaviour stable 5.7.0 must have. They reproduced live
defects of beta.2 as expected failures (commit ea97ee8) and pass since beta.3. Evidence: recorder history of 2026-09-19 on the
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
    def test_setting_change_during_a_run_keeps_the_session_water(self):
        # Live 2026-09-19 16:48: mop intensity changed while returning; the whole
        # session was stored with water=None and accounting_valid=False.
        steps = [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                 dict(status="returning_home", vac="returning", area="10", intensity="off"),
                 dict(status="charging", vac="docked", area="10", intensity="off")]
        state = run(S8, dict(BASE), steps)
        self.assertIsNotNone(state["automatic_sessions"][0]["water"])

    def test_refill_during_a_run_keeps_the_whole_run_in_history(self):
        # Live 2026-09-19 06:14: Refilled pressed mid-run; the session lost its water.
        refill = importlib.import_module("vwmruntimepkg.refill")
        state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity="extreme")])
        refill.apply_refill(state, 10_130_000, "card", rebaseline=True)
        state = run(S8, state, [dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                                dict(status="cleaning", vac="cleaning", area="20", intensity="extreme"),
                                dict(status="charging", vac="docked", area="20", intensity="extreme")], ts=10_140_000)
        session = state["automatic_sessions"][0]
        self.assertAlmostEqual(session["water"], 180, places=1)  # 20 m2 x 6 x 1.5
        self.assertFalse(session["accounting_valid"])  # not a clean measurement for calibration

    def test_a_broken_count_still_leaves_the_water_unknown(self):
        steps = [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="2", intensity="extreme"),  # counter reset mid-run
                 dict(status="charging", vac="docked", area="2", intensity="extreme")]
        state = run(S8, dict(BASE), steps)
        self.assertIsNone(state["automatic_sessions"][0]["water"])


class TaskRestartInsideSessionTests(unittest.TestCase):
    """Live 2026-09-23 15:20: after bumper_stuck the robot resumed as a new task and
    cleaning_area restarted 23.4 -> 0 inside one session."""

    def test_area_counter_restart_keeps_the_whole_run(self):
        steps = [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="0.2", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="5", intensity="extreme"),
                 dict(status="charging", vac="docked", area="5", intensity="extreme")]
        state = run(S8, dict(BASE), steps)
        session = state["automatic_sessions"][0]
        self.assertAlmostEqual(session["area"], 15, places=1)
        self.assertAlmostEqual(session["water"], 15 * 9, places=1)
        self.assertAlmostEqual(state["used_ml"], 15 * 9, places=1)

    def test_a_large_drop_to_a_non_zero_value_is_still_a_counter_anomaly(self):
        steps = [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                 dict(status="cleaning", vac="cleaning", area="2", intensity="extreme"),
                 dict(status="charging", vac="docked", area="2", intensity="extreme")]
        state = run(S8, dict(BASE), steps)
        self.assertIsNone(state["automatic_sessions"][0]["water"])


class CapacityTests(unittest.TestCase):
    def test_sensor_and_engine_use_one_capacity(self):
        # Live: the card stored water_total_ml 3000; sensors showed 3000 while the
        # engine anchored calibration to the profile's tracked_capacity_ml 4000.
        settings = {"configured_devices": [{"vacuum_entity": "vacuum.robot", "water_total_ml": 3000}]}
        device = effective(settings, descriptor())
        self.assertEqual(sc._water_capacity_ml(device, settings), 3000)
        self.assertEqual(device.get("tracked_capacity_ml"), 3000)
        # the user's tank size keeps the dock anchor and automatic refill
        self.assertTrue(device.get("refill_on_clear"))
        self.assertEqual(device.get("water_anchor_reservoir"), "dock_clean")

    def test_without_a_card_capacity_both_use_the_model_tank(self):
        device = effective({}, descriptor())
        self.assertEqual(sc._water_capacity_ml(device, {}), device.get("tracked_capacity_ml"))


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


class TickOnlyPersistenceTests(unittest.TestCase):
    def test_tick_timestamp_only_pass_is_detected(self):
        state = run(S8, dict(BASE), [dict(status="charging", vac="docked", area="0")] * 3)
        before = dict(state)
        after, _ = tick.tick_device(hass(status="charging", vac="docked", area="0"), S8, dict(state), now_ts=10_300_000)
        self.assertTrue(tick._only_tick_timestamp_changed(before, after))
        after["used_ml"] = 1
        self.assertFalse(tick._only_tick_timestamp_changed(before, after))

    def test_store_keeps_a_tick_only_pass_in_memory_without_writing(self):
        import asyncio

        class Store:
            saves = 0

            async def async_load(self):
                return None

            async def async_save(self, data):
                Store.saves += 1

        async def go():
            st = storage.VacuumWaterStorage(None)
            st._store = Store()
            await st.async_set_tank_states({"vacuum.a": {"used_ml": 1, "last_tick_ts": 5}}, persist=False)
            state = await st.async_get_state()
            return state["tank_states"]["vacuum.a"]["last_tick_ts"], Store.saves

        self.assertEqual(asyncio.run(go()), (5, 0))


class RegistryDevicesTests(unittest.TestCase):
    def test_entries_and_legacy_ids_are_both_resolved(self):
        discovery = importlib.import_module("vwmruntimepkg.discovery")

        class Modern:
            devices = ["entry-a", "entry-b"]

        entry = object()

        class Legacy:
            devices = {"d1": entry}

            def async_get(self, device_id):
                return self.devices.get(device_id)

        modern = Modern()
        modern.devices = [entry]
        self.assertEqual(discovery._registry_devices(modern), [entry])
        self.assertEqual(discovery._registry_devices(Legacy()), [entry])
        self.assertEqual(discovery._registry_devices(object()), [])


class DoubleRefillReportTests(unittest.TestCase):
    """Live 2026-09-19 06:14:04 and 06:14:44: Refilled pressed twice during a run."""

    def run_resets(self, second_after_ms):
        import asyncio

        async def go():
            st = storage.VacuumWaterStorage(None)
            await st.async_set_tank_state("vacuum.a", {"used_ml": 2296, "initialized": True, "last_reset_ts": 1})
            await st.async_reset_tank("vacuum.a", "2026-09-19T06:14:04Z", 1_000_000, "card")
            state = await st.async_get_state()
            state["tank_states"]["vacuum.a"]["used_ml"] = 7.2
            await st.async_set_tank_state("vacuum.a", state["tank_states"]["vacuum.a"])
            return await st.async_reset_tank("vacuum.a", "2026-09-19T06:14:44Z", 1_000_000 + second_after_ms, "card")

        return asyncio.run(go())

    def test_second_press_within_ten_minutes_is_the_same_refill(self):
        state = self.run_resets(40_000)
        self.assertEqual(state["used_ml"], 7.2)
        self.assertEqual(len(state["refill_history"]), 1)

    def test_a_later_press_is_a_new_refill(self):
        state = self.run_resets(601_000)
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(len(state["refill_history"]), 2)


class DisplayNameTests(unittest.TestCase):
    def test_registry_device_name_when_the_state_is_not_loaded_yet(self):
        discovery = importlib.import_module("vwmruntimepkg.discovery")
        entities = [{"entity_id": "vacuum.robotic_vacuum_cleaner", "platform": "matter", "device_id": "d1",
                     "original_name": None}]
        devices = [{"id": "d1", "manufacturer": "Roborock", "model": "Robotic Vacuum Cleaner",
                    "name": "Robotic Vacuum Cleaner", "name_by_user": None}]
        descriptor = discovery.discover_descriptors(entities, devices, {})[0]
        self.assertEqual(descriptor["name"], "Robotic Vacuum Cleaner")


class EventPayloadTests(unittest.TestCase):
    """Live 2026-09-23: 'Event data for ha_vacuum_water_monitor_state_changed exceed maximum size of 32768 bytes'."""

    def test_event_keeps_the_balance_and_drops_the_history(self):
        import json
        const = importlib.import_module("vwmruntimepkg.const")
        tank = {"used_ml": 12.5, "initialized": True, "last_reset_ts": 5,
                "automatic_sessions": [{"context": {"pad": "x" * 600}} for _ in range(50)],
                "refill_history": [{"ts": 1}] * 20, "session_context": {"a": 1}, "consumption_resolution": {"b": 2}}
        event = const.event_tank_states({"vacuum.a": tank})
        self.assertEqual(event["vacuum.a"]["used_ml"], 12.5)
        self.assertNotIn("automatic_sessions", event["vacuum.a"])
        self.assertLess(len(json.dumps(event)), 2_000)
        self.assertIn("automatic_sessions", tank)  # the stored state is untouched

    def test_the_card_reloads_history_when_a_refill_or_run_moves_it(self):
        card = (ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js").read_text(encoding="utf-8")
        self.assertIn("if (historyMoved) setTimeout(() => this._ensureServerState(true), 0);", card)

    def test_the_card_merges_partial_events_per_vacuum(self):
        card = (ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js").read_text(encoding="utf-8")
        self.assertIn("data.partial ? { ...(merged[vacuum] || {}), ...tank } : tank", card)


class EmptyTankTests(unittest.TestCase):
    """Live 2026-09-23 20:13: after the dock reported water_empty the robot washed its
    mop once more and 140 ml were added to a tank that had none left."""

    def empty(self):
        state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity="extreme",
                                          dock_err="water_empty"),
                                     dict(status="cleaning", vac="cleaning", area="10", intensity="extreme",
                                          dock_err="water_empty", _gap=70_000)])
        self.assertTrue(state["water_empty_active"])
        return state

    def test_no_water_is_counted_while_the_tank_is_empty(self):
        state = self.empty()
        before = state["used_ml"]
        state = run(S8, state, [dict(status="cleaning", vac="cleaning", area="14", intensity="extreme", dock_err="water_empty"),
                                dict(status="washing_the_mop", vac="docked", area="14", intensity="extreme", dock_err="water_empty")],
                    ts=10_600_000)
        self.assertEqual(state["used_ml"], before)
        self.assertEqual(state["last_accounting_reason"], "tank_empty_no_draw")

    def test_a_user_refill_during_the_error_counts_again(self):
        refill = importlib.import_module("vwmruntimepkg.refill")
        state = self.empty()
        refill.apply_refill(state, 10_500_000, "card", rebaseline=True)
        state = run(S8, state, [dict(status="cleaning", vac="cleaning", area="10", intensity="extreme", dock_err="water_empty"),
                                dict(status="cleaning", vac="cleaning", area="14", intensity="extreme", dock_err="water_empty")],
                    ts=10_600_000)
        self.assertAlmostEqual(state["used_ml"], 4 * 9, places=1)


class AnchorInsideSessionTests(unittest.TestCase):
    def test_the_tank_correction_is_not_charged_to_the_open_run(self):
        # The S8 test profile's tank anchors at 3800 ml (4000 - 5%). A tank predicted
        # at 3710 ml is raised by 90 ml at the anchor; the 10 m2 run that emptied it
        # still shows its own 90 ml, not 180.
        state = {**BASE, "used_ml": 3620, "initialized": True, "last_reset_ts": 1, "last_dock_err": "ok"}
        state = run(S8, state, [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                                dict(status="cleaning", vac="cleaning", area="10", intensity="extreme"),
                                dict(status="cleaning", vac="cleaning", area="10", intensity="extreme", dock_err="water_empty"),
                                dict(status="cleaning", vac="cleaning", area="10", intensity="extreme", dock_err="water_empty",
                                     _gap=70_000),
                                dict(status="charging", vac="docked", area="10", intensity="extreme", dock_err="water_empty")])
        self.assertAlmostEqual(state["used_ml"], 3800, places=1)
        self.assertAlmostEqual(state["automatic_sessions"][0]["water"], 90, places=1)


class LidDuringEmptyErrorTests(unittest.TestCase):
    def test_lid_refill_inside_the_window_counts_when_the_tank_is_empty_again(self):
        cfg = {"vacuum_entity": "vacuum.robot", "reset_door_sensor": "binary_sensor.lid",
               "config_provenance": {"authored_fields": ["vacuum_entity", "reset_door_sensor"]}}
        device = effective({"configured_devices": [cfg]}, descriptor())
        # The dock cleared (auto refill) 5 minutes ago and reports empty again.
        state = {**BASE, "used_ml": 900, "initialized": True, "last_reset_ts": 10_000_000, "last_reset_source": "dock_cleared",
                 "water_empty_active": True, "water_anchor_kind": "empty", "last_dock_err": "water_empty"}
        state = run(device, state, [dict(dock_err="water_empty", extra={"binary_sensor.lid": _S("on")}),
                                    dict(dock_err="water_empty", extra={"binary_sensor.lid": _S("off")})], ts=10_180_000)
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "lid")


class SessionEndStateTests(unittest.TestCase):
    def test_vendor_end_states_close_the_session(self):
        for end in ("charging_completed", "sleeping", "standby"):
            with self.subTest(end=end):
                state = run(S8, dict(BASE), [dict(status="cleaning", vac="cleaning", area="0", intensity="extreme"),
                                             dict(status="cleaning", vac="cleaning", area="5", intensity="extreme"),
                                             dict(status=end, vac="idle", area="5", intensity="extreme")])
                self.assertIsNone(state.get("session_start_ts"))
                self.assertEqual(len(state["automatic_sessions"]), 1)


class DeprecatedRegistryApiTests(unittest.TestCase):
    """HA 2026.9 warns (removal 2027.8/2027.9) on registry mapping access and async_get_device."""

    def test_integration_code_avoids_deprecated_registry_calls(self):
        package = ROOT / "custom_components" / "ha_vacuum_water_monitor"
        for path in package.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn(".async_get_device(", source)
                self.assertNotIn('"devices", {}).values()', source)
                self.assertNotIn(".devices[", source)


class ShadowReplayToolTests(unittest.TestCase):
    def test_history_request_has_an_end_time(self):
        # Without end_time HA returns one day from start, so --days N replays 24 h.
        source = (ROOT / "scripts" / "shadow_capture.py").read_text(encoding="utf-8")
        self.assertIn("end_time", source)


if __name__ == "__main__":
    unittest.main()
