"""Allowlisted contribution drafts; no upload and no automatic profile promotion."""
from __future__ import annotations

import math
from uuid import uuid4


def _number(value):
    # Do not copy strings from HA or accept booleans as physical quantities.
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return value


def _matrix_rank(matrix, tolerance=1e-10):
    """Compute numeric rank without adding a runtime scientific dependency."""
    work = [list(map(float, row)) for row in matrix]
    if not work:
        return 0
    rows, columns = len(work), len(work[0])
    rank = 0
    for column in range(columns):
        pivot = max(range(rank, rows), key=lambda row: abs(work[row][column]), default=None)
        if pivot is None or abs(work[pivot][column]) <= tolerance:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        scale = work[rank][column]
        work[rank] = [value / scale for value in work[rank]]
        for row in range(rows):
            if row == rank:
                continue
            factor = work[row][column]
            if abs(factor) > tolerance:
                work[row] = [left - factor * right
                             for left, right in zip(work[row], work[rank])]
        rank += 1
        if rank == rows:
            break
    return rank


def check_identifiability(method, exposures):
    """Check whether measured exposures can identify every requested rate.

    This gate inspects the design only. It neither consumes observed volume nor
    fits or promotes a consumption profile.
    """
    columns_by_method = {
        'area': ('area',),
        'time': ('time',),
        'action': ('action',),
        'hybrid': ('area', 'time', 'action'),
    }
    columns = columns_by_method.get(method)
    parameters = len(columns) if columns else 0
    invalid = {'identifiable': False, 'rank': 0,
               'parameters': parameters, 'reason': 'invalid_design'}
    if columns is None or not isinstance(exposures, list) or not exposures:
        return invalid
    matrix = []
    for row in exposures:
        if not isinstance(row, dict) or set(row) != set(columns):
            return invalid
        values = [_number(row.get(column)) for column in columns]
        if any(value is None for value in values):
            return invalid
        matrix.append(values)
    rank = _matrix_rank(matrix)
    identifiable = rank == parameters
    return {'identifiable': identifiable, 'rank': rank, 'parameters': parameters,
            'reason': 'full_rank' if identifiable else 'insufficient_rank'}


def build_contribution_draft(session, observed_ml=None, resolution_ml=None):
    """Export a numeric summary for manual review, not a dataset observation.

    Legacy history has no trustworthy historical settings or active-mopping
    exposure. Current settings must never be attached retrospectively.
    """
    measurement = None
    if observed_ml is not None or resolution_ml is not None:
        volume, resolution = _number(observed_ml), _number(resolution_ml)
        if volume is None or resolution is None or resolution <= 0:
            raise ValueError('Provide measured refill volume and positive measurement resolution in ml')
        measurement = {'observed_ml': volume, 'resolution_ml': resolution,
                       'scope': 'whole_cycle', 'source': 'user_entered_refill'}
    return {
        'schema_version': 1,
        'kind': 'contribution_draft',
        'draft_id': str(uuid4()),
        'runtime_eligible': False,
        'session': {
            'area_delta_m2': _number(session.get('area')),
            'elapsed_minutes': _number(session.get('duration')),
            'estimated_water_ml': _number(session.get('water')),
        },
        'measurement': measurement,
        'missing': ['public_model_id', 'sku', 'dock_variant', 'firmware',
                    'integration_version', 'reservoir', 'historical_settings',
                    'action_breakdown', 'measurement_instrument',
                    'refill_boundaries_confirmed', 'independent_validation'],
        'limitations': [
            'Elapsed time is not active mopping time; area delta may omit the first observed interval.',
            'Estimated water is not an independent physical measurement.',
            'A whole-cycle refill cannot separate floor, mop washing and internal transfers.',
            'Add missing public context and confirm measurement boundaries before submitting.',
        ],
    }


def select_recorded_cycle(sessions, index, expected_ts):
    """Reject a stale selection if a newly completed cycle moved the history."""
    if not isinstance(sessions, list) or type(index) is not int or not 0 <= index < min(len(sessions), 50):
        raise ValueError('No recorded cycle at this position')
    record = sessions[index]
    if not isinstance(record, dict) or type(expected_ts) is not int or record.get('ts') != expected_ts:
        raise ValueError('Recorded cycles changed; refresh and select the cycle again')
    return record


