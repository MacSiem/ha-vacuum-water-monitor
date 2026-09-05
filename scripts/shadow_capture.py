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

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--secrets-file',required=True);ap.add_argument('--days',type=int,default=7);args=ap.parse_args()
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
    history=get('/api/history/period/'+start+'?'+urlencode({'filter_entity_id':','.join(ids),'significant_changes_only':'false'}))
    events=[]
    for series in history:
        for sample in series:
            if sample.get('entity_id') in ids and sample.get('last_updated'):
                events.append((sample['last_updated'],ids[sample['entity_id']],sanitized(sample)))
    events.sort(key=lambda row:row[0]);samples={};tanks={};reasons=Counter();methods=Counter();active=0
    hass=types.SimpleNamespace(states=types.SimpleNamespace(get=samples.get),config=types.SimpleNamespace(units=types.SimpleNamespace(length_unit='km')))
    for stamp,entity,value in events:
        samples[entity]=value
        for device in effective:
            device=calc.apply_custom_calibration(device,{})
            key=device['vacuum_entity'];state=tanks.get(key,{'used_ml':0})
            state,_=tick.tick_device(hass,device,state,now_ts=int(datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()*1000));tanks[key]=state
            reasons[str(state.get('last_accounting_reason') or 'none')]+=1
            methods[str(state.get('last_accounting_source') or 'unknown')]+=1
        active+=value.state in {'cleaning','mopping','segment_mopping','washing_the_mop'}
    print(json.dumps({'read_only':True,'raw_identifiers_retained':False,'stored_calibration_audit':calibration_audit,'days':args.days,'vacuum_count':len(vacuums),'linked_entities':len(relevant),'history_samples':len(events),'active_samples':active,'adapters':sorted({d.get('integration_adapter','unknown') for d in effective}),'reason_counts':dict(reasons),'method_counts':dict(methods),'predicted_ml':None,'observed_ml':None,'comparison':'blocked_measured_same_reservoir_volume_and_calibration_required'},indent=2))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'read_only':True,'error_type':type(exc).__name__,'detail':'Capture failed; no raw server response or identifiers emitted.'}));sys.exit(1)
