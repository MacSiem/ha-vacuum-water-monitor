"""Issue 32: reported IDs plus upstream registry keys, not a live registry dump.

Upstream entity.py derives translation_key from the description key and IDs from
<device>_<key>; original_name is localized and report does not provide it.
States and entity availability/disabled flags in the report are unknown.
"""
from test_beta_runtime_path import discovery, effective, tick, _Hass, _S

KEYS = {
    'sensor.saubi_state': 'state', 'sensor.saubi_cleaned_area': 'cleaned_area',
    'sensor.saubi_cleaning_time': 'cleaning_time', 'sensor.saubi_mop_pad': 'mop_pad',
    'sensor.saubi_error': 'error', 'sensor.saubi_self_wash_base_status': 'self_wash_base_status',
    'select.saubi_cleaning_mode': 'cleaning_mode', 'select.saubi_mop_pad_humidity': 'mop_pad_humidity',
    'sensor.saubi_clean_water_tank_status': 'clean_water_tank_status',
    'sensor.saubi_dirty_water_tank_status': 'dirty_water_tank_status',
    'sensor.saubi_low_water_warning': 'low_water_warning',
    'sensor.saubi_drainage_status': 'drainage_status',
    'sensor.saubi_station_drainage_status': 'station_drainage_status',
    'select.saubi_washing_mode': 'washing_mode', 'select.saubi_self_clean_frequency': 'self_clean_frequency',
    'number.saubi_self_clean_area': 'self_clean_area', 'number.saubi_self_clean_time': 'self_clean_time',
    'select.saubi_water_temperature': 'water_temperature', 'number.saubi_wetness_level': 'wetness_level',
    **{f'select.saubi_{k}': k for k in ('cleaning_route', 'auto_rewashing', 'auto_recleaning', 'cleangenius', 'cleangenius_mode')},
    **{f'switch.saubi_{k}': k for k in ('smart_mop_washing', 'auto_water_refilling', 'customized_cleaning', 'mop_washing_with_detergent', 'mopping_with_detergent', 'auto_mount_mop')},
}

def descriptor():
    entities = [{'entity_id':'vacuum.saubi', 'platform':'dreame_vacuum', 'device_id':'d', 'unique_id':'mac'}]
    entities += [{'entity_id': entity, 'platform':'dreame_vacuum', 'device_id':'d',
                  'unique_id':'mac_'+key, 'translation_key':key,
                  'original_name':key.replace('_', ' ').title()} for entity,key in KEYS.items()]
    return discovery.discover_descriptors(entities, [{'id':'d', 'manufacturer':'Dreametech',
        'model':'dreame.vacuum.r2538z'}], {})[0]

def test_reported_registry_contract_and_upgrade_preserves_user_binding():
    desc = descriptor(); signals = desc['signals']
    for role, entity in {'status_sensor':'sensor.saubi_state', 'area_sensor':'sensor.saubi_cleaned_area',
        'duration_sensor':'sensor.saubi_cleaning_time', 'mop_attached_sensor':'sensor.saubi_mop_pad',
        'mop_intensity_entity':'select.saubi_mop_pad_humidity',
        'clean_water_tank_status_sensor':'sensor.saubi_clean_water_tank_status'}.items():
        assert signals[role] == entity
    assert 'dock_clean_water_sensor' not in signals
    device = effective({}, desc)
    assert device['mop_system'] == 'rotating_pads'
    assert device['usage_ml_per_m2'] == {}
    assert device.get('wash_volume_ml') is None
    settings = {'configured_devices':[{'vacuum_entity':'vacuum.saubi', 'area_sensor':'sensor.manual_area'}]}
    assert effective(settings, desc)['area_sensor'] == 'sensor.manual_area'

def test_tank_status_is_not_volume_or_refill_anchor():
    entity = 'sensor.saubi_clean_water_tank_status'
    device = {'dock_clean_water_sensor':entity, 'tracked_reservoir':'dock_clean'}
    for value in ('installed', 'not_installed', 'low_water', 'unknown'):
        hass = _Hass({entity:_S(value)})
        assert tick._water_anchor_states(hass, device, None)['dock_clean_water'][0] is None
        state = {}
        assert tick._observe_user_refill_signals(hass, device, state, 1000)[0] is None
        assert 'clean_box_cycled_ts' not in state

