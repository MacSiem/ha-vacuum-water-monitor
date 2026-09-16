"""5.7.0-beta.2: every refill choice resets the integration's own tank.

Audit 2026-09-15: the card's input_button and lid methods only generated HA
automations that reset legacy DIY helpers, the lid was blocked by the dock
contract, automatic dock refill had no off switch, and pressing Refilled while
the dock still showed its empty error re-emptied the tank on the next tick.
"""

from __future__ import annotations

import asyncio
import importlib
import unittest

from test_beta_runtime_path import BASE, _S, descriptor, effective, run, sc, tick

storage = importlib.import_module("vwmruntimepkg.storage")
refill = importlib.import_module("vwmruntimepkg.refill")

BUTTON = "input_button.dock_refilled"
LID = "binary_sensor.dock_tank_lid"


def device(refill_settings=None, **settings):
    all_settings = dict(settings)
    if refill_settings is not None:
        all_settings["refill_settings"] = {"vacuum.robot": refill_settings}
    return effective(all_settings, descriptor())


class ButtonAndLidTests(unittest.TestCase):
    def test_bound_input_button_press_resets_the_tank(self):
        dev = device({"button_entity": BUTTON})
        self.assertEqual(dev["refill_button_entity"], BUTTON)
        state = run(dev, {**BASE, "used_ml": 2500}, [
            dict(extra={BUTTON: _S("2026-09-10T08:00:00+00:00")}),
            dict(extra={BUTTON: _S("2026-09-10T08:00:00+00:00")}),
        ])
        self.assertEqual(state["used_ml"], 2500, "binding an already-pressed button is a baseline, not a press")
        state = run(dev, state, [dict(extra={BUTTON: _S("2026-09-16T07:30:00+00:00")})], ts=20_000_000)
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "button")
        self.assertEqual(state["refill_history"][0]["source"], "button")
        self.assertEqual(state["refill_history"][0]["used_before_ml"], 2500)

    def test_first_ever_press_of_a_new_helper_counts(self):
        dev = device({"button_entity": BUTTON})
        state = run(dev, {**BASE, "used_ml": 900}, [
            dict(extra={BUTTON: _S("unknown")}),
            dict(extra={BUTTON: _S("2026-09-16T07:30:00+00:00")}),
        ])
        self.assertEqual(state["used_ml"], 0)

    def test_button_reconnect_is_not_a_press(self):
        dev = device({"button_entity": BUTTON})
        pressed = "2026-09-10T08:00:00+00:00"
        state = run(dev, {**BASE, "used_ml": 1200}, [
            dict(extra={BUTTON: _S(pressed)}),
            dict(extra={BUTTON: _S("unavailable")}),
            dict(extra={BUTTON: _S(pressed)}),
        ])
        self.assertEqual(state["used_ml"], 1200)

    def test_lid_closing_resets_even_through_an_unavailable_reading(self):
        dev = device({"lid_entity": LID})
        state = run(dev, {**BASE, "used_ml": 2000}, [
            dict(extra={LID: _S("off")}), dict(extra={LID: _S("on")}),
            dict(extra={LID: _S("unavailable")}), dict(extra={LID: _S("off")}),
        ])
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "lid")

    def test_lid_refill_is_recorded_while_the_robot_is_offline(self):
        dev = device({"lid_entity": LID})
        state = run(dev, {**BASE, "used_ml": 2000, "last_door": "on"},
                    [dict(vac="unavailable", status="unavailable", extra={LID: _S("off")})])
        self.assertEqual(state["used_ml"], 0)

    def test_pre_5_7_card_refill_config_still_binds(self):
        dev = device(refill_config={"robot": {"buttonEntity": BUTTON, "sensorEntity": LID, "buttonAutoId": "vwm_refill_robot_button"}})
        self.assertEqual(dev["refill_button_entity"], BUTTON)
        self.assertEqual(dev["reset_door_sensor"], LID)

    def test_invalid_bindings_are_ignored(self):
        dev = device({"button_entity": "switch.pump", "lid_entity": "sensor.lid"})
        self.assertNotIn("refill_button_entity", dev)
        self.assertNotEqual(dev.get("reset_door_sensor"), "sensor.lid")


