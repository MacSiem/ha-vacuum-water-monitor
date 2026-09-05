"""Regression: passing local tests must never imply universal consumption coverage."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('coverage_gate', Path(__file__).resolve().parents[1] / 'scripts/check_consumption_coverage.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ConsumptionAcceptanceTests(unittest.TestCase):
    def test_empty_inventory_cannot_complete(self):
        self.assertIn('empty_model_inventory', gate.blockers({'global_inventory_complete': True, 'models': []}))

    def test_all_criteria_required_for_each_model(self):
        row = dict(profile_id='example', **{k: True for k in gate.CRITERIA})
        data = {'global_inventory_complete': True, 'models': [row]}
        self.assertIn('missing_evidence_documents', gate.blockers(data))
        for key in gate.CRITERIA:
            with self.subTest(key=key):
                incomplete = dict(row, **{key: False})
                self.assertIn('example:' + key, gate.blockers(dict(data, models=[incomplete])))

    def test_additional_discovered_model_prevents_completion(self):
        data = {'global_inventory_complete': True, 'models': [dict(profile_id='example', **{k: True for k in gate.CRITERIA})], 'additional_researched_models': [{'model': 'new_robot'}]}
        self.assertIn('unintegrated_researched_model:new_robot', gate.blockers(data))

    def test_true_flags_do_not_override_ineligible_source(self):
        row = dict(profile_id='example', consumption_evidence_ids=['e1'], **{k: True for k in gate.CRITERIA})
        coverage = {'global_inventory_complete': True, 'models': [row]}
        evidence = {'records': [{'id': 'e1', 'profile_id': 'example', 'runtime_eligible': False}]}
        self.assertIn('example:missing_applicable_consumption_evidence', gate.blockers(coverage, evidence, {'models': []}))

    def test_untriaged_public_spec_blocks_complete(self):
        self.assertIn('public.model:unresolved_public_spec', gate.blockers({'global_inventory_complete': True, 'models': []}, {'records': []}, {'models': [{'model_id': 'public.model'}]}))