def test_unknown_and_vacuum_only_do_not_assert_mopping():
    for mode in ('unknown', 'unavailable', 'sweeping'):
        assert not tick._is_mop_active(mode, None, None, None, require_evidence=True)

def test_report_runtime_has_no_unmeasured_consumption_or_automatic_refill():
    device = effective({}, descriptor())
    state = {'used_ml': 0, 'initialized': True, 'last_reset_ts': 0}
    for index, (area, mode, tank) in enumerate([(0, 'mopping', 'installed'),
            (5, 'mopping', 'low_water'), (10, 'unknown', 'not_installed'),
            (15, 'sweeping', 'installed')]):
        hass = _Hass({'vacuum.saubi': _S('cleaning'),
            'sensor.saubi_state': _S('cleaning'),
            'sensor.saubi_cleaned_area': _S(str(area), {'unit_of_measurement':'m²'}),
            'sensor.saubi_cleaning_time': _S(str(index * 3), {'unit_of_measurement':'min'}),
            'sensor.saubi_mop_pad': _S('unknown'),
            'select.saubi_cleaning_mode': _S(mode),
            'select.saubi_mop_pad_humidity': _S('moist'),
            'sensor.saubi_clean_water_tank_status': _S(tank)})
        state, _ = tick.tick_device(hass, device, state, now_ts=10000000 + index * 60000)
        assert state['used_ml'] == 0
        assert not state.get('last_refill_ts')
    assert state.get('accounting_incomplete')

def test_live_advisory_transitions_and_legacy_binding_are_non_quantitative():
    desc = descriptor()
    settings = {'signal_overrides': {'vacuum.saubi': {'dock_clean_water_sensor': 'sensor.saubi_clean_water_tank_status'}}}
    device = effective(settings, desc)
    entity = 'sensor.saubi_clean_water_tank_status'
    state = {'initialized': True, 'used_ml': 120, 'last_reset_ts': 42, 'calibration_factor': 1.2}
    for idx, (raw, expected) in enumerate([('low_water', 'low_water'), ('not_installed', 'missing'),
            ('installed', 'ok'), ('unavailable', 'unknown'), ('unknown', 'unknown')]):
        h = _Hass({entity: _S(raw), 'vacuum.saubi': _S('docked')})
        state, changed = tick.tick_device(h, device, state, now_ts=10000000 + idx * 60000)
        assert state['clean_tank_advisory'] == expected
        assert state['used_ml'] == 120
        assert state['last_reset_ts'] == 42
        assert state['calibration_factor'] == 1.2
        assert not state.get('water_empty_active')
        assert not state.get('water_anchor_kind')
        if idx < 4:
            assert changed

def test_legacy_manual_binding_wins_and_explicit_status_override_wins():
    h = _Hass({'sensor.manual': _S('low_water'), 'sensor.auto': _S('installed')})
    d = {'integration_adapter':'dreame_vacuum', 'clean_water_tank_status_sensor':'sensor.auto',
         'dock_clean_water_sensor':'sensor.manual', '_explicit_fields':('dock_clean_water_sensor',)}
    assert tick._dreame_clean_tank_advisory(h,d) == 'low_water'
    d['signal_overrides_applied'] = ['clean_water_tank_status_sensor']
    assert tick._dreame_clean_tank_advisory(h,d) == 'ok'
    assert tick._dreame_clean_tank_advisory(h, {**d, 'dock_variant': 'plumbed'}) is None
    d['integration_adapter'] = 'roborock'
    assert tick._dreame_clean_tank_advisory(h,d) is None

def test_health_exposes_same_advisory_and_does_not_mark_empty():
    from test_issue10_missing_rate import health
    report = health.robot_health({'vacuum_entity':'vacuum.saubi'}, {},
        {'clean_tank_advisory':'low_water'}, {})
    assert report['clean_tank_advisory'] == 'low_water'
    assert not report['tank_empty']
