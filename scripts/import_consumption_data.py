"""Import an offline bundle after validation by the explicitly selected local data repo.

This is a developer build tool, not a Home Assistant runtime network operation.
The --data-repo argument must point to a trusted checkout of vacuum-consumption-data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'custom_components/ha_vacuum_water_monitor/consumption_snapshot.json'

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def compile_snapshot(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {'payload', 'manifest'}:
        raise ValueError('Invalid bundle envelope')
    payload, manifest = bundle['payload'], bundle['manifest']
    if not isinstance(payload, dict) or not isinstance(manifest, dict):
        raise ValueError('Invalid manifest/payload')
    version = payload.get('schema_version')
    if type(version) is not int or version not in {1, 2} or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != version:
        raise ValueError('Incompatible schema')
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    records = payload.get('records')
    if not isinstance(records, list) or manifest.get('payload_sha256') != digest:
        raise ValueError('Corrupt bundle')
    if type(manifest.get('record_count')) is not int or manifest['record_count'] != len(records) or not isinstance(payload.get('dataset_version'), str) or not payload['dataset_version'] or manifest.get('dataset_version') != payload['dataset_version']:
        raise ValueError('Manifest mismatch')
    if any(not isinstance(r, dict) or not isinstance(r.get('id'), str) or not r['id'] for r in records):
        raise ValueError('Invalid record identity')
    ids = [r['id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate IDs')
    observations = {r['id']: r for r in records if r.get('kind') == 'observation'}
    import importlib.util
    spec = importlib.util.spec_from_file_location('snapshot_profiles', ROOT / 'custom_components/ha_vacuum_water_monitor/profiles.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profiles = []
    estimates = []
    for record in records:
        if record.get('kind') == 'estimate':
            if version != 2 or not module._valid_labeled_estimate(record):
                raise ValueError('Ineligible v2 estimate')
            estimates.append(record)
            continue
        if record.get('kind') != 'profile':
            continue
        if version != 2:
            raise ValueError('v1 profile is evidence only; accounting contract missing')
        if not module._valid_consumption_record(record):
            raise ValueError('Ineligible v2 profile')
        refs = set(record['evidence_ids']) | set(record['validation']['training_ids']) | set(record['validation']['validation_ids'])
        for ref in refs:
            observation = observations.get(ref, {})
            if (observation.get('context') != record['context']
                    or observation.get('evidence_class') != 'empirical'
                    or observation.get('confidence') not in {'measured', 'validated'}
                    or not observation.get('provenance')
                    or any(p.get('type') != 'empirical' for p in observation['provenance'])):
                raise ValueError('Missing applicable empirical evidence')
        train, hold = record['validation']['training_ids'], record['validation']['validation_ids']
        if set(train + hold) != set(record['evidence_ids']):
            raise ValueError('Incomplete evidence lineage')
        measurements = []
        for ref in train + hold:
            obs = observations[ref]
            measured = obs.get('measurement')
            if (not isinstance(measured, dict) or measured.get('scope') != record['scope']
                    or measured.get('exposure_unit') != record['unit'].split('/')[1]
                    or measured.get('settings_constant') is not True or measured.get('interrupted') is not False
                    or measured.get('publication_consent') is not True
                    or any(not module._positive_number(measured.get(k)) for k in ('observed_ml', 'exposure', 'instrument_resolution_ml'))
                    or not measured.get('series_id') or not measured.get('cycle_id')
                    or measured.get('split') != ('train' if ref in train else 'validation')):
                raise ValueError('Incomplete physical measurement')
            measurements.append(measured)
        if len({(v['series_id'],v['cycle_id']) for v in measurements}) != len(measurements):
            raise ValueError('Repeated physical cycle')
        train_devices = {observations[k]['measurement']['series_id'] for k in train}
        hold_devices = {observations[k]['measurement']['series_id'] for k in hold}
        if train_devices & hold_devices or len(train_devices | hold_devices) != record['validation']['device_count']:
            raise ValueError('Device holdout leakage')
        import math
        errors = [abs(record['coefficient'] * observations[k]['measurement']['exposure'] - observations[k]['measurement']['observed_ml']) for k in hold]
        relative = [e / observations[k]['measurement']['observed_ml'] for e,k in zip(errors,hold)]
        if not math.isclose(max(errors),record['validation']['max_error_ml'],abs_tol=1e-9) or not math.isclose(max(relative),record['validation']['max_relative_error'],abs_tol=1e-9):
            raise ValueError('Untrue validation metrics')
        profiles.append(record)
    return {'schema_version':version, 'dataset_version':payload['dataset_version'],
            'source_payload_sha256':digest, 'source_revision':payload.get('source_revision'),
            'profiles':sorted(profiles, key=lambda r:r['id']),
            'estimates':sorted(estimates, key=lambda r:r['id'])}

def compile_portable(envelope, source_bundle):
    """Bind a v2 projection to exact source bytes; declared hashes are not proof."""
    if (not isinstance(envelope, dict) or set(envelope) != {'schema_version','envelope_kind','source_payload_sha256','records'}
            or type(envelope['schema_version']) is not int or envelope['schema_version'] != 2
            or envelope['envelope_kind'] != 'portable_import'
            or not isinstance(envelope['records'], list) or not envelope['records']):
        raise ValueError('Invalid portable import envelope')
    source_payload = source_bundle['payload']
    digest = hashlib.sha256(canonical(source_payload)).hexdigest()
    if digest != source_bundle['manifest']['payload_sha256'] or digest != envelope['source_payload_sha256']:
        raise ValueError('Portable source hash mismatch')
    projected = []
    for record in envelope['records']:
        if not isinstance(record, dict):
            raise ValueError('Invalid portable record')
        projected.append({k:v for k,v in record.items() if k not in {'evidence_class','accounting_contract'}})
    if projected != source_payload['records']:
        raise ValueError('Portable records differ from verified source')
    payload = {**source_payload, 'schema_version':2, 'records':envelope['records']}
    manifest = {**source_bundle['manifest'], 'schema_version':2,
                'payload_sha256':hashlib.sha256(canonical(payload)).hexdigest()}
    result = compile_snapshot({'payload':payload, 'manifest':manifest})
    result['source_payload_sha256'] = digest
    return result


def snapshot_diff(current, candidate):
    """Return the reviewable active-rate and evidence-lineage change."""
    def index(snapshot):
        profiles = snapshot.get('profiles', []) if isinstance(snapshot, dict) else []
        if not isinstance(profiles, list) or any(
                not isinstance(profile, dict) or not profile.get('id')
                for profile in profiles):
            raise ValueError('Invalid snapshot for diff')
        return {profile['id']: profile for profile in profiles}

    before, after = index(current), index(candidate)
    fields = ('method', 'coefficient', 'unit', 'evidence_ids')
    changed = []
    for profile_id in sorted(set(before) & set(after)):
        left = {key: before[profile_id].get(key) for key in fields}
        right = {key: after[profile_id].get(key) for key in fields}
        if left != right:
            changed.append({'id': profile_id, 'before': left, 'after': right})
    return {'added': sorted(set(after) - set(before)),
            'removed': sorted(set(before) - set(after)), 'changed': changed}


def atomic_write(path,data,verify=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    previous=path.read_bytes() if path.exists() else None
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.consumption-',delete=False) as f:
            name=f.name;f.write(canonical(data)+b'\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path);name=None
        if verify is not None and verify(path) is not True:
            raise ValueError('Snapshot readback failed')
    except Exception:
        if previous is None:
            if path.exists():
                path.unlink()
        else:
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.consumption-rollback-',delete=False) as f:
                rollback=f.name;f.write(previous);f.flush();os.fsync(f.fileno())
            os.replace(rollback,path)
        raise
    finally:
        if name is not None:os.unlink(name)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-repo',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--check',action='store_true');p.add_argument('--portable',type=Path,help='Strict v2 envelope bound to --bundle source');args=p.parse_args()
    data_repo=args.data_repo.resolve();bundle_path=args.bundle.resolve()
    raw=bundle_path.read_text()
    code='import json,sys; from tools.build_bundle import verify; verify(json.load(sys.stdin))'
    # v2 retains all v1 record semantics, plus the app's stricter contract gate.
    # The received dataset builder has no v2 envelope/schema yet. Validate a
    # lossless v1 projection of records, never skip empirical/settings checks.
    if json.loads(raw).get('payload', {}).get('schema_version') == 2:
        code = """import json,sys
