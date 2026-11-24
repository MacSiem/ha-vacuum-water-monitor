"""Local whole-session fits from a bound reservoir level and observed area.

A reservoir level cannot identify individual floor or dock doses.  Fits in this
bank therefore describe total reservoir draw per complete session area only.
They are diagnostic while the bound physical sensor remains authoritative.
"""
from copy import deepcopy
from statistics import median
import math


def _positive(value, zero=False):
    return type(value) in (int, float) and math.isfinite(value) and (value >= 0 if zero else value > 0)


def observe(state, *, context, binding, reservoir, area, volume, now, session_id,
            running, complete, valid, reason=None, max_area_delta=None):
    """Consume a real sensor tick; all boundaries must be continuously observed."""
    state = deepcopy(state) if isinstance(state, dict) else {}
    state.setdefault('version', 1)
    state.setdefault('contexts', [])
    state.setdefault('cycle', None)
    state.setdefault('reason', None)
    cycle = state['cycle']
    identity = {'context': context, 'binding': binding, 'reservoir': reservoir}
    if reason or not valid or not _positive(area, True) or not _positive(volume, True):
        state.update(cycle=None, blocked_session_id=session_id, reason=reason or 'physical_exposure_unavailable')
        return state
    if cycle is not None:
        if (not isinstance(cycle, dict) or not _positive(cycle.get('last_ts'))
                or not _positive(cycle.get('last_area'), True)
                or not _positive(cycle.get('last_volume'), True)
                or not _positive(cycle.get('start_area'), True)
                or not _positive(cycle.get('start_volume'), True)):
            state.update(cycle=None, blocked_session_id=session_id, reason='physical_invalid_saved_observation')
            return state
        problem = None
        if cycle.get('identity') != identity:
            problem = 'physical_context_or_binding_changed'
        elif session_id != cycle.get('session_id') or not complete:
            problem = 'physical_session_incomplete'
        elif not _positive(now) or now < cycle['last_ts'] or now - cycle['last_ts'] > 180000:
            problem = 'physical_observation_gap'
        elif area < cycle['last_area']:
            problem = 'physical_exposure_reset'
        elif _positive(max_area_delta) and area - cycle['last_area'] > max_area_delta:
            problem = 'physical_exposure_anomaly'
        elif volume > cycle['last_volume']:
            problem = 'physical_refill_or_level_increase'
        if problem:
            state.update(cycle=None, blocked_session_id=session_id, reason=problem)
            return state
        cycle.update(last_ts=now, last_area=area, last_volume=volume)
        if not running:
            draw, exposure = cycle['start_volume'] - volume, area - cycle['start_area']
            if not _positive(draw) or not _positive(exposure):
                state.update(cycle=None, reason='physical_no_observed_draw_or_exposure')
                return state
            entries = state['contexts'] if isinstance(state['contexts'], list) else []
            entry = next((e for e in entries if isinstance(e, dict) and e.get('identity') == identity), None)
            if entry is None:
                entry = {'identity': identity, 'samples': [], 'pending': []}
            else:
                entries.remove(entry)
            def clean(items):
                return [s for s in items if isinstance(s, dict) and _positive(s.get('rate'))
                        and _positive(s.get('area')) and _positive(s.get('draw'))
                        and math.isclose(s['rate'], s['draw'] / s['area'], rel_tol=1e-9)][-8:] if isinstance(items, list) else []
            def agrees(samples):
                return len(samples) >= 3 and max(s['rate'] for s in samples[-3:]) / min(s['rate'] for s in samples[-3:]) <= 1.25
            samples, pending = clean(entry.get('samples')), clean(entry.get('pending'))
            sample = {'draw': draw, 'area': exposure, 'rate': draw / exposure, 'finished_ts': now}
            candidate = [*samples, sample][-8:]
            if agrees(samples) and not agrees(candidate):
                pending = [*pending, sample][-3:]
                if agrees(pending):
                    samples, pending, state['reason'] = pending, [], 'physical_shift_confirmed'
                else:
                    state['reason'] = 'physical_outlier_pending'
            else:
                samples, pending, state['reason'] = candidate, [], 'physical_sample_accepted'
            entry.update(samples=samples, pending=pending)
            entries.append(entry)
            state.update(contexts=entries[-32:], cycle=None)
        return state
    if running and session_id and session_id != state.get('blocked_session_id') and complete and area == 0:
        state.update(cycle={'identity': identity, 'session_id': session_id, 'start_area': area,
                            'start_volume': volume, 'last_area': area, 'last_volume': volume,
                            'last_ts': now}, reason='physical_observation_in_progress')
    elif running:
        state['reason'] = 'physical_start_boundary_unobserved'
    return state


def resolution(state, *, context, binding, reservoir):
    state = state if isinstance(state, dict) else {}
    identity = {'context': context, 'binding': binding, 'reservoir': reservoir}
    entries = state.get('contexts') if isinstance(state.get('contexts'), list) else []
    entry = next((e for e in reversed(entries) if isinstance(e, dict) and e.get('identity') == identity), {})
    samples = entry.get('samples') if isinstance(entry.get('samples'), list) else []
    samples = [s for s in samples if isinstance(s, dict) and _positive(s.get('rate')) and _positive(s.get('draw'))
               and _positive(s.get('area')) and _positive(s.get('finished_ts')) and math.isclose(s['rate'], s['draw']/s['area'], rel_tol=1e-9)][-8:]
    active = len(samples) >= 3 and max(s['rate'] for s in samples[-3:]) / min(s['rate'] for s in samples[-3:]) <= 1.25
    return {'status': 'active' if active else 'provisional' if samples else 'unavailable',
            'source': 'bound_reservoir_volume_sensor', 'scope': 'whole_session',
            'basis': 'measured_reservoir_draw_per_session_area', 'reason': state.get('reason'),
            'sample_count': len(samples), 'pending_count': len(entry.get('pending') or []),
            'coefficient_ml_per_m2': median(s['rate'] for s in samples[-3:]) if active else None,
            'application': 'physical_sensor_authoritative'}


def profile(state, *, context, binding, reservoir):
    """Return a bounded private whole-session record for the ordinary resolver."""
    result = resolution(state, context=context, binding=binding, reservoir=reservoir)
    if result['status'] != 'active' or not isinstance(context, dict):
        return None
    identity = {'context': context, 'binding': binding, 'reservoir': reservoir}
    entry = next((e for e in reversed(state.get('contexts') or [])
                  if isinstance(e, dict) and e.get('identity') == identity), None)
    if entry is None:
        return None
    samples = entry.get('samples') or []
    samples = [s for s in samples if isinstance(s, dict) and _positive(s.get('rate'))
               and _positive(s.get('draw')) and _positive(s.get('area')) and _positive(s.get('finished_ts'))
               and math.isclose(s['rate'], s['draw']/s['area'], rel_tol=1e-9)][-3:]
    if len(samples) != 3:
        return None
    return {'id': 'local.automatic_physical', 'kind': 'profile',
            'device_id': context.get('device_id'), 'context': deepcopy(context),
            'method': 'area', 'coefficient': result['coefficient_ml_per_m2'],
            'unit': 'ml/m2', 'scope': 'whole_cycle', 'confidence': 'measured',
            'unknowns': [], 'review': {'status': 'experimental'},
            'evidence_ids': [f"physical.{sample['finished_ts']}" for sample in samples],
            'provenance': [{'type': 'automatic_reservoir_sensor',
                            'claim': 'Private measured whole-session reservoir draw'}],
            'exposure_domain': {'min': min(s['area'] for s in samples),
                                'max': max(s['area'] for s in samples)}}
