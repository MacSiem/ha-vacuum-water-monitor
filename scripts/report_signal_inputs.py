#!/usr/bin/env python3
"""Produce an auditable, conservative inventory; this never probes devices."""
from __future__ import annotations
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'custom_components/ha_vacuum_water_monitor'

def adapters_module():
    spec = importlib.util.spec_from_file_location('vwm_signal_adapters', COMPONENT / 'integration_adapters.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Contract role => required research topic. A binding is evidence of a software
# contract, not evidence that an individual device exposes it.
ROLE_TOPICS = {
    'area_sensor': 'area', 'duration_sensor': 'time',
    'status_sensor': 'activity', 'cleaning_active_sensor': 'activity',
    'current_phase_sensor': 'activity', 'mop_mode_entity': 'mode_route_passes',
    'cleaning_mode_entity': 'mode_route_passes', 'route_entity': 'mode_route_passes',
    'passes_entity': 'mode_route_passes', 'mop_intensity_entity': 'dose_setting',
    'mop_attached_sensor': 'mop_system', 'water_box_attached_sensor': 'mop_system',
    'water_box_detached_sensor': 'mop_system', 'water_shortage_sensor': 'empty_threshold',
    'dock_clean_water_sensor': 'empty_threshold', 'dock_dirty_water_sensor': 'dirty_water',
    'dock_status_sensor': 'wash_start_end', 'dock_error_sensor': 'activity',
    'water_error_sensor': 'empty_threshold', 'tank_level_sensor': 'level_volume_counter',
    'dock_tank_level_sensor': 'level_volume_counter', 'wash_mode_entity': 'wash_program',
    'wash_frequency_entity': 'wash_frequency', 'wash_area_threshold_entity': 'wash_frequency',
    'wash_time_threshold_entity': 'wash_frequency', 'wash_temperature_entity': 'wash_temperature',
    'clean_water_tank_status_sensor': 'empty_threshold', 'dirty_water_tank_status_sensor': 'dirty_water',
    'low_water_warning_sensor': 'empty_threshold', 'drainage_status_sensor': 'water_exchange',
    'station_drainage_status_sensor': 'water_exchange',
}
TOPICS = ('level_volume_counter','area','wet_distance','time','activity','mop_system',
          'mode_route_passes','dose_setting','dose_measurement','wash_start_end',
          'wash_frequency','wash_program','wash_duration','wash_adaptive','wash_temperature',
          'transfer_to_robot','empty_threshold','water_exchange','plumbed','detergent',
          'rinse_pause','dirty_water')

def topic_for(role):
    if role in ROLE_TOPICS:
        return ROLE_TOPICS[role]
    if role.startswith('context_'):
        if any(x in role for x in ('adaptive', 'remopping', 'remop')): return 'wash_adaptive'
        if 'wash' in role and 'interval' in role: return 'wash_frequency'
        if any(x in role for x in ('pass', 'cycles')): return 'mode_route_passes'
        return 'mode_route_passes'
    return 'unclassified'

def role_info(role):
    topic = topic_for(role)
    if topic == 'area': return ('conditional_balance_input', 'area unit from entity or adapter; normalized to m²', 'robot session; not necessarily wet distance')
    if topic == 'time': return ('conditional_balance_input', 'time unit from entity or adapter; normalized to minutes', 'robot session; requires mop gate and applicable rate')
    if topic == 'level_volume_counter': return ('context', 'percent; semantics unverified', 'robot or dock; clean/dirty meaning requires model proof')
    if topic in ('empty_threshold','dirty_water'): return ('context', 'state / enum; not mL', 'clean or dirty reservoir depends on exact role; not a full-volume anchor')
    if topic == 'wash_start_end': return ('context', 'state / enum', 'dock; only explicit washing may trigger estimated wash')
    return ('context', 'state / enum or entity unit', 'robot or dock depending on role; setting/status is not measured water volume')

def report():
    a = adapters_module()
    catalog = json.loads((COMPONENT / 'model_profiles.json').read_text())
    coverage = json.loads((ROOT / 'docs/integration-coverage.json').read_text())
    inv = json.loads((ROOT / 'docs/miot-signal-inventory.json').read_text())
    contracts = {}
    for adapter, roles in sorted(a.ADAPTER_ROLE_IDENTIFIERS.items()):
        rows = []
        for role, keys in sorted(roles.items()):
            classification, unit, semantics = role_info(role)
            rows.append(dict(role=role, keys=list(keys), topic=topic_for(role), classification=classification,
                             unit=unit, reservoir_semantics=semantics,
                             runtime='integration_adapters.py binding; see docs/integration-signal-contracts.md for gate and use'))
        attrs = a.ADAPTER_ATTRIBUTE_BINDINGS.get(adapter, {})
        for key, value in sorted(attrs.items()):
            if not key.endswith('_attribute'): continue
            role = {'area_attribute':'area_sensor', 'duration_attribute':'duration_sensor',
                    'mop_intensity_attribute':'mop_intensity_entity', 'mop_attached_attribute':'mop_attached_sensor',
                    'water_box_attached_attribute':'water_box_attached_sensor','status_attribute':'status_sensor'}[key]
            classification, unit, semantics = role_info(role)
            rows.append(dict(role=key, keys=[value], topic=topic_for(role), classification=classification,
                             unit=attrs.get(key+'_unit', unit), reservoir_semantics=semantics,
                             runtime='vacuum attribute binding; see docs/integration-signal-contracts.md'))
        contracts[adapter] = {'bindings': rows, 'contract_source': 'custom_components/ha_vacuum_water_monitor/integration_adapters.py',
             'interpretation_source': 'docs/integration-signal-contracts.md',
             'freshness': 'repository revision; upstream and installed device not rechecked',
             'availability': 'unknown: binding does not prove model, dock or firmware exposes entity'}
    models = []
    for key, p in sorted(catalog['profiles'].items()):
        # Deliberately no expansion of adapter bindings into model capabilities.
        models.append(dict(id=key, manufacturer=p.get('manufacturer'), model=p.get('model'),
            model_ids=p.get('model_ids'), regional_skus=p.get('regional_skus'), firmware='unknown: not established by catalog',
            dock_variant='unknown: model-specific station binding not established by this report',
            adapters=p.get('integration_adapters', []), catalog_signals=p.get('available_signals', []),
            reservoirs_ml=p.get('reservoirs_ml'), tracked_reservoir=p.get('tracked_reservoir'),
            last_verified=p.get('last_verified'), provenance=p.get('provenance', []),
            unsupported_unknowns=p.get('unsupported_unknowns', []),
            topics={topic: {'classification':'unknown', 'reason':'No model-and-firmware-specific signal presence and semantics verified by this report; consult adapter contract and source evidence.'} for topic in TOPICS}))
    unknown = sum(len(m['topics']) for m in models)
    miot_models = inv['models']
    audit = {'source':'docs/miot-signal-inventory.json', 'cutoff_date':inv['cutoff_date'],
             'method':inv['method'], 'limitations':inv['limitations'], 'model_count':len(miot_models),
             'status_counts':dict(Counter(m.get('status','unknown') for m in miot_models)),
             'models_with_candidates':sum(bool(m.get('volume_candidates')) for m in miot_models),
             'models_with_verified_ha_binding':sum(m.get('ha_entity_binding') == 'verified' for m in miot_models),
             'entries':[{'model_id':m['model_id'], 'spec_urn':m.get('spec_urn'), 'source':m.get('url'),
                 'spec_revision_ts':m.get('spec_revision_ts'), 'status':m.get('status'), 'ha_entity_binding':m.get('ha_entity_binding'),
                 'properties':m.get('properties'), 'actions':m.get('actions'), 'volume_candidates':m.get('volume_candidates'),
                 'unknowns':m.get('unknowns')} for m in miot_models]}
    return {'schema_version':1, 'scope':'software contracts and catalog research; not installed-device or hardware verification',
            'catalog_source':'custom_components/ha_vacuum_water_monitor/model_profiles.json', 'catalog_cutoff':catalog['cutoff_date'],
            'integration_inventory_source':'docs/integration-coverage.json', 'integration_inventory_cutoff':coverage['cutoff_date'],
            'integration_inventory':coverage['integrations'], 'adapter_contracts':contracts, 'models':models,
            'gaps':{'model_topic_unknown':unknown, 'models':len(models), 'topics':len(TOPICS),
                    'unclassified_contract_roles':sum(r['topic']=='unclassified' for c in contracts.values() for r in c['bindings'])},
            'miot_inventory_audit':audit}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', action='store_true', help='print counts instead of full JSON')
    args = parser.parse_args()
    result = report()
    print(json.dumps({'gaps':result['gaps'], 'adapters':len(result['adapter_contracts']),
                      'miot_inventory':{k:v for k,v in result['miot_inventory_audit'].items() if k != 'entries'}} if args.summary else result,
                     ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
