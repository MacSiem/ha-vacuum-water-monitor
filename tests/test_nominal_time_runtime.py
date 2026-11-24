"""Full nominal tanks teach the real Matter profile without an invented seed."""
import unittest
from test_beta_runtime_path import discovery, sc, tick, _S, _Hass


def device():
    entities = [{'entity_id': 'vacuum.tapo', 'platform': 'matter', 'device_id': 'one'}]
    entities += [{'entity_id': eid, 'platform': 'matter', 'device_id': 'one',
                  'translation_key': key} for eid, key in (
                    ('sensor.tapo_status', 'operational_state'),
                    ('select.tapo_mode', 'clean_mode'))]
    desc = discovery.discover_descriptors(entities, [{'id': 'one', 'manufacturer': 'Tapo',
                'model': 'RV50 Pro Omni', 'model_id': '1797'}], {})[0]
    return sc.build_vacuum_devices({}, {}, [desc])[0]


def observe(dev, state, now, active, mode='Vacuum and Mop;Deep Clean', distance=0, area=0):
    hass = _Hass({'vacuum.tapo': _S('cleaning' if active else 'docked'),
                  'sensor.tapo_status': _S('running' if active else 'docked'),
                  'select.tapo_mode': _S(mode),
                  'sensor.wet_distance': _S(str(distance), {'unit_of_measurement': 'm'}),
                  'sensor.area': _S(str(area), {'unit_of_measurement': 'm²'})})
    return tick.tick_device(hass, dev, state, now_ts=now)[0]


