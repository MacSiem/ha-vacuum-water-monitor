"""Data-only conservation engine. Source eligibility is separate from arithmetic.

Frozen dataset replays lack timed source-bound events. They exercise this engine
only through replay_synthetic; they must never be consumed as live HA events.
"""
from copy import deepcopy
import hashlib
import json
import math

RESERVOIRS = ('dock_clean', 'dock_dirty', 'robot_clean', 'robot_dirty', 'detergent')
COMPLETION = {'counter_increment', 'terminal_event'}
BINDING_STATES = {'present', 'absent', 'unsupported', 'not_applicable', 'unknown', 'source_documented_capability_dependent'}
SETTING_NAMES = ('task_scope', 'suction_level', 'carpet_policy', 'cleaning_mode',
                 'mop_mode', 'water_level', 'route', 'passes', 'wash_mode',
                 'wash_frequency', 'wash_temperature', 'adaptive_mode',
                 'detergent_mode')
SCOPE_IDENTITY = ('model_id', 'sku', 'firmware', 'integration_id',
                  'integration_version')
MAX_LIVE_AGE_MS = 120000
MAX_CLOCK_SKEW_MS = 5000
MAX_EVENTS = 2000


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(value):
    if (not isinstance(value, dict) or set(value) != {'installation_id', 'vacuum_id'}
            or any(not isinstance(v, str) or not v.strip() for v in value.values())):
        raise ValueError('missing_device_identity')
    return value


def new_balance(device_identity, reservoirs):
    identity(device_identity)
    if not isinstance(reservoirs, dict) or set(reservoirs) != set(RESERVOIRS) or any(not number(v) for v in reservoirs.values()):
        raise ValueError('invalid_initial_reservoirs')
    return {'schema_version': 2, 'device_identity': deepcopy(device_identity),
            'balances_ml': deepcopy(reservoirs), 'initial_total_ml': sum(reservoirs.values()),
            'external_supply_ml': 0, 'external_drain_ml': 0, 'events': {},
            'completed_actions': [], 'aborted_actions': []}


def apply_event(state, device_identity, event):
    """Apply an already source-validated event atomically, or reject unchanged.

    Repeated immutable event IDs are idempotent across JSON storage/restarts.
    At the retention limit stop instead of evicting identities and billing twice.
    Edges describe physical quantities even on a partial/aborted operation.
    """
    if identity(device_identity) != state.get('device_identity'):
        raise ValueError('foreign_device_identity')
    if not isinstance(event, dict) or set(event) != {'id', 'completed', 'aborted', 'completion_evidence', 'edges'}:
        raise ValueError('invalid_event_fields')
    if not isinstance(event['id'], str) or not event['id'].strip():
        raise ValueError('missing_event_identity')
    if type(event['completed']) is not bool or type(event['aborted']) is not bool:
        raise ValueError('invalid_action_flags')
    proof = event['completion_evidence']
    if not isinstance(proof, str) or proof not in COMPLETION | {'none', 'command', 'state'}:
        raise ValueError('unknown_completion_semantics')
    if event['completed'] and (event['aborted'] or proof not in COMPLETION):
        raise ValueError('unproven_completion')
    if not event['completed'] and proof in COMPLETION:
        raise ValueError('inconsistent_completion')
    digest = fingerprint(event)
    seen = state.get('events', {})
    if event['id'] in seen:
        if seen[event['id']] != digest:
            raise ValueError('conflicting_event_identity')
        return deepcopy(state)
    if len(seen) >= MAX_EVENTS:
        raise ValueError('event_retention_limit')
    if not isinstance(event['edges'], list):
        raise ValueError('invalid_edges')
    result = deepcopy(state)
    balances = result['balances_ml']
    for edge in event['edges']:
        if not isinstance(edge, dict) or set(edge) != {'from', 'to', 'amount_ml'}:
            raise ValueError('invalid_edge')
        origin, target, amount = edge['from'], edge['to'], edge['amount_ml']
        if (not isinstance(origin, str) or not isinstance(target, str)
                or origin not in RESERVOIRS + ('external_supply',)
                or target not in RESERVOIRS + ('external_drain',) or origin == target
                or not number(amount) or amount <= 0):
            raise ValueError('invalid_transfer')
        if (origin == 'detergent' and target != 'external_drain') or (target == 'detergent' and origin != 'external_supply'):
            raise ValueError('detergent_conversion_unverified')
        if origin == 'external_supply' and target == 'external_drain':
            raise ValueError('unobservable_through_flow')
        if origin in balances:
            if balances[origin] < amount:
                raise ValueError('negative_intermediate_balance')
            balances[origin] -= amount
        else:
            result['external_supply_ml'] += amount
        if target in balances:
            balances[target] += amount
        else:
            result['external_drain_ml'] += amount
    total = sum(balances.values()) + result['external_drain_ml'] - result['external_supply_ml']
    if not math.isfinite(total) or not math.isclose(total, result['initial_total_ml'], rel_tol=1e-12, abs_tol=1e-7):
        raise ValueError('conservation_failure')
    result['events'][event['id']] = digest
    if event['completed']:
        result['completed_actions'].append(event['id'])
    if event['aborted']:
        result['aborted_actions'].append(event['id'])
    return result


