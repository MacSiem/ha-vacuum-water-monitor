"""Conservative two-action fit over independently measured private cycles.

This module does not collect observations or change runtime accounting. Callers
must establish the provenance and continuity of every observation first.
"""
from math import isfinite


def _number(value, *, positive=False):
    return (type(value) in (int, float) and isfinite(value)
            and (value > 0 if positive else value >= 0))


def fit(samples, identity=None):
    """Fit floor ml/m² and completed-wash ml for one pair of action contexts.

    At least three training cycles, a full-rank well-conditioned design, and a
    separate passing validation cycle are required. All observations must have
    been independently measured, with explicit quality and identity evidence.
    """
    if not isinstance(samples, list) or len(samples) < 4:
        return None
    required = {'boundaries_confirmed': True, 'uninterrupted': True,
                'exposure_complete': True, 'settings_constant': True,
                'same_reservoir': True, 'intervening_refill': False,
                'unmeasured_transfer': False}
    if any(not isinstance(s, dict) or s.get('quality') != required for s in samples):
        return None
    ids = [s.get('id') for s in samples]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        return None
    identity = identity if identity is not None else samples[0].get('identity')
    if not isinstance(identity, dict) or any(not identity.get(k) for k in
            ('robot', 'station', 'reservoir', 'floor_context', 'wash_context')):
        return None
    if any(s.get('source') not in ('measured_refill', 'bound_reservoir_sensor')
           or s.get('purpose') not in ('training', 'validation') for s in samples):
        return None
    for s in samples:
        if (not _number(s.get('area_m2')) or not _number(s.get('wash_count'))
                or not float(s['wash_count']).is_integer()
                or not _number(s.get('observed_ml'), positive=True)
                or not _number(s.get('resolution_ml'), positive=True)
                or s['resolution_ml'] >= s['observed_ml']
                or not (s['area_m2'] or s['wash_count'])):
            return None
        other = s.get('identity')
        if (not isinstance(other, dict)
                or any(other.get(k) != identity[k] for k in ('robot', 'station', 'reservoir'))
                or (s['area_m2'] > 0 and other.get('floor_context') != identity['floor_context'])
                or (s['wash_count'] > 0 and other.get('wash_context') != identity['wash_context'])):
            return None
    train = [s for s in samples if s['purpose'] == 'training']
    holdout = [s for s in samples if s['purpose'] == 'validation']
    if len(train) < 3 or not holdout:
        return None
    aa = sum(s['area_m2'] ** 2 for s in train)
    ww = sum(s['wash_count'] ** 2 for s in train)
    aw = sum(s['area_m2'] * s['wash_count'] for s in train)
    # Reject near-collinearity as well as exact rank deficiency.
    determinant = aa * ww - aw * aw
    if not aa or not ww or determinant <= 0.05 * aa * ww:
        return None
    ay = sum(s['area_m2'] * s['observed_ml'] for s in train)
    wy = sum(s['wash_count'] * s['observed_ml'] for s in train)
    floor = (ay * ww - wy * aw) / determinant
    wash = (wy * aa - ay * aw) / determinant
    if not _number(floor, positive=True) or not _number(wash, positive=True):
        return None
    # Bound every residual, not merely an average that can hide outliers.
    def agrees(s):
        prediction = floor * s['area_m2'] + wash * s['wash_count']
        return abs(prediction - s['observed_ml']) <= max(
            2 * s['resolution_ml'], 0.2 * s['observed_ml'])
    if not all(agrees(s) for s in samples):
        return None
    return {'version': 1, 'identity': identity.copy(), 'floor_ml_per_m2': floor,
            'wash_ml_per_completed_action': wash,
            'training_ids': [s['id'] for s in train],
            'validation_ids': [s['id'] for s in holdout]}


def resolve(samples, identity):
    """Resolve private, independently validated rates for the requested contexts.

    Pure actions can qualify without a matching partner action. Mixed cycles
    qualify only as a full-rank pair. Never merge identities or duplicate IDs.
    """
    from statistics import median
    result = {'floor_ml_per_m2': None, 'wash_ml_per_completed_action': None}
    if not isinstance(samples, list) or not isinstance(identity, dict):
        return result
    ids = [s.get('id') for s in samples if isinstance(s, dict)]
    duplicate = {i for i in ids if isinstance(i, str) and ids.count(i) > 1}
    required = {'boundaries_confirmed': True, 'uninterrupted': True,
                'exposure_complete': True, 'settings_constant': True,
                'same_reservoir': True, 'intervening_refill': False,
                'unmeasured_transfer': False}
    if any(not identity.get(k) for k in ('robot', 'station', 'reservoir', 'floor_context', 'wash_context')):
        return result
    eligible = []
    for s in samples:
        if not isinstance(s, dict) or not isinstance(s.get('id'), str) or not s['id'] or s['id'] in duplicate:
            continue
        other = s.get('identity')
        if (not isinstance(other, dict) or any(other.get(k) != identity[k] for k in ('robot', 'station', 'reservoir'))
                or s.get('quality') != required or s.get('source') not in ('measured_refill', 'bound_reservoir_sensor')
                or s.get('purpose') not in ('training', 'validation')
                or not _number(s.get('area_m2')) or not _number(s.get('wash_count'))
                or not float(s['wash_count']).is_integer() or not _number(s.get('observed_ml'), positive=True)
                or not _number(s.get('resolution_ml'), positive=True) or s['resolution_ml'] >= s['observed_ml']
                or not (s['area_m2'] or s['wash_count'])
                or (s['area_m2'] and other.get('floor_context') != identity['floor_context'])
                or (s['wash_count'] and other.get('wash_context') != identity['wash_context'])):
            continue
        eligible.append(s)
    mixed = fit(eligible, identity)
    if mixed:
        result.update({k: mixed[k] for k in result})
    for key, exposure, inactive in (('floor_ml_per_m2', 'area_m2', 'wash_count'),
                                     ('wash_ml_per_completed_action', 'wash_count', 'area_m2')):
        pure = [s for s in eligible if s[inactive] == 0 and s[exposure] > 0]
        training = [s for s in pure if s['purpose'] == 'training']
        validation = [s for s in pure if s['purpose'] == 'validation']
        if len(training) < 3 or not validation:
            continue
        rate = median(s['observed_ml'] / s[exposure] for s in training)
        if all(abs(rate * s[exposure] - s['observed_ml']) <= max(2*s['resolution_ml'], .2*s['observed_ml'])
               for s in pure):
            result[key] = rate
    return result
