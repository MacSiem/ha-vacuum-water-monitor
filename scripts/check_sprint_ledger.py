"""Require explicit disposition of every unresolved consumption acceptance gate."""
import json
from pathlib import Path


def validate(ledger, unresolved):
    errors = []
    rows = ledger.get('coverage_dispositions', {})
    if not isinstance(rows, dict):
        return ['coverage_dispositions must be an object']
    for key in unresolved:
        row = rows.get(key)
        if not isinstance(row, dict):
            errors.append(key + ':missing_disposition')
            continue
        if row.get('status') not in {'unknown', 'blocked_dependency', 'needs_evidence'}:
            errors.append(key + ':unresolved_cannot_be_complete')
        for field in ('owner', 'evidence', 'next_step'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(key + ':missing_' + field)
    return errors


if __name__ == '__main__':
    from check_consumption_coverage import blockers
    root = Path(__file__).resolve().parents[1]
    read = lambda name: json.loads((root / 'docs' / name).read_text())
    unresolved = blockers(read('consumption-coverage.json'), read('consumption-evidence.json'), read('miot-signal-inventory.json'))
    errors = validate(read('app-sprint-ledger.json'), unresolved)
    print(json.dumps({'disposition_check':'FAIL' if errors else 'PASS',
                      'unresolved_criteria':len(unresolved), 'errors':errors[:10]}))
    raise SystemExit(bool(errors))