def validate_segments(segments):
    if not isinstance(segments, list) or not segments:
        raise ValueError('missing_setting_segments')
    last = 0
    for segment in segments:
        if (not isinstance(segment, dict) or set(segment) != {'start', 'end', 'settings_id'}
                or not number(segment['start']) or not number(segment['end'])
                or segment['start'] != last or segment['end'] <= last
                or not isinstance(segment['settings_id'], str) or not segment['settings_id']):
            raise ValueError('invalid_setting_segment')
        last = segment['end']


def replay_synthetic(replay):
    if replay.get('schema_version') != 2 or replay.get('fixture_class') != 'synthetic_accounting_replay':
        raise ValueError('not_a_synthetic_v2_replay')
    validate_segments(replay.get('setting_segments'))
    state = new_balance(replay.get('device_identity'), replay.get('initial_reservoirs'))
    for event in replay.get('events', []):
        state = apply_event(state, replay['device_identity'], event)
    if state['balances_ml'] != replay.get('expected_final_reservoirs'):
        raise ValueError('hand_calculated_balance_mismatch')
    return {**state, 'runtime_eligible': False, 'source': 'synthetic',
            'segment_accounting': 'unknown_missing_event_segment'}


def source_readiness(source):
    if source.get('schema_version') != 2 or source.get('fixture_class') != 'source_contract':
        raise ValueError('unsupported_source_contract')
    settings = {}
    for setting in source.get('settings', []):
        if setting.get('state') not in BINDING_STATES or setting.get('name') in settings:
            raise ValueError('invalid_setting_state')
        settings[setting['name']] = setting['state']
    completions = source.get('action_completion', {})
    # This inventory has no bound entity, model/firmware/version or event source
    # identity. Even a textual complete disposition cannot activate it.
    return {'settings': settings, 'action_completion': deepcopy(completions),
            'verified_completion_count': 0, 'runtime_eligible': False,
            'reason': 'missing_versioned_source_binding'}

# There are no source-backed physical event-stream bindings in the received
# dataset. Only an explicitly reviewed adapter may populate this registry.
# Device configuration and entity attributes cannot self-approve a contract.
SOURCE_CONTRACTS = ()
SOURCE_BINDINGS = ()


