"""Rejected area samples must not distort learning or task history.

These reproduce source defects discovered while investigating issue #11;
they do not assert that the author's undocumented area jump was a false alarm.
"""
import copy
import json
import unittest

from test_beta_runtime_path import BASE, _S, descriptor, effective, hass, run, tick


class AreaObservationValidationTests(unittest.TestCase):
    def setUp(self):
        self.device = effective({}, descriptor())

    def test_new_task_first_nonzero_area_matches_counted_water_in_history(self):
        state = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="2"),
            dict(status="cleaning", vac="cleaning", area="4"),
            dict(status="charging", vac="docked", area="4"),
        ])
        self.assertFalse(state.get("accounting_incomplete"))
        self.assertEqual(state["used_ml"], 24)
        self.assertEqual(state["automatic_sessions"][0]["water"], 24)
        self.assertEqual(state["automatic_sessions"][0]["area"], 4)

    def test_rejected_area_jump_does_not_train_cleaning_pace(self):
        before = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
        ])
        self.assertGreater(before["area_rate_m2_per_s"], 0)
        after = run(self.device, copy.deepcopy(before), [
            dict(status="cleaning", vac="cleaning", area="40"),
        ], ts=10_120_000)
        self.assertEqual(after["used_ml"], before["used_ml"])
        self.assertTrue(after["accounting_incomplete"])
        self.assertIn("area_anomaly", after["last_accounting_interruption"]["reasons"])
        self.assertEqual(after["area_rate_m2_per_s"], before["area_rate_m2_per_s"])
        # The accepted pace, not the rejected jump, must survive persisted state.
        self.assertEqual(json.loads(json.dumps(after))["area_rate_m2_per_s"], before["area_rate_m2_per_s"])

    def test_first_positive_increment_uses_the_previously_observed_baseline(self):
        for previous_area, first_area, final_area in ((0, 2, 4), (10, 12, 14)):
            with self.subTest(previous_area=previous_area):
                state = run(self.device, {**BASE, "last_area": previous_area}, [
                    dict(status="cleaning", vac="cleaning", area=str(first_area)),
                    dict(status="cleaning", vac="cleaning", area=str(final_area)),
                    dict(status="charging", vac="docked", area=str(final_area)),
                ])
                self.assertEqual(state["used_ml"], 24)
                self.assertEqual(state["automatic_sessions"][0]["area"], 4)

    def test_first_area_interruption_keeps_bounded_observation_after_idle_and_refill(self):
        before = run(self.device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
        ])
        after = run(self.device, before, [
            dict(status="cleaning", vac="cleaning", extra={
                "sensor.robot_area": _S("400000", {"unit_of_measurement": "cm²"}),
            }),
        ], ts=10_120_000)
        incident = copy.deepcopy(after["last_accounting_interruption"])
        observation = incident.get("area_observation")
        self.assertIsNotNone(observation)
        self.assertEqual(observation["raw_value"], 400000)
        self.assertEqual(observation["unit"], "cm²")
        self.assertEqual(observation["previous_m2"], 4)
        self.assertEqual(observation["current_m2"], 40)
        self.assertEqual(observation["delta_m2"], 36)
        self.assertEqual(observation["ceiling_m2"], 25)
        self.assertEqual(observation["interval_seconds"], 60)
        self.assertTrue(observation["cleaning"])
        from vwmruntimepkg.const import VERSION
        self.assertEqual(observation["version"], VERSION)
        self.assertLess(len(json.dumps(observation)), 700)
        self.assertNotIn("sensor.robot_area", json.dumps(incident))
        later = run(self.device, after, [dict(status="charging", vac="docked", area="40")], ts=10_180_000)
        self.assertEqual(later["last_accounting_interruption"], incident)
        from vwmruntimepkg.refill import apply_refill
        apply_refill(later, 10_300_000, "repair", rebaseline=True)
        persisted = json.loads(json.dumps(later))
        self.assertEqual(persisted["last_accounting_interruption"]["area_observation"], observation)
        self.assertFalse(any(key.startswith("_pass_") for key in persisted))

    def test_area_attribute_fallback_records_the_value_actually_used(self):
        device = {**self.device, "area_attribute": "cleaned_area", "area_attribute_unit": "ft²"}
        before = run(device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
        ])
        after = run(device, before, [dict(status="cleaning", vac="cleaning", extra={
            "sensor.robot_area": _S("unavailable", {"unit_of_measurement": "m²"}),
            "vacuum.robot": _S("cleaning", {"status": "cleaning", "cleaned_area": 500}),
        })], ts=10_120_000)
        observation = after["last_accounting_interruption"]["area_observation"]
        self.assertEqual(observation["raw_value"], 500)
        self.assertEqual(observation["unit"], "ft²")
        self.assertAlmostEqual(observation["current_m2"], 46.45152)

    def test_system_area_unit_records_the_effective_imperial_unit(self):
        device = {**self.device, "area_attribute": "cleaned_area",
                  "area_attribute_unit": "ha_unit_system"}
        before = run(device, dict(BASE), [
            dict(status="cleaning", vac="cleaning", area="0"),
            dict(status="cleaning", vac="cleaning", area="4"),
        ])
        host = hass(status="cleaning", vac="cleaning", extra={
            "sensor.robot_area": _S("unavailable", {"unit_of_measurement": "m²"}),
            "vacuum.robot": _S("cleaning", {"status": "cleaning", "cleaned_area": 500}),
        })
        host.config.units.length_unit = "mi"
        after, _ = tick.tick_device(host, device, before, now_ts=10_180_000)
        observation = after["last_accounting_interruption"]["area_observation"]
        self.assertEqual(observation["unit"], "ft²")
        self.assertAlmostEqual(observation["current_m2"], 46.45152)
