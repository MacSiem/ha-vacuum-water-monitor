"""Inventory invariants: software contracts must not imply hardware availability."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('signal_report', ROOT / 'scripts/report_signal_inputs.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_every_live_adapter_and_binding_is_in_report():
    data = mod.report()
    source = mod.adapters_module()
    assert set(data['adapter_contracts']) == set(source.ADAPTER_ROLE_IDENTIFIERS)
    for adapter, roles in source.ADAPTER_ROLE_IDENTIFIERS.items():
        rows = {r['role']: r for r in data['adapter_contracts'][adapter]['bindings']}
        for role, keys in roles.items():
            assert rows[role]['keys'] == list(keys), (adapter, role)
            assert rows[role]['topic'] != 'unclassified', (adapter, role)
            assert rows[role]['reservoir_semantics']
        assert 'unknown' in data['adapter_contracts'][adapter]['availability']


def test_catalog_and_inventory_are_distinct_and_fail_closed():
    data = mod.report()
    assert data['gaps']['model_topic_unknown'] == len(data['models']) * len(mod.TOPICS)
    assert all(set(m['topics']) == set(mod.TOPICS) for m in data['models'])
    assert all(v['classification'] == 'unknown' and v['reason'] for m in data['models'] for v in m['topics'].values())
    assert all(m['firmware'].startswith('unknown') and m['dock_variant'].startswith('unknown') for m in data['models'])
    audit = data['miot_inventory_audit']
    assert audit['model_count'] == len(audit['entries'])
    assert sum(audit['status_counts'].values()) == audit['model_count']
    assert all(e['source'] and e['status'] for e in audit['entries'])


def test_distinct_contracts_do_not_confuse_reservoirs_or_dose():
    c = mod.report()['adapter_contracts']
    for adapter in c.values():
        for row in adapter['bindings']:
            if row['topic'] in {'dose_setting', 'empty_threshold', 'dirty_water'}:
                assert row['classification'] == 'context'
    assert next(r for r in c['roborock']['bindings'] if r['role'] == 'dock_dirty_water_sensor')['topic'] == 'dirty_water'
    assert next(r for r in c['dreame_vacuum']['bindings'] if r['role'] == 'wash_temperature_entity')['topic'] == 'wash_temperature'
    assert next(r for r in c['tapo_rv30']['bindings'] if r['role'] == 'area_attribute')['unit'] == 'm²'
    assert next(r for r in c['roomba']['bindings'] if r['role'] == 'area_attribute')['unit'] == 'ha_unit_system'
