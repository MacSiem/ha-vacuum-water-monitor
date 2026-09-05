"""No unresolved acceptance item may silently lose an owner or next action."""
import importlib.util
from pathlib import Path
import unittest


class SprintLedgerTests(unittest.TestCase):
    def check(self,ledger,blockers):
        path=Path(__file__).resolve().parents[1]/'scripts/check_sprint_ledger.py'
        self.assertTrue(path.exists(),'Ledger verifier is missing')
        spec=importlib.util.spec_from_file_location('ledger_check',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.validate(ledger,blockers)

    def test_missing_disposition_owner_and_next_step_are_rejected(self):
        self.assertTrue(self.check({'coverage_dispositions':{}},['model:unknown']))
        self.assertTrue(self.check({'coverage_dispositions':{'model:unknown':{'status':'unknown'}}},['model:unknown']))

    def test_explicit_unresolved_disposition_is_valid_not_complete(self):
        row={'status':'unknown','owner':'Codex dataset','evidence':'source not sufficient','next_step':'Verify primary manual'}
        self.assertEqual(self.check({'coverage_dispositions':{'model:unknown':row}},['model:unknown']),[])
        row['status']='complete'
        self.assertTrue(self.check({'coverage_dispositions':{'model:unknown':row}},['model:unknown']))