def consume_stream(previous, stream, *, device_identity, context, source_entity,
                   contracts, now_ms):
    """App extension: fresh, complete physical event log with timed segments.

    Complete immutable logs permit recovery after transport gaps without guessing
    missed actions. Frozen dataset fixtures do not satisfy this live envelope.
    Validation failure hides balances while retaining the last immutable journal.
    """
    previous = previous if isinstance(previous, dict) else {}
    journal = previous.get('journal')
    try:
        identity(device_identity)
        if not isinstance(stream, dict) or type(stream.get('schema_version')) is not int or stream['schema_version'] != 2 or stream.get('fixture_class') != 'physical_event_stream':
            raise ValueError('missing_physical_event_stream')
        if stream.get('device_identity') != device_identity:
            raise ValueError('foreign_device_identity')
        candidates = [c for c in contracts if c.get('id') == stream.get('source_contract_id')
                      and c.get('context') == context == stream.get('context')
                      and c.get('source_entity') == source_entity and c.get('device_identity') == device_identity]
        if len(candidates) != 1:
            raise ValueError('source_binding_unverified')
        contract = candidates[0]
        observed = stream.get('observed_at_ms')
        if not number(observed) or observed <= 0 or not number(now_ms) or not 0 <= now_ms - observed <= 120000:
            raise ValueError('stale_event_stream')
        if stream.get('complete_since_baseline') is not True:
            raise ValueError('incomplete_event_stream')
        if not isinstance(stream.get('baseline_id'), str) or not stream['baseline_id']:
            raise ValueError('missing_baseline_identity')
        baseline_time = stream.get('baseline_at_ms')
        if not number(baseline_time) or baseline_time > observed:
            raise ValueError('missing_baseline_time')
        segments = stream.get('setting_segments')
        validate_segments(segments)
        events = stream.get('events')
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError('event_retention_limit')
        baseline = {'id': stream['baseline_id'], 'baseline_at_ms': baseline_time, 'device_identity': device_identity,
                    'initial_reservoirs': stream.get('initial_reservoirs'),
                    'source_contract_id': stream['source_contract_id'], 'context': context}
        hashes = [fingerprint(e) for e in events]
        if journal:
            if journal['baseline'] != baseline or hashes[:len(journal['hashes'])] != journal['hashes']:
                raise ValueError('rewritten_or_truncated_event_stream')
            if observed < journal['observed_at_ms']:
                raise ValueError('older_event_stream')
        state = new_balance(device_identity, stream.get('initial_reservoirs'))
        segment_totals = [{**s, 'event_ids': [], 'external_supply_ml': 0,
                           'external_drain_ml': 0} for s in segments]
        assignments = []
        last_time = -1
        event_ids = set()
        for sequence, wrapper in enumerate(events, 1):
            if not isinstance(wrapper, dict) or set(wrapper) != {'sequence', 'timestamp_ms', 'settings_id', 'quantity_evidence', 'event'}:
                raise ValueError('invalid_event_envelope')
            timestamp = wrapper['timestamp_ms']
            if type(wrapper['sequence']) is not int or wrapper['sequence'] != sequence or not number(timestamp) or not last_time <= timestamp <= observed:
                raise ValueError('event_sequence_gap')
            last_time = timestamp
            matching = [s for s in segments if s['start'] <= (timestamp - baseline_time) / 1000 < s['end']]
            if len(matching) != 1 or matching[0]['settings_id'] != wrapper['settings_id']:
                raise ValueError('event_segment_mismatch')
            if wrapper['quantity_evidence'] != 'physical_ml':
                raise ValueError('unmeasured_transfer')
            event = wrapper['event']
            if not isinstance(event, dict) or event.get('id') in event_ids:
                raise ValueError('duplicate_event_identity')
            event_ids.add(event.get('id'))
            if event.get('completed') and event.get('completion_evidence') not in contract.get('completion_evidence', []):
                raise ValueError('source_completion_unverified')
            before_supply, before_drain = state['external_supply_ml'], state['external_drain_ml']
            state = apply_event(state, device_identity, event)
            segment_index = segments.index(matching[0])
            assignments.append({'index':segment_index, 'start':matching[0]['start'], 'settings_id':wrapper['settings_id']})
            totals = segment_totals[segment_index]
            totals['event_ids'].append(event['id'])
            totals['external_supply_ml'] += state['external_supply_ml'] - before_supply
            totals['external_drain_ml'] += state['external_drain_ml'] - before_drain
        if journal and assignments[:len(journal['assignments'])] != journal['assignments']:
            raise ValueError('rewritten_segment_assignment')
        return {**state, 'status': 'known', 'reason': None, 'source': 'physical_event_stream',
                'source_contract_id': contract['id'], 'segments': segment_totals,
                'journal': {'baseline': deepcopy(baseline), 'hashes': hashes, 'assignments': assignments, 'observed_at_ms': observed}}
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return {'schema_version': 2, 'status': 'unknown', 'reason': str(error),
                'source': 'unknown', 'balances_ml': None, 'journal': deepcopy(journal)}


