#!/usr/bin/env python3
"""Read-only HA shadow replay. Raw registry/history stay in memory; output aggregates only."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ALLOWED_WS = {'config/entity_registry/list','config/device_registry/list','ha_vacuum_water_monitor/get_state'}
def load_env(path):
    out={}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);out[key.strip()]=value.strip().strip('\"\'')
    return out

def modules():
    root=Path(__file__).resolve().parents[1]
    pkg=types.ModuleType('vwmshadow');pkg.__path__=[str(root/'custom_components/ha_vacuum_water_monitor')];sys.modules['vwmshadow']=pkg
    core=types.ModuleType('homeassistant.core');core.HomeAssistant=object
    sys.modules.setdefault('homeassistant',types.ModuleType('homeassistant'));sys.modules.setdefault('homeassistant.core',core)
    storage=types.ModuleType('vwmshadow.storage');storage.VacuumWaterStorage=object;sys.modules['vwmshadow.storage']=storage
    import importlib
    return [importlib.import_module('vwmshadow.'+name) for name in ('discovery','sensor_calculations','tick')]

def _ms(stamp):
    return int(datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).timestamp() * 1000)


def _minute(ts):
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%MZ')


def _increments(series, start_ts, end_ts):
    """Water counted by a reference counter inside a window; a drop is a reset."""
    total, previous = 0.0, None
    for ts, value in series:
        if ts > end_ts:
            break
        if previous is not None and ts >= start_ts and value > previous:
            total += value - previous
        previous = value
    return round(total, 1)


def replay(events, devices, calc, tick, *, poll_seconds=0, compare=None, settings=None):
    """Replay recorded states through the accounting engine.

    ``events`` are (ts_ms, entity_id, state) sorted by time. ``poll_seconds=0``
    ticks on every change like the event-driven integration; a positive value
    ticks only on that period, like the heartbeat alone. ``compare`` is an
    optional [(ts_ms, value)] series of a reference counter (for example the
    DIY input_number) compared per session.
    """
    samples, tanks, reasons = {}, {}, Counter()
    dock_transitions, levels, modes = [], Counter(), Counter()
    hass = types.SimpleNamespace(states=types.SimpleNamespace(get=samples.get),
                                 config=types.SimpleNamespace(units=types.SimpleNamespace(length_unit='km')))
    effective = [calc.apply_custom_calibration(device, settings or {}) for device in devices]

    def observe(entity, value, ts):
        previous = samples.get(entity)
        samples[entity] = value
        for device in effective:
            if entity == device.get('dock_error_sensor') and (previous is None or previous.state != value.state):
                dock_transitions.append({'at': _minute(ts), 'from': previous.state if previous else None, 'to': value.state})

    def run_tick(ts):
        for device in effective:
            key = device['vacuum_entity']
            state, _ = tick.tick_device(hass, device, tanks.get(key, {'used_ml': 0, 'initialized': True}), now_ts=ts)
            tanks[key] = state
            reasons[str(state.get('last_accounting_reason') or 'none')] += 1
            status = samples.get(device.get('status_sensor'))
            if status is not None and status.state in tick._ACTIVE_CLEANING_STATES:
                for counter, role in ((levels, 'mop_intensity_entity'), (modes, 'mop_mode_entity')):
                    sample = samples.get(device.get(role))
                    if sample is not None:
                        counter[sample.state] += 1

    if poll_seconds and events:
        index, ts, last = 0, events[0][0], events[-1][0]
        while ts <= last + poll_seconds * 1000:
            while index < len(events) and events[index][0] <= ts:
                observe(events[index][1], events[index][2], events[index][0])
                index += 1
            run_tick(ts)
            ts += poll_seconds * 1000
    else:
        for ts, entity, value in events:
            observe(entity, value, ts)
            run_tick(ts)

    result = {'mode': f'poll_{poll_seconds}s' if poll_seconds else 'event_driven', 'vacuums': []}
    for device in effective:
        state = tanks.get(device['vacuum_entity'], {})
        sessions = []
        for record in reversed(state.get('automatic_sessions') or []):
            row = {'start': _minute(record['started_ts']), 'minutes': record.get('duration'),
                   'area_m2': record.get('area'), 'vwm_ml': record.get('water'), 'valid': record.get('accounting_valid')}
            if compare:
                row['reference_ml'] = _increments(compare, record['started_ts'], record['ts'])
                if row['vwm_ml'] is not None and row['reference_ml']:
                    row['difference_percent'] = round((row['vwm_ml'] - row['reference_ml']) / row['reference_ml'] * 100, 1)
            sessions.append(row)
        result['vacuums'].append({
            'profile': device.get('profile_key'), 'estimate_basis': device.get('estimate_basis'),
            'final_used_ml': state.get('used_ml'), 'accounting_incomplete': bool(state.get('accounting_incomplete')),
            'sessions': sessions,
            'empty_tanks': [{**{k: v for k, v in t.items() if k != 'ts'}, 'at': _minute(t['ts'])} for t in reversed(state.get('calibration_history') or [])],
            'refills': [{'at': _minute(r['ts']), 'source': r.get('source'), 'used_before_ml': r.get('used_before_ml')} for r in reversed(state.get('refill_history') or [])],
            'calibration_factor': state.get('calibration_factor'), 'calibration_samples': state.get('calibration_samples'),
            'bridged_gaps': state.get('bridged_gaps') or 0,
        })
    result.update(dock_error_transitions=dock_transitions, water_levels_while_cleaning=dict(levels),
                  mop_modes_while_cleaning=dict(modes), reason_counts=dict(reasons))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--secrets-file',required=True);ap.add_argument('--days',type=int,default=7)
    ap.add_argument('--poll-seconds',type=int,default=0,help='0 = tick on every change (the integration since 5.7.0-beta.2); 60 = heartbeat only')
    ap.add_argument('--compare-entity',help='numeric reference counter to compare per session, e.g. the DIY input_number (never printed)')
    args=ap.parse_args()
    env=load_env(args.secrets_file);base=env['HA_URL'].rstrip('/');token=env['HA_TOKEN']
    def get(path):
        if not path.startswith(('/api/states','/api/history/period/')):raise ValueError('read endpoint not allowed')
        req=Request(base+path,headers={'Authorization':'Bearer '+token},method='GET')
        with urlopen(req,timeout=45) as response:return json.load(response)
    from websockets.sync.client import connect
    with connect(base.replace('http://','ws://').replace('https://','wss://')+'/api/websocket',open_timeout=15, max_size=32*1024*1024) as ws:
        ws.recv();ws.send(json.dumps({'type':'auth','access_token':token}));assert json.loads(ws.recv())['type']=='auth_ok'
        def read_registry(kind,ident):
            assert kind in ALLOWED_WS
            ws.send(json.dumps({'id':ident,'type':kind}));result=json.loads(ws.recv())
            if not result.get('success'):raise ValueError('registry read failed')
            return result['result']
        entities=read_registry('config/entity_registry/list',1);devices=read_registry('config/device_registry/list',2)
        try:
            stored=read_registry('ha_vacuum_water_monitor/get_state',3)
            calibrations=(stored.get('settings') or {}).get('custom_calibration') or {}
            calibration_audit={'readable':True,'calibration_records':len(calibrations),'records_with_measurement_provenance':sum(bool(v.get('sample_count') and v.get('provenance')) for v in calibrations.values() if isinstance(v,dict))}
        except ValueError:
            calibration_audit={'readable':False,'reason':'readonly_store_endpoint_unavailable'}
    states=get('/api/states');state_map={s['entity_id']:s for s in states}
    vacuums=[e for e in entities if e['entity_id'].startswith('vacuum.') and not e.get('disabled_by')]
    wanted_devices={e['device_id'] for e in vacuums}
    relevant=[e for e in entities if e.get('device_id') in wanted_devices and not e.get('disabled_by')]
    device_ids={d:'device_'+str(i) for i,d in enumerate(sorted(wanted_devices)) if d}
    ids={e['entity_id']:e['entity_id'].split('.')[0]+'.sample_'+str(i) for i,e in enumerate(relevant)}
    clean_entities=[{k:v for k,v in e.items() if k in {'platform','translation_key','original_device_class','device_class'}} | {'entity_id':ids[e['entity_id']],'device_id':device_ids.get(e.get('device_id'))} for e in relevant]
    clean_devices=[{'id':device_ids[d['id']],'manufacturer':d.get('manufacturer'),'model':d.get('model'),'model_id':d.get('model_id')} for d in devices if d['id'] in device_ids]
    safe_attributes={'unit_of_measurement','status','cleaned_area','cleaning_time','fan_speed','tank_present'}
    def sanitized(s):return types.SimpleNamespace(state=s['state'],attributes={k:v for k,v in s.get('attributes',{}).items() if k in safe_attributes})
    clean_states={ids[k]:sanitized(s) for k,s in state_map.items() if k in ids}
    discovery,calc,tick=modules();descriptors=discovery.discover_descriptors(clean_entities,clean_devices,clean_states)
    effective=calc.build_vacuum_devices({}, {},descriptors)
    start=(datetime.now(timezone.utc)-timedelta(days=max(1,min(args.days,30)))).isoformat()
    wanted=list(ids)+([args.compare_entity] if args.compare_entity else [])
    history=get('/api/history/period/'+start+'?'+urlencode({'filter_entity_id':','.join(wanted),'significant_changes_only':'false'}))
    events=[];compare=[]
    for series in history:
        for sample in series:
            entity=sample.get('entity_id')
            if not sample.get('last_updated'):
                continue
            if entity in ids:
                events.append((_ms(sample['last_updated']),ids[entity],sanitized(sample)))
            elif args.compare_entity and entity==args.compare_entity:
                try:compare.append((_ms(sample['last_updated']),float(sample['state'])))
                except (TypeError,ValueError):pass
    events.sort(key=lambda row:row[0]);compare.sort()
    report=replay(events,effective,calc,tick,poll_seconds=max(0,args.poll_seconds),compare=compare or None)
    print(json.dumps({'read_only':True,'raw_identifiers_retained':False,'stored_calibration_audit':calibration_audit,'days':args.days,
                      'vacuum_count':len(vacuums),'linked_entities':len(relevant),'history_samples':len(events),
                      'adapters':sorted({d.get('integration_adapter','unknown') for d in effective}),**report},indent=2))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'read_only':True,'error_type':type(exc).__name__,'detail':'Capture failed; no raw server response or identifiers emitted.'}));sys.exit(1)