def build_local_measurement(session, values, device_id):
    """Validate a private whole-cycle refill; predictions are never training data."""
    from copy import deepcopy
    if not isinstance(session, dict) or not isinstance(values, dict):
        raise ValueError('Select a recorded cycle and provide measurement details')
    if values.get('boundaries_confirmed') is not True or values.get('uninterrupted') is not True:
        raise ValueError('Confirm full-to-full refill boundaries and an uninterrupted cycle')
    volume, resolution = _number(values.get('observed_ml')), _number(values.get('resolution_ml'))
    area = _number(session.get('area'))
    if volume is None or volume <= 0 or resolution is None or resolution <= 0 or resolution >= volume:
        raise ValueError('Provide positive measured ml and a finer positive resolution')
    if values.get('instrument') not in {'graduated_jug', 'scale_water', 'flow_meter'}:
        raise ValueError('Choose the measurement instrument')
    if values.get('purpose') not in {'training', 'validation'}:
        raise ValueError('Choose training or independent validation')
    if (session.get('exposure_complete') is not True or session.get('segments') != 1
            or area is None or area <= 0):
        raise ValueError('A complete single-context cycle with measured area is required')
    context = session.get('context')
    # Import lazily: direct-file export tests intentionally do not load HA.
    try:
        from .profiles import _known_context
    except ImportError:
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('calibration_profiles', Path(__file__).with_name('profiles.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _known_context = module._known_context
    if not _known_context(context) or not device_id or type(session.get('ts')) is not int:
        raise ValueError('Historical model, firmware, reservoir and every setting must be known')
    return {'id': 'local.' + str(session['ts']), 'device_id': device_id,
            'context': deepcopy(context), 'area_m2': area, 'observed_ml': volume,
            'resolution_ml': resolution, 'instrument': values['instrument'],
            'purpose': values['purpose'], 'scope': 'whole_cycle'}


def fit_local_measurements(samples):
    """Fit one identifiable total dose per m², never separate floor/wash rates.

    Three distinct cycles are the minimum training protocol. Holdout errors are
    descriptive and never change the fit or approve a shared profile.
    """
    from copy import deepcopy
    if not isinstance(samples, list) or not samples or any(not isinstance(s, dict) for s in samples):
        return None
    first = samples[0]
    ids = [s.get('id') for s in samples]
    if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        return None
    if any(s.get('device_id') != first.get('device_id') or s.get('context') != first.get('context')
           or s.get('scope') != 'whole_cycle' for s in samples):
        return None
    if any(_number(s.get(k)) is None or s[k] <= 0 for s in samples for k in ('area_m2', 'observed_ml', 'resolution_ml')):
        return None
    training = [s for s in samples if s.get('purpose') == 'training']
    holdout = [s for s in samples if s.get('purpose') == 'validation']
    if len(training) < 3:
        return None
    design = check_identifiability('area', [{'area': s['area_m2']} for s in training])
    if not design['identifiable']:
        return None
    coefficient = sum(s['observed_ml'] for s in training) / sum(s['area_m2'] for s in training)
    domain = {'min': min(s['area_m2'] for s in training), 'max': max(s['area_m2'] for s in training)}
    comparable = [s for s in holdout if domain['min'] <= s['area_m2'] <= domain['max']]
    errors = [abs(coefficient * s['area_m2'] - s['observed_ml']) for s in comparable]
    relative = [e/s['observed_ml'] for e,s in zip(errors, comparable)]
    return {'id': 'local.calibration.' + first['id'], 'kind': 'profile',
            'device_id': first['device_id'], 'context': deepcopy(first['context']),
            'method': 'area', 'coefficient': coefficient, 'unit': 'ml/m2', 'scope': 'whole_cycle',
            'confidence': 'measured', 'unknowns': [],
            'review': {'status': 'experimental', 'reviewer': None},
            'evidence_ids': [s['id'] for s in training],
            'provenance': [{'type': 'local_measurement', 'claim': 'Private full-to-full measured refill; not a shared approved profile'}],
            'exposure_domain': domain,
            'validation': {'training_ids': [s['id'] for s in training],
                'validation_ids': [s['id'] for s in comparable], 'device_count': 1,
                'max_error_ml': max(errors) if errors else None,
                'max_relative_error': max(relative) if relative else None}}