def replay_dataset_synthetic(replay):
    """Read the frozen epoch-ms dataset replay without promoting its provenance."""
    if (replay.get('schema_version') != 2 or replay.get('fixture_class') != 'synthetic_accounting_replay'
            or replay.get('source_provenance') != 'synthetic'):
        raise ValueError('synthetic_fixture_required')
    device = replay['device_identity']
    device_id = {k:device[k] for k in ('installation_id','vacuum_id')}
    segments = replay['setting_segments']
    ids = [s['id'] for s in segments]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_setting_segment')
    baseline = replay.get('baseline_observed_at_ms')
    if type(baseline) is not int or baseline < 0:
        raise ValueError('missing_baseline_time')
    last_end = baseline
    for segment in segments:
        if (set(segment) != {'id', 'start_at_ms', 'end_at_ms', 'settings_id'}
                or type(segment['start_at_ms']) is not int
                or type(segment['end_at_ms']) is not int
                or segment['start_at_ms'] != last_end
                or segment['end_at_ms'] <= segment['start_at_ms']):
            raise ValueError('invalid_setting_segment')
        last_end = segment['end_at_ms']
    state = new_balance(device_id,replay['initial_reservoirs'])
    totals = [{**s,'event_ids':[]} for s in segments]
    last_timestamp = -1
    for sequence, event in enumerate(replay['events'],1):
        timestamp = event['observed_at_ms']
        if (type(event['sequence']) is not int or event['sequence'] != sequence
                or not number(timestamp) or timestamp < last_timestamp
                or event['quantity_provenance'] != 'synthetic' or not event['source_contract_id']):
            raise ValueError('invalid_dataset_event')
        last_timestamp = timestamp
        candidates = [i for i,s in enumerate(segments) if s['id'] == event['segment_id']
                      and s['start_at_ms'] <= timestamp < s['end_at_ms']]
        if len(candidates) != 1:
            raise ValueError('event_segment_mismatch')
        core = {k:event[k] for k in ('id','completed','aborted','completion_evidence','edges')}
        state = apply_event(state,device_id,core)
        totals[candidates[0]]['event_ids'].append(event['id'])
    if state['balances_ml'] != replay['expected_final_reservoirs']:
        raise ValueError('hand_calculated_balance_mismatch')
    return {**state,'segments':totals,'runtime_eligible':False,'source':'synthetic'}


def _matching_live_binding(contract, event, device):
    """Return one evidence-backed exact binding for a physical event."""
    if (not isinstance(contract, dict) or contract.get('fixture_class') != 'source_contract'
            or contract.get('hardware_verified') is not True
            or set(contract) != {'schema_version', 'fixture_class', 'hardware_verified',
                                 'verification', 'sources', 'bindings', 'settings',
                                 'action_completion'}
            or type(contract.get('schema_version')) is not int
            or contract['schema_version'] != 2):
        return None
    sources = contract.get('sources')
    if (not isinstance(sources, list) or not sources
            or len(sources) != len(set(sources))
            or any(not isinstance(source, str) or not source.startswith('https://')
                   for source in sources)):
        return None
    verification = contract.get('verification')
    if (not isinstance(verification, dict)
            or set(verification) != {'status', 'evidence'}
            or verification.get('status') != 'hardware_verified'):
        return None
    evidence = verification.get('evidence')
    if (not isinstance(evidence, list) or not evidence
            or any(not isinstance(item, dict)
                   or item.get('kind') not in {'registry_fixture', 'terminal_counter', 'physical_measurement'}
                   or not isinstance(item.get('source'), str)
                   or not item['source'].startswith('https://')
                   or type(item.get('recorded_at_ms')) is not int
                   for item in evidence)):
        return None
    bindings = contract.get('bindings')
    if not isinstance(bindings, list) or not bindings:
        return None
    binding_ids = set()
    for binding in bindings:
        scope = binding.get('scope') if isinstance(binding, dict) else None
        if (not isinstance(binding, dict)
                or set(binding) != {'id', 'integration', 'role', 'key', 'state',
                                    'scope', 'source'}
                or not isinstance(binding.get('id'), str) or not binding['id']
                or binding['id'] in binding_ids
                or binding.get('source') not in sources
                or binding.get('state') not in BINDING_STATES
                or not isinstance(scope, dict)
                or set(scope) != {*SCOPE_IDENTITY, 'domain', 'key', 'unit'}
                or scope.get('integration_id') != binding.get('integration')
                or scope.get('key') != binding.get('key')):
            return None
        binding_ids.add(binding['id'])
    settings = contract.get('settings')
    if (not isinstance(settings, list) or len(settings) != len(SETTING_NAMES)
            or {item.get('name') for item in settings if isinstance(item, dict)} != set(SETTING_NAMES)):
        return None
    for setting in settings:
        scope = setting.get('scope')
        if (set(setting) != {'name', 'state', 'scope'}
                or setting.get('state') not in BINDING_STATES
                or not isinstance(scope, dict)
                or set(scope) != {*SCOPE_IDENTITY, 'domain', 'key', 'unit'}
                or any(scope.get(key) != device.get(key) for key in SCOPE_IDENTITY)):
            return None
    actions = contract.get('action_completion')
    if (not isinstance(actions, dict)
            or set(actions) != {'wash_mop', 'tray_clean', 'flush', 'refill',
                                'detergent_dose'}):
        return None
    for action in actions.values():
        scope = action.get('scope') if isinstance(action, dict) else None
        if (not isinstance(action, dict)
                or set(action) != {'disposition', 'evidence', 'reason', 'scope', 'source'}
                or action.get('source') not in sources
                or not isinstance(action.get('reason'), str) or not action['reason']
                or not isinstance(scope, dict)
                or set(scope) != {*SCOPE_IDENTITY, 'domain', 'key', 'unit'}
                or any(scope.get(key) != device.get(key) for key in SCOPE_IDENTITY)
                or ((action.get('disposition') == 'complete')
                    != (action.get('evidence') in COMPLETION))):
            return None
    matches = []
    for binding in bindings:
        scope = binding.get('scope') if isinstance(binding, dict) else None
        if (binding.get('id') == event.get('source_contract_id')
                and isinstance(scope, dict)
                and all(scope.get(key) == device.get(key) for key in SCOPE_IDENTITY)
                and scope.get('unit') == 'ml'):
            matches.append(binding)
    if len(matches) != 1:
        return None
    if event.get('completed'):
        dispositions = contract.get('action_completion', {})
        proven = [item for item in dispositions.values() if isinstance(item, dict)
                  and item.get('disposition') == 'complete'
                  and item.get('evidence') == event.get('completion_evidence')
                  and isinstance(item.get('scope'), dict)
                  and all(item['scope'].get(key) == device.get(key)
                          for key in SCOPE_IDENTITY)]
        if len(proven) != 1:
            return None
    return matches[0]


