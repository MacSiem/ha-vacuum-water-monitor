"""A completed wash dedupe window must not invent water exposure at startup."""
from __future__ import annotations

import copy
import json
import unittest

from test_beta_runtime_path import BASE, descriptor, effective, hass, run, tick


class RestartAccountingTests(unittest.TestCase):
    def setUp(self):
        self.device = effective({}, descriptor())

    def completed(self):
        state = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
            dict(status="washing_the_mop", vac="docked", area="4"),
            dict(status="charging", vac="docked", area="4"),
        ])
        self.assertIsNone(state.get("session_start_ts"))
        self.assertTrue(state["wash_sequence_active"])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], 174)
        return state

    def assert_preserved(self, before, after):
        self.assertFalse(after.get("accounting_incomplete"))
        self.assertEqual(after["used_ml"], 174)
        self.assertIsNone(after.get("session_start_ts"))
        self.assertEqual(after["automatic_sessions"], before["automatic_sessions"])
        self.assertEqual(after.get("last_accounting_interruption"), before.get("last_accounting_interruption"))

    def test_completed_wash_restored_then_startup_unavailable_keeps_balance(self):
        before = self.completed()
        restored = json.loads(json.dumps(before))
        after = run(self.device, restored, [
            dict(status="unavailable", vac="unavailable", area="4", _gap=600_000),
            dict(status="charging", vac="docked", area="4", _gap=10_000),
        ], ts=10_240_000)
        self.assert_preserved(before, after)

    def test_completed_wash_long_tick_gap_keeps_balance(self):
        before = self.completed()
        after = run(self.device, copy.deepcopy(before), [
            dict(status="charging", vac="docked", area="4", _gap=610_000),
        ], ts=10_240_000)
        self.assert_preserved(before, after)

    def test_startup_unknown_repeats_keep_original_gap_anchor(self):
        before = self.completed()
        state = copy.deepcopy(before)
        for ts in (10_840_000, 10_850_000, 10_860_000):
            state, _ = tick.tick_device(hass(status="unknown", vac="unknown", area="4"), self.device, state, now_ts=ts)
            self.assertEqual(state["gap_started_ts"], 10_240_000)
        after, _ = tick.tick_device(hass(area="4"), self.device, state, now_ts=10_870_000)
        self.assert_preserved(before, after)

    def test_completed_wash_restart_keeps_earlier_resolved_incident(self):
        before = self.completed()
        before["last_accounting_interruption"] = {
            "ts": 1_000, "reasons": ["accounting_context_changed"],
            "resolved_ts": 2_000, "refill_source": "repair",
        }
        after = run(self.device, copy.deepcopy(before), [
            dict(vac="unavailable", area="4", _gap=600_000),
            dict(area="4", _gap=10_000),
        ], ts=10_240_000)
        self.assert_preserved(before, after)

    def test_existing_incomplete_balance_and_incident_are_not_cleared(self):
        before = self.completed()
        before.update(accounting_incomplete=True, last_accounting_interruption={
            "ts": 1_000, "reasons": ["gap_not_bridged"],
        })
        after = run(self.device, copy.deepcopy(before), [
            dict(vac="unavailable", area="4", _gap=600_000), dict(area="4"),
        ], ts=10_240_000)
        self.assertTrue(after["accounting_incomplete"])
        self.assertEqual(after["last_accounting_interruption"], before["last_accounting_interruption"])

    def test_active_wash_without_area_progress_still_loses_continuity(self):
        state = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
            dict(status="washing_the_mop", vac="docked", area="4"),
        ])
        state = run(self.device, state, [
            dict(status="unavailable", vac="unavailable", area="4", _gap=600_000),
            dict(status="charging", vac="docked", area="4", _gap=10_000),
        ], ts=10_180_000)
        self.assertTrue(state["accounting_incomplete"])
        self.assertIn("gap_not_bridged", state["last_accounting_interruption"]["reasons"])

    def test_new_area_in_dock_after_completed_wash_is_still_unobserved_exposure(self):
        before = self.completed()
        after = run(self.device, copy.deepcopy(before), [
            dict(vac="unavailable", area="4", _gap=600_000), dict(area="14"),
        ], ts=10_240_000)
        self.assertTrue(after["accounting_incomplete"])
        self.assertEqual(after["used_ml"], 174)

    def test_dedupe_latch_is_kept_during_short_dock_transition(self):
        before = self.completed()
        after = run(self.device, copy.deepcopy(before), [
            dict(vac="unavailable", area="4", _gap=10_000),
            dict(status="washing_the_mop", vac="docked", area="4", _gap=10_000),
        ], ts=10_240_000)
        self.assertEqual(after["used_ml"], 174)
        self.assertTrue(after["wash_sequence_active"])

    def test_unconfirmed_completed_wash_counter_remains_possible_exposure(self):
        before = self.completed()
        before["verified_wash_active"] = True
        after = run(self.device, before, [
            dict(vac="unavailable", area="4", _gap=600_000), dict(area="4"),
        ], ts=10_240_000)
        self.assertTrue(after["accounting_incomplete"])

    def test_dock_wash_remains_possible_exposure_even_if_robot_reports_charging(self):
        before = self.completed()
        before["last_dock_status"] = "washing_the_mop"
        after = run(self.device, before, [
            dict(vac="unavailable", area="4", _gap=600_000), dict(area="4"),
        ], ts=10_240_000)
        self.assertTrue(after["accounting_incomplete"])
