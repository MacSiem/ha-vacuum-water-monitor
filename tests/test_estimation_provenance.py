"""Consumer-visible evidence and protection against misleading calibration."""

import math
import unittest

from test_beta_estimation import estimation
from test_sensor_calculations import estimate_water_state


class EstimationEvidenceTests(unittest.TestCase):
    def test_sensor_preserves_owner_evidence_without_claiming_metered_volume(self):
        result = estimate_water_state(
            {"profile_key": "roborock_s8_maxv_ultra", "vacuum_entity": "vacuum.qa"},
            {"initialized": True, "used_ml": 100}, {},
        )
        sources = result.get("estimate_sources", [])
        self.assertTrue(sources, "the sensor must retain the prior's evidence")
        self.assertIn("not metered", " ".join(sources))
        self.assertEqual(result.get("uncertainty_kind"), "prior_band")

    def test_authored_rate_does_not_inherit_catalog_prior_evidence(self):
        result = estimate_water_state(
            {"profile_key": "roborock_s8_maxv_ultra", "vacuum_entity": "vacuum.qa"},
            {"initialized": True, "used_ml": 100},
            {"custom_calibration": {"entity:vacuum.qa": {"usage_ml_per_m2": {"default": 8}}}},
        )
        self.assertEqual(result.get("estimate_sources"), [])
        self.assertIsNone(result.get("uncertainty_kind"))

    def test_two_tanks_are_insufficient_to_shrink_prior_uncertainty(self):
        for factors in ([math.log(1.2)], [math.log(1.2), math.log(1.2)]):
            with self.subTest(factors=factors):
                self.assertEqual(estimation.uncertainty_percent("class_prior", factors), 50)

    def test_real_volume_sensor_does_not_inherit_prior_accuracy_claims(self):
        result = estimate_water_state(
            {"profile_key": "roborock_s8_maxv_ultra", "water_volume_sensor": "sensor.qa_ml"},
            {"last_water_volume_ml": 1250, "last_accounting_source": "real_sensor"}, {},
        )
        self.assertEqual(result["remaining_ml"], 1250)
        self.assertIsNone(result["estimate_basis"])
        self.assertIsNone(result["uncertainty_percent"])
        self.assertEqual(result.get("estimate_sources"), [])

    def test_three_tanks_report_repeatability_separately_from_prior(self):
        result = estimate_water_state(
            {"profile_key": "roborock_s8_maxv_ultra", "vacuum_entity": "vacuum.qa"},
            {"initialized": True, "used_ml": 100, "calibration_samples": 3,
             "calibration_log_factors": [math.log(1.2)] * 3}, {},
        )
        self.assertEqual(result.get("uncertainty_kind"), "calibration_spread")
        self.assertLess(result["uncertainty_percent"], 20)
        self.assertFalse(result.get("physical_accuracy_verified", True))

    def test_invalid_or_out_of_range_observation_cannot_poison_or_clip_learning(self):
        for observation in (float("nan"), float("inf"), 0, -1, 0.1, 9):
            with self.subTest(observation=observation):
                window, factor, accepted, reason, pending = estimation.update_calibration(
                    [math.log(1.2)], observation, band_fraction=0.5)
                self.assertFalse(accepted)
                self.assertEqual(window, [math.log(1.2)])
                self.assertAlmostEqual(factor, 1.2)
                self.assertIsNone(pending)
                self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