class AutomaticDockRefillChoiceTests(unittest.TestCase):
    EMPTY = [dict(dock_err="water_empty"), dict(dock_err="water_empty")]

    def test_default_dock_contract_refills_when_empty_clears(self):
        state = run(device(), {**BASE, "used_ml": 3700}, self.EMPTY + [dict(dock_err="ok", _gap=120_000)])
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "dock_cleared")

    def test_user_can_turn_automatic_refill_off(self):
        dev = device({"auto_refill": False})
        state = run(dev, {**BASE, "used_ml": 3700}, self.EMPTY + [dict(dock_err="ok", _gap=120_000)])
        self.assertGreater(state["used_ml"], 3000, "the tank stays at its empty anchor until the user reports the refill")
        self.assertFalse(state["water_empty_active"], "the empty condition ended")
        # The user reports the refill; the next real empty is a new anchor again.
        refill.apply_refill(state, 10_400_000, "card", rebaseline=True)
        state = run(dev, {**state, "used_ml": 3500}, [dict(), dict(dock_err="water_empty")], ts=10_500_000)
        self.assertTrue(state["water_empty_active"])
        self.assertEqual(state["calibration_history"][0]["target_ml"], 3800.0)

    def test_user_can_turn_automatic_refill_on_for_an_authored_contract(self):
        cfg = {"vacuum_entity": "vacuum.robot", "refill_on_clear": False,
               "config_provenance": {"authored_fields": ["vacuum_entity", "refill_on_clear"]}}
        dev = effective({"configured_devices": [cfg], "refill_settings": {"vacuum.robot": {"auto_refill": True}}}, descriptor())
        state = run(dev, {**BASE, "used_ml": 3700}, self.EMPTY + [dict(dock_err="ok", _gap=120_000)])
        self.assertEqual(state["used_ml"], 0)


class RefillWhileDockStillEmptyTests(unittest.TestCase):
    def test_refilled_before_the_dock_clears_its_error_keeps_the_tank_full(self):
        dev = device()
        state = run(dev, {**BASE, "used_ml": 3700}, [dict(dock_err="water_empty")])
        self.assertTrue(state["water_empty_active"])
        refill.apply_refill(state, 10_200_000, "card", rebaseline=True)
        state = run(dev, state, [dict(dock_err="water_empty"), dict(dock_err="water_empty"),
                                 dict(status="cleaning", vac="cleaning", area="0", dock_err="water_empty"),
                                 dict(status="cleaning", vac="cleaning", area="10", dock_err="water_empty")],
                    ts=10_200_000)
        used_after_cleaning = state["used_ml"]
        self.assertGreater(used_after_cleaning, 0)
        self.assertLess(used_after_cleaning, 200, "a persisting error is not a new empty anchor")
        state = run(dev, state, [dict(status="charging", area="10", dock_err="ok")], ts=10_600_000)
        self.assertEqual(state["used_ml"], used_after_cleaning, "clearing the acknowledged error is not a second refill")
        self.assertEqual(state["last_reset_source"], "card")
        self.assertFalse(state["water_empty_active"])
        self.assertFalse(state["water_empty_acknowledged"])


class ReviewFollowUpTests(unittest.TestCase):
    """Independent review of 5.7.0-beta.2 (2026-09-16)."""

    def test_flickering_empty_error_with_auto_refill_off_is_one_tank(self):
        dev = device({"auto_refill": False})
        state = run(dev, {**BASE, "used_ml": 3700}, [
            dict(dock_err="water_empty"), dict(dock_err="ok"), dict(dock_err="water_empty"),
            dict(dock_err="ok"), dict(dock_err="water_empty")])
        self.assertEqual(state.get("calibration_samples", 0), 1)
        self.assertEqual(state["calibration_history"][0]["reason"], "calibration_sample_no_refill_since_empty")

    def test_binding_another_button_is_not_a_refill(self):
        other = "input_button.other"
        state = run(device({"button_entity": BUTTON}), {**BASE, "used_ml": 2500},
                    [dict(extra={BUTTON: _S("2026-09-16T07:00:00+00:00")})] * 2)
        state = run(device({"button_entity": other}), state, [dict(extra={other: _S("2026-09-01T07:00:00+00:00")})],
                    ts=10_500_000)
        self.assertEqual(state["used_ml"], 2500)

    def test_a_restored_older_press_time_is_not_a_refill_but_a_newer_one_is(self):
        dev = device({"button_entity": BUTTON})
        state = run(dev, {**BASE, "used_ml": 2500}, [
            dict(extra={BUTTON: _S("2026-09-16T07:00:00+00:00")}),
            dict(extra={BUTTON: _S("unavailable")}),
            dict(extra={BUTTON: _S("2026-09-16T06:40:00+00:00")})])
        self.assertEqual(state["used_ml"], 2500)
        state = run(dev, state, [dict(extra={BUTTON: _S("2026-09-16T08:00:00+00:00")})], ts=20_000_000)
        self.assertEqual(state["used_ml"], 0)

    def test_binding_another_lid_is_not_a_refill(self):
        state = run(device({"lid_entity": LID}), {**BASE, "used_ml": 2000}, [dict(extra={LID: _S("on")})])
        state = run(device({"lid_entity": "binary_sensor.other_lid"}), state,
                    [dict(extra={"binary_sensor.other_lid": _S("off")})], ts=10_500_000)
        self.assertEqual(state["used_ml"], 2000)

    def test_refilled_before_the_empty_error_was_seen_keeps_the_tank_full(self):
        dev = device({"auto_refill": False})
        state = run(dev, {**BASE, "used_ml": 3700}, [dict()])
        refill.apply_refill(state, 10_060_000, "card", rebaseline=False)
        state = run(dev, state, [dict(dock_err="water_empty"), dict(dock_err="ok")], ts=10_060_000)
        self.assertEqual(state["used_ml"], 0)
        self.assertFalse(state["water_empty_active"])
        state = run(dev, {**state, "used_ml": 3600}, [dict(dock_err="water_empty")], ts=20_000_000)
        self.assertTrue(state["water_empty_active"], "the next real empty is still an anchor")
        self.assertGreater(state["used_ml"], 3700)

    def test_a_real_empty_soon_after_a_false_lid_refill_is_still_an_anchor(self):
        dev = device({"lid_entity": LID})
        state = run(dev, {**BASE, "used_ml": 1000}, [dict(extra={LID: _S("on")}), dict(extra={LID: _S("off")})])
        self.assertEqual(state["last_reset_source"], "lid")
        state = run(dev, {**state, "used_ml": 600}, [dict(dock_err="water_empty", extra={LID: _S("off")})], ts=10_600_000)
        self.assertTrue(state["water_empty_active"])
        self.assertFalse(state.get("water_empty_acknowledged"))

    def test_a_lid_closing_after_the_dock_already_cleared_is_the_same_refill(self):
        dev = device({"lid_entity": LID})
        state = run(dev, {**BASE, "used_ml": 3700}, [
            dict(dock_err="water_empty", extra={LID: _S("off")}), dict(extra={LID: _S("on")}),
            dict(dock_err="ok", extra={LID: _S("on")}, _gap=120_000),
            dict(status="cleaning", vac="cleaning", area="0", extra={LID: _S("on")}),
            dict(status="cleaning", vac="cleaning", area="10", extra={LID: _S("on")}),
            dict(status="cleaning", vac="cleaning", area="10", extra={LID: _S("off")}, _gap=90_000)])
        self.assertEqual([r["source"] for r in state["refill_history"]], ["dock_cleared"])
        self.assertGreater(state["used_ml"], 50)


