"""Keep local QA success separate from the universal consumption acceptance gate."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ('mode_action_inventory_complete', 'ha_bindings_verified',
            'consumption_model_verified', 'independent_validation')


def blockers(coverage, evidence=None, inventory=None):
    result = []
    evidence_by_id = {r["id"]: r for r in (evidence or {}).get("records", [])}
    if evidence is None or inventory is None:
        result.append("missing_evidence_documents")
    if coverage.get('global_inventory_complete') is not True:
        result.append('global_model_and_integration_inventory_incomplete')
    if not coverage.get('models'):
        result.append('empty_model_inventory')
    for model in coverage.get('models', []):
        for key in CRITERIA:
            if model.get(key) is not True:
                result.append(f"{model['profile_id']}:{key}")
    for model in coverage.get("models", []):
        refs = model.get("consumption_evidence_ids", [])
        eligible = [evidence_by_id.get(ref, {}) for ref in refs]
        if not eligible or not all(r.get("runtime_eligible") is True and r.get("profile_id") == model["profile_id"] and r.get("ha_binding") and r.get("firmware") and r.get("independent_validation", {}).get("evidence_url") for r in eligible):
            result.append(f"{model['profile_id']}:missing_applicable_consumption_evidence")
    for device in (inventory or {}).get("models", []):
        disposition = coverage.get("public_spec_dispositions", {}).get(device["model_id"], {})
        if disposition.get("status") not in ("mapped_to_profile", "verified_not_mopping", "verified_not_retail") or not disposition.get("evidence_url"):
            result.append(f"{device['model_id']}:unresolved_public_spec")
        elif disposition["status"] == "mapped_to_profile" and disposition.get("profile_id") not in {r["profile_id"] for r in coverage.get("models", [])}:
            result.append(f"{device['model_id']}:invalid_profile_mapping")
    for model in coverage.get('additional_researched_models', []):
        result.append(f"unintegrated_researched_model:{model['model']}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    coverage = json.loads((ROOT / 'docs/consumption-coverage.json').read_text())
    profiles = json.loads((ROOT / 'custom_components/ha_vacuum_water_monitor/model_profiles.json').read_text())['profiles']
    ids = [m['profile_id'] for m in coverage['models']]
    if len(ids) != len(set(ids)) or set(ids) != set(profiles):
        raise SystemExit('Coverage must include each runtime profile exactly once')
    evidence = json.loads((ROOT / "docs/consumption-evidence.json").read_text())
    inventory = json.loads((ROOT / "docs/miot-signal-inventory.json").read_text())
    missing = blockers(coverage, evidence, inventory)
    complete = not missing
    if coverage.get('goal_complete') is not complete:
        raise SystemExit('Stored goal_complete contradicts evidence gates')
    print(json.dumps({'format_check': 'PASS', 'goal_complete': complete,
                      'unresolved_criteria': len(missing), 'models': len(ids)}))
    return 2 if args.require_complete and missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