def consume_dataset_live(previous, replay, *, contracts, source_bindings=(),
                         source_entity=None, now_ms):
    """Consume a native V3 physical stream or hide the last public balance."""
    previous = previous if isinstance(previous, dict) else {}
    journal = previous.get('journal')
    try:
        if (not isinstance(replay, dict) or replay.get('schema_version') != 2
                or replay.get('fixture_class') != 'physical_event_stream'
                or replay.get('source_provenance') != 'physical_ml'
                or set(replay) != {'schema_version', 'fixture_class',
                                   'source_provenance', 'baseline_id',
                                   'baseline_observed_at_ms', 'device_identity',
                                   'initial_reservoirs', 'setting_segments',
                                   'events', 'expected_final_reservoirs'}):
            raise ValueError('missing_physical_event_stream')
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError('invalid_now_ms')
        device = replay.get('device_identity')
        if (not isinstance(device, dict)
                or any(not isinstance(device.get(key), str) or not device[key]
                       for key in ('installation_id', 'vacuum_id', *SCOPE_IDENTITY))):
            raise ValueError('missing_device_identity')
        baseline_time = replay.get('baseline_observed_at_ms')
        if type(baseline_time) is not int or baseline_time < 0:
            raise ValueError('missing_baseline_time')
        if baseline_time > now_ms + MAX_CLOCK_SKEW_MS:
            raise ValueError('future_event_stream')
        segments = replay.get('setting_segments')
        if not isinstance(segments, list) or not segments:
            raise ValueError('missing_setting_segments')
        last_end = baseline_time
        segment_ids = set()
        for segment in segments:
            if (not isinstance(segment, dict)
                    or set(segment) != {'id', 'start_at_ms', 'end_at_ms', 'settings_id'}
                    or not isinstance(segment['id'], str) or not segment['id']
                    or segment['id'] in segment_ids
                    or type(segment['start_at_ms']) is not int
                    or type(segment['end_at_ms']) is not int
                    or segment['start_at_ms'] != last_end
                    or segment['end_at_ms'] <= segment['start_at_ms']):
                raise ValueError('invalid_setting_segment')
            segment_ids.add(segment['id'])
            last_end = segment['end_at_ms']
        events = replay.get('events')
        if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
            raise ValueError('invalid_event_count')
        latest = events[-1].get('observed_at_ms') if isinstance(events[-1], dict) else None
        if type(latest) is not int:
            raise ValueError('invalid_event_time')
        if latest > now_ms + MAX_CLOCK_SKEW_MS:
            raise ValueError('future_event_stream')
        if now_ms - latest > MAX_LIVE_AGE_MS:
            raise ValueError('stale_event_stream')
        baseline = {'id': replay.get('baseline_id'),
                    'baseline_observed_at_ms': baseline_time,
                    'device_identity': deepcopy(device),
                    'initial_reservoirs': deepcopy(replay.get('initial_reservoirs'))}
        if not isinstance(baseline['id'], str) or not baseline['id']:
            raise ValueError('missing_baseline_identity')
        hashes = [fingerprint(event) for event in events]
        if journal:
            if (journal.get('baseline') != baseline
                    or hashes[:len(journal.get('hashes', []))] != journal.get('hashes')):
                raise ValueError('rewritten_or_truncated_event_stream')
            if latest < journal.get('latest_observed_at_ms', -1):
                raise ValueError('older_event_stream')
        state = new_balance(
            {key: device[key] for key in ('installation_id', 'vacuum_id')},
            replay.get('initial_reservoirs'))
        totals = [{**segment, 'event_ids': [], 'external_supply_ml': 0,
                   'external_drain_ml': 0} for segment in segments]
        last_timestamp = baseline_time - 1
        seen_ids = set()
        for sequence, event in enumerate(events, 1):
            if (not isinstance(event, dict) or event.get('id') in seen_ids
                    or set(event) != {'id', 'sequence', 'observed_at_ms',
                                      'segment_id', 'source_contract_id',
                                      'quantity_provenance', 'completed', 'aborted',
                                      'completion_evidence', 'edges'}
                    or type(event.get('sequence')) is not int
                    or event['sequence'] != sequence
                    or type(event.get('observed_at_ms')) is not int
                    or event['observed_at_ms'] <= last_timestamp
                    or event.get('quantity_provenance') != 'physical_ml'):
                raise ValueError('invalid_dataset_event')
            last_timestamp = event['observed_at_ms']
            seen_ids.add(event.get('id'))
            candidates = [i for i, segment in enumerate(segments)
                          if segment['id'] == event.get('segment_id')
                          and segment['start_at_ms'] <= event['observed_at_ms'] < segment['end_at_ms']]
            if len(candidates) != 1:
                raise ValueError('event_segment_mismatch')
            binding_matches = [_matching_live_binding(contract, event, device)
                               for contract in contracts]
            bindings = [binding for binding in binding_matches if binding is not None]
            if len(bindings) != 1:
                raise ValueError('source_binding_unverified')
            entity_matches = [item for item in source_bindings
                              if isinstance(item, dict)
                              and item.get('entity_id') == source_entity
                              and item.get('contract_id') == event.get('source_contract_id')
                              and item.get('device_identity') == device]
            if len(entity_matches) != 1:
                raise ValueError('source_entity_unverified')
            core = {key: event[key] for key in
                    ('id', 'completed', 'aborted', 'completion_evidence', 'edges')}
            before_supply = state['external_supply_ml']
            before_drain = state['external_drain_ml']
            state = apply_event(
                state, {key: device[key] for key in ('installation_id', 'vacuum_id')}, core)
            totals[candidates[0]]['event_ids'].append(event['id'])
            totals[candidates[0]]['external_supply_ml'] += state['external_supply_ml'] - before_supply
            totals[candidates[0]]['external_drain_ml'] += state['external_drain_ml'] - before_drain
        if state['balances_ml'] != replay.get('expected_final_reservoirs'):
            raise ValueError('hand_calculated_balance_mismatch')
        result = {**state, 'status': 'known', 'reason': None,
                  'source': 'physical_event_stream', 'segments': totals,
                  'journal': {'baseline': baseline, 'hashes': hashes,
                              'latest_observed_at_ms': latest}}
        if previous.get('status') == 'known' and result == previous:
            return previous
        return result
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return {'schema_version': 2, 'status': 'unknown', 'reason': str(error),
                'source': 'unknown', 'balances_ml': None,
                'journal': deepcopy(journal)}