from tools.validate import validate_dataset
records=json.load(sys.stdin)['payload']['records']
for r in records:
    r.pop('evidence_class',None)
    r.pop('accounting_contract',None)
validate_dataset(records)
"""
    subprocess.run([sys.executable,'-c',code],input=raw,text=True,cwd=data_repo,check=True,
                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
    # Compile exactly the bytes validated through stdin, not a second file read.
    if args.portable:
        portable_raw=args.portable.read_text()
        subprocess.run([sys.executable,'-c','import json,sys; from tools.contracts_v2 import validate_import; validate_import(json.load(sys.stdin))'],
                       input=portable_raw,text=True,cwd=data_repo,check=True,
                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
        snapshot=compile_portable(json.loads(portable_raw),json.loads(raw))
    else:
        snapshot=compile_snapshot(json.loads(raw))
    current=json.loads(TARGET.read_text()) if TARGET.exists() else {'profiles':[]}
    diff=snapshot_diff(current,snapshot)
    if args.check:
        if current!=snapshot:raise SystemExit('Snapshot differs: '+json.dumps(diff,sort_keys=True))
    else:
        atomic_write(TARGET,snapshot,verify=lambda path:json.loads(path.read_text())==snapshot)
    print(json.dumps({'snapshot':'PASS','profiles':len(snapshot['profiles']),
                      'dataset_version':snapshot['dataset_version'],'diff':diff}))