class NominalTimeRuntimeTests(unittest.TestCase):
    def test_three_full_tanks_activate_a_private_rate_on_next_refill(self):
        dev = device()
        self.assertFalse(dev.get('usage_ml_per_active_minute'))
        state = {}
        from importlib import import_module
        apply_refill = import_module(tick.__package__ + '.refill').apply_refill
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            apply_refill(state, now, 'service', rebaseline=True)
            state = observe(dev, state, now, False)
            for minute in range(10):
                state = observe(dev, state, now + 60_000 + minute * 60_000, True)
            state = observe(dev, state, now + 660_000, False)
            state['user_empty_active'] = True
            state = observe(dev, state, now + 720_000, False)
        resolution = state.get('nominal_time_resolution') or {}
        self.assertEqual(resolution.get('status'), 'active')
        self.assertEqual(resolution.get('accuracy'), 'not_established')
        self.assertEqual(resolution.get('sample_count'), 3)
        now += 2_000_000
        apply_refill(state, now, 'service', rebaseline=True)
        state = observe(dev, state, now, False)
        state = observe(dev, state, now + 60_000, True)
        state = observe(dev, state, now + 120_000, True)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10, places=2)
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertEqual(state['last_accounting_evidence'], 'nominal_full_to_empty_time')
        self.assertEqual(state['consumption_events'][0]['action'], 'whole_cycle')
        projection = sc.estimate_water_state(dev, state)
        self.assertEqual(projection['nominal_time_resolution']['status'], 'active')
        self.assertEqual(projection['uncertainty_kind'], 'nominal_tank_repeatability')
        self.assertIsNone(projection['uncertainty_percent'])

    def test_unrated_wet_distance_does_not_prevent_nominal_learning(self):
        dev = device()
        dev['mopped_distance_sensor'] = 'sensor.wet_distance'
        refill = __import__(tick.__package__ + '.refill', fromlist=['apply_refill']).apply_refill
        state = {}
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            refill(state, now, 'service', rebaseline=True)
            state = observe(dev, state, now, False)
            for minute in range(10):
                state = observe(dev, state, now + 60_000 * (minute + 1), True, distance=minute * 2)
            state = observe(dev, state, now + 660_000, False, distance=20)
            state = observe(dev, state, now + 720_000, False, distance=20)
            state['user_empty_active'] = True
            state = observe(dev, state, now + 780_000, False, distance=20)
        self.assertEqual(state['nominal_time_resolution']['status'], 'active')
        self.assertEqual(state['nominal_time_resolution']['sample_count'], 3)
        self.assertNotIn('usage_ml_per_m', dev)
        now += 2_000_000
        refill(state, now, 'service', rebaseline=True)
        state = observe(dev, state, now, False)
        state = observe(dev, state, now + 60_000, True)
        state = observe(dev, state, now + 120_000, True, distance=2)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10, places=2)
        self.assertEqual(state['last_accounting_evidence'], 'nominal_full_to_empty_time')
        self.assertEqual(state['consumption_events'][0]['action'], 'whole_cycle')
        # A configured distance rate replaces the nominal method; it is not added to it.
        dev['usage_ml_per_m'] = 2
        state = observe(dev, state, now + 180_000, True, distance=4)
        self.assertEqual(state['nominal_time_resolution']['reason'], 'time_method_replaced')
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10, places=2)
        state = observe(dev, state, now + 240_000, True, distance=6)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10 + 4, places=2)
        self.assertEqual(state['consumption_events'][0]['source'], 'mopped_distance')

    def test_unrated_distance_does_not_train_dirty_reservoir(self):
        refill = __import__(tick.__package__ + '.refill', fromlist=['apply_refill']).apply_refill
        for reservoir in ('dock_dirty', 'robot_dirty', 'detergent'):
            with self.subTest(reservoir=reservoir):
                dev = device()
                dev.update(mopped_distance_sensor='sensor.wet_distance', tracked_reservoir=reservoir)
                state = {}
                refill(state, 10_000_000, 'service', rebaseline=True)
                state = observe(dev, state, 10_000_000, False)
                state = observe(dev, state, 10_060_000, True)
                state = observe(dev, state, 10_120_000, True, distance=2)
                self.assertFalse((state.get('nominal_time_learning') or {}).get('cycle'))
                self.assertEqual(state['used_ml'], 0)

    def test_missing_mop_mode_does_not_create_learning_exposure(self):
        dev = device()
        state = {'initialized': True, 'last_reset_ts': 10_000_000,
                 'cycle_full_confirmed': True, 'used_ml': 0}
        for minute in range(12):
            state = observe(dev, state, 10_000_000 + minute * 60_000, True, mode='Vacuum Only')
        self.assertEqual(state['used_ml'], 0)
        self.assertFalse((state.get('nominal_time_learning') or {}).get('contexts'))

    def test_unavailable_before_first_observation_discards_pending_full(self):
        state = {'nominal_time_start_pending': True}
        tick._open_observation_gap(state, 1000000)
        self.assertFalse(state.get('nominal_time_start_pending'))

    def test_unrated_area_full_tanks_learn_and_apply_nominal_time(self):
        dev = device()
        dev['area_sensor'] = 'sensor.area'
        dev['usage_ml_per_m2'] = {}
        refill = __import__(tick.__package__ + '.refill', fromlist=['apply_refill']).apply_refill
        state = {}
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            refill(state, now, 'service', rebaseline=True)
            state = observe(dev, state, now, False, area=0)
            for minute in range(10):
                state = observe(dev, state, now + 60_000 * (minute + 1), True, area=minute)
            state = observe(dev, state, now + 660_000, False, area=10)
            state['user_empty_active'] = True
            state = observe(dev, state, now + 720_000, False, area=10)
        self.assertEqual(state['nominal_time_resolution']['status'], 'active')
        self.assertEqual(state['nominal_time_resolution']['sample_count'], 3)
        now += 2_000_000
        refill(state, now, 'service', rebaseline=True)
        state = observe(dev, state, now, False, area=0)
        state = observe(dev, state, now + 60_000, True, area=0)
        state = observe(dev, state, now + 120_000, True, area=1)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10, places=2)
        self.assertEqual(state['last_accounting_evidence'], 'nominal_full_to_empty_time')
        self.assertEqual(state['consumption_events'][0]['action'], 'whole_cycle')
        self.assertFalse(state.get('accounting_incomplete'))
        # The rated area source replaces the learned whole-cycle time rate.
        dev['usage_ml_per_m2'] = {'default': 5}
        state = observe(dev, state, now + 180_000, True, area=2)
        self.assertEqual(state['nominal_time_resolution']['reason'], 'time_method_replaced')
        state = observe(dev, state, now + 240_000, True, area=3)
        self.assertAlmostEqual(state['used_ml'], dev['tracked_capacity_ml'] * .95 / 10 + 5, places=2)
        self.assertEqual(state['consumption_events'][0]['source'], 'area')

    def test_generic_duration_without_verified_wet_semantics_is_explicitly_rejected(self):
        dev = device()
        dev['duration_sensor'] = 'sensor.duration'
        dev['usage_ml_per_active_minute'] = {}
        state = observe(dev, {'nominal_time_start_pending': True}, 1_000_000, False)
        self.assertFalse(state.get('nominal_time_start_pending'))
        self.assertEqual(state['nominal_time_resolution']['reason'], 'duration_counter_semantics_unverified')
        self.assertFalse((state.get('nominal_time_learning') or {}).get('cycle'))

    def test_unrated_area_gap_invalidates_nominal_learning(self):
        dev = device()
        dev.update(area_sensor='sensor.area', usage_ml_per_m2={})
        refill = __import__(tick.__package__ + '.refill', fromlist=['apply_refill']).apply_refill
        state = {}
        refill(state, 1_000_000, 'service', rebaseline=True)
        state = observe(dev, state, 1_000_000, False)
        state = observe(dev, state, 1_060_000, True)
        state = observe(dev, state, 1_120_000, True, area='unavailable')
        self.assertIsNone(state['nominal_time_learning']['cycle'])
        self.assertEqual(state['nominal_time_learning']['last_reason'], 'time_observation_unavailable')

    def test_area_method_cannot_retain_full_pending_for_later_time_learning(self):
        dev = device()
        dev['area_sensor'] = 'sensor.area'
        dev['usage_ml_per_m2'] = {'default': 5}
        state = observe(dev, {'nominal_time_start_pending': True}, 1000000, False)
        self.assertFalse(state.get('nominal_time_start_pending'))
