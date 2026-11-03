"""The scoped subscription delivers compact balance updates and detaches cleanly."""
from pathlib import Path
import unittest
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]

class HouseholdSubscriptionTests(unittest.TestCase):
    # The subscription/revocation/unsubscribe contract is exercised with
    # authenticated clients in tests_ha/test_ha_runtime.py and test_58_entities.py.
    def test_household_card_receives_compact_updates_without_losing_history(self):
        subprocess.run(["node", ".github/household-events.cjs"],cwd=ROOT,check=True,env=os.environ.copy())
