"""Feature grants are independent and resource scope narrows them."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/ha_vacuum_water_monitor/feature_access.py"
spec = importlib.util.spec_from_file_location("vwm_access_test", PATH)
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class AccessPolicyTests(unittest.TestCase):
    def test_selected_user_and_robot_do_not_gain_other_operations(self):
        policy = {"schema": 1, "features": {"water": {
            "visible": {"mode": "household"},
            "read": {"mode": "selected_users", "user_ids": ["u1"], "entity_ids": ["vacuum.a"]},
            "execute": {"mode": "admin"},
        }}}
        def allowed(user, operation, entity="vacuum.a", admin=False):
            return access.feature_access_allowed(policy, "water", operation, user_id=user,
                is_active=True, is_admin=admin, entity_id=entity)
        self.assertTrue(allowed("u1", "read"))
        self.assertFalse(allowed("u1", "read", "vacuum.b"))
        self.assertFalse(allowed("u2", "read"))
        self.assertTrue(allowed("u2", "visible"))
        self.assertFalse(allowed("u1", "execute"))
        self.assertTrue(allowed("admin", "execute", admin=True))

    def test_invalid_or_oversized_rules_fail_closed(self):
        for policy in ({"schema": True, "features": {}},
                       {"schema": 1, "features": {"water": {"execute": {"mode": "household", "entity_ids": ["sensor.x"]}}}},
                       {"schema": 1, "features": {"water": {"read": {"mode": "selected_users", "user_ids": ["u"] * 129}}}},
                       {"schema": 1, "features": {"unknown": {}}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                access.validate_feature_access(policy)