class StorageRefillTests(unittest.TestCase):
    def test_reset_records_source_and_history(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            await st.async_set_tank_state("vacuum.robot", {"used_ml": 1234.5, "initialized": True})
            return await st.async_reset_tank("vacuum.robot", "2026-09-16T08:00:00+00:00", 1789545600000, source="service")

        state = asyncio.run(scenario())
        self.assertEqual(state["used_ml"], 0)
        self.assertEqual(state["last_reset_source"], "service")
        self.assertEqual(state["refill_history"][0], {"ts": 1789545600000, "source": "service",
                                                      "used_before_ml": 1234.5, "empty_acknowledged": False})

    def test_refill_settings_are_validated_and_replaced_per_vacuum(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            with self.assertRaises(ValueError):
                await st.async_set_refill_settings("vacuum.robot", auto_refill=None, button_entity="light.x", lid_entity=None)
            with self.assertRaises(ValueError):
                await st.async_set_refill_settings("vacuum.robot", auto_refill=None, button_entity=None, lid_entity="switch.lid")
            await st.async_set_refill_settings("vacuum.robot", auto_refill=False, button_entity=BUTTON, lid_entity=LID)
            first = await st.async_get_settings()
            await st.async_set_refill_settings("vacuum.robot", auto_refill=None, button_entity=None, lid_entity=None)
            return first, await st.async_get_settings()

        first, cleared = asyncio.run(scenario())
        self.assertEqual(first["refill_settings"]["vacuum.robot"],
                         {"auto_refill": False, "button_entity": BUTTON, "lid_entity": LID})
        self.assertNotIn("vacuum.robot", cleared["refill_settings"])

    def test_a_tick_computed_before_a_refill_does_not_overwrite_it(self):
        async def scenario():
            st = storage.VacuumWaterStorage(None)
            await st.async_load()
            await st.async_set_tank_state("vacuum.robot", {"used_ml": 3000, "last_reset_ts": 5})
            snapshot = (await st.async_get_state())["tank_states"]["vacuum.robot"]
            await st.async_reset_tank("vacuum.robot", "2026-09-16T08:00:00+00:00", 1789545600000)
            written = await st.async_set_tank_states({"vacuum.robot": {**snapshot, "used_ml": 3010}},
                                                     expected_reset_ts={"vacuum.robot": snapshot["last_reset_ts"]})
            return written, await st.async_get_tank_state("vacuum.robot")

        written, state = asyncio.run(scenario())
        self.assertEqual(written, {})
        self.assertEqual(state["used_ml"], 0)


class CapacityCorrectionTests(unittest.TestCase):
    def test_card_capacity_for_the_dock_tank_keeps_automatic_refill(self):
        custom = {"entity:vacuum.robot": {"tracked_capacity_ml": 3500, "tracked_reservoir": "dock_clean"}}
        dev = device(custom_calibration=custom)
        self.assertEqual(dev["tracked_capacity_ml"], 3500)
        self.assertTrue(dev.get("refill_on_clear_inferred"))
        self.assertEqual(dev.get("water_anchor_reservoir"), "dock_clean")

    def test_unqualified_capacity_still_does_not_infer_the_dock_contract(self):
        dev = device(custom_calibration={"entity:vacuum.robot": {"tracked_capacity_ml": 3500}})
        self.assertNotIn("refill_on_clear_inferred", dev)


if __name__ == "__main__":
    unittest.main()
