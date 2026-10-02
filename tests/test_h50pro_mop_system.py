import unittest
from test_beta_estimation import profiles

class H50ProMechanismTests(unittest.TestCase):
    def test_confirmed_dual_rotating_model_uses_labelled_class_prior(self):
        result=profiles.resolve_profile({"manufacturer":"Xiaomi","model":"Xiaomi Robot Vacuum H50 Pro"})
        self.assertEqual(result["profile_key"],"xiaomi_h50_pro")
        self.assertEqual(result["mop_system"],"rotating_pads")
        self.assertEqual(result["estimate_basis"],"class_prior")
        self.assertEqual(result["accounting_evidence"],"labeled_estimate")
        self.assertEqual(result["uncertainty_percent"],50)
        self.assertEqual(result["usage_ml_per_m2"]["deep"],10)
        self.assertEqual(result["tracked_capacity_ml"],4000)

    def test_h50_base_does_not_inherit_pro_mechanism(self):
        result=profiles.resolve_profile({"profile_key":"xiaomi_h50"})
        self.assertEqual(result["mop_system"],"unknown")
        self.assertEqual(result["estimate_basis"],"generic_prior")
