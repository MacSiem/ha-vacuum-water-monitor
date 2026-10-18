"""Station settings must reach the same runtime that accounts for water."""
import unittest
from test_beta_runtime_path import discovery, sc
from test_tick import tick, _Hass, _State


class MopWashContracts(unittest.TestCase):
    def test_dreame_station_controls_survive_discovery_and_device_projection(self):
        keys = {'wash_mode_entity': 'washing_mode',
                'wash_frequency_entity': 'self_clean_frequency',
                'wash_temperature_entity': 'water_temperature'}
        entities = [{'entity_id': 'vacuum.robot', 'platform': 'dreame_vacuum',
                     'device_id': 'one', 'unique_id': 'robot'}]
        entities += [{'entity_id': 'select.' + key, 'translation_key': key,
                      'platform': 'dreame_vacuum', 'device_id': 'one'} for key in keys.values()]
        desc = discovery.discover_descriptors(entities, [{'id': 'one', 'manufacturer': 'Dreame',
                    'model': 'L10s Ultra'}], {})[0]
        device = sc.build_vacuum_devices({}, {}, [desc])[0]
        for role, key in keys.items():
            self.assertEqual(desc['signals'].get(role), 'select.' + key)
            self.assertEqual(device.get(role), 'select.' + key)

    def test_station_controls_are_exact_same_device_selects(self):
        record = {'entity_id': 'select.wash', 'translation_key': 'washing_mode',
                  'platform': 'dreame_vacuum', 'device_id': 'one'}
        for changed in ({'entity_id': 'button.wash'}, {'device_id': 'other'},
                        {'disabled_by': 'integration'}, {'platform': 'roborock'}):
            with self.subTest(changed=changed):
                signals = discovery._signals_for_device({'one'}, 'dreame_vacuum', [{**record, **changed}], {})[0]
                self.assertNotIn('wash_mode_entity', signals)

    def test_aborted_return_to_wash_never_charges_a_wash(self):
        device = {'vacuum_entity': 'vacuum.robot', 'status_sensor': 'sensor.status',
                  'wash_volume_ml': 150}
        state = {'used_ml': 0, 'initialized': True, 'last_status': 'charging'}
        for index, status in enumerate(('going_to_wash_the_mop', 'docking', 'charging')):
            hass = _Hass({'vacuum.robot': _State('docked'), 'sensor.status': _State(status)})
            state, _ = tick.tick_device(hass, device, state, now_ts=1000000 + index * 60000)
        self.assertEqual(state['used_ml'], 0)

    def test_return_then_actual_wash_charges_once_and_drying_does_not_charge(self):
        device = {'vacuum_entity': 'vacuum.robot', 'status_sensor': 'sensor.status',
                  'wash_volume_ml': 150}
        state = {'used_ml': 0, 'initialized': True, 'last_status': 'charging'}
        used = []
        for index, status in enumerate(('going_to_wash_the_mop', 'washing_the_mop',
                                        'washing_the_mop', 'drying', 'charging')):
            hass = _Hass({'vacuum.robot': _State('docked'), 'sensor.status': _State(status)})
            state, _ = tick.tick_device(hass, device, state, now_ts=1000000 + index * 60000)
            used.append(state['used_ml'])
        self.assertEqual(used, [0, 150, 150, 150, 150])

    def test_dreame_thresholds_and_alternate_frequency_are_bound_separately(self):
        keys = {'wash_frequency_entity': ('select', 'mop_clean_frequency'),
                'wash_area_threshold_entity': ('number', 'self_clean_area'),
                'wash_time_threshold_entity': ('number', 'self_clean_time')}
        entities = [{'entity_id': 'vacuum.robot', 'platform': 'dreame_vacuum', 'device_id': 'one'}]
        entities += [{'entity_id': domain+'.'+key, 'translation_key': key,
                      'platform': 'dreame_vacuum', 'device_id': 'one'}
                     for domain,key in keys.values()]
        desc=discovery.discover_descriptors(entities,[{'id':'one','manufacturer':'Dreame','model':'L10s Ultra'}],{})[0]
        device=sc.build_vacuum_devices({}, {}, [desc])[0]
        for role,(domain,key) in keys.items():
            self.assertEqual(device.get(role),domain+'.'+key)

    def test_wash_threshold_changes_consumption_context_without_charging_water(self):
        dev = {'vacuum_entity':'vacuum.robot', 'wash_frequency_entity':'select.frequency',
               'wash_area_threshold_entity':'number.area', 'wash_time_threshold_entity':'number.time'}
        state = {'used_ml':0, 'initialized':True}
        contexts=[]
        for i,area in enumerate((20,25)):
            hass=_Hass({'vacuum.robot':_State('docked'), 'select.frequency':_State('by_area'),
                        'number.area':_State(str(area)), 'number.time':_State('15')})
            state,_=tick.tick_device(hass,dev,state,now_ts=1000000+i*60000)
            contexts.append(state['last_consumption_context']['settings']['wash_frequency'])
        self.assertNotEqual(*contexts)
        self.assertEqual(state['used_ml'],0)

    def test_unknown_mop_label_is_not_positive_mode_evidence(self):
        self.assertFalse(tick._is_mop_active(None,'manufacturer_new_mode',None,require_evidence=True))

    def test_sequential_vacuum_then_mop_is_not_current_mopping(self):
        self.assertFalse(tick._is_mop_active('vacuum_then_mop',None,True,require_evidence=True))
