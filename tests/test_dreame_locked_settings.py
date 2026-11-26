"""Dreame task locks must preserve only fresh, bound observations."""
import unittest
from test_beta_runtime_path import BASE, _S, hass, tick
from test_dreame_observed_settings import fixture


def sample(status='charging', vacuum='docked', area=0, route='standard', remop='off',
           reclean='off', genius='off', mode='unavailable'):
    values = {'sensor.robot_state': _S(status),
              'sensor.robot_area': _S(str(area), {'unit_of_measurement': 'm²'}),
              'select.robot_mode': _S('mopping'), 'select.robot_humidity': _S('medium'),
              'number.robot_wetness': _S('16', {'min': 1, 'max': 32}),
              'select.robot_route': _S(route), 'select.robot_remop': _S(remop),
              'select.robot_reclean': _S(reclean), 'switch.robot_smart': _S('off'),
              'select.genius': _S(genius), 'select.genius_mode': _S(mode)}
    return hass(status=status, vac=vacuum, area=area, extra=values)


def device():
    return {**fixture(), 'context_cleangenius_entity': 'select.genius',
            'context_cleangenius_mode_entity': 'select.genius_mode',
            'usage_ml_per_m2': {'default': 10}, 'calibration_scope': 'floor_only'}


def step(dev, state, ts, **kw):
    return tick.tick_device(sample(**kw), dev, state, now_ts=ts)[0]


class LockedSettings(unittest.TestCase):
    def test_seed_lock_small_area_and_recovery(self):
        dev = device()
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        self.assertEqual(state['last_consumption_context']['observed_settings']['cleangenius_mode']['value'], 'not_applicable')
        state = step(dev, state, 10_060_000, status='cleaning', vacuum='cleaning', area=0,
                     route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        state = step(dev, state, 10_120_000, status='cleaning', vacuum='cleaning', area=0.05,
                     route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        state = step(dev, state, 10_180_000, status='cleaning', vacuum='cleaning', area=2,
                     route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        self.assertFalse(state.get('accounting_incomplete', False))
        self.assertEqual(state['used_ml'], 20)
        state = step(dev, state, 10_240_000, status='cleaning', vacuum='cleaning', area=3, route='other')
        self.assertTrue(state['accounting_incomplete'])

    def test_no_seed_and_unknown_are_not_locks(self):
        dev = device()
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000, status='cleaning', vacuum='cleaning', route='unavailable')
        self.assertTrue(state['accounting_incomplete'])
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        state = step(dev, state, 10_060_000, status='cleaning', vacuum='cleaning', route='unknown')
        self.assertTrue(state['accounting_incomplete'])

    def test_disconnect_and_rebind_drop_seed(self):
        dev = device()
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        state = step(dev, state, 10_060_000, vacuum='unavailable')
        state = step(dev, state, 10_120_000, status='cleaning', vacuum='cleaning', route='unavailable')
        self.assertIsNone(state['last_consumption_context']['observed_settings']['cleaning_route']['value'])
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        changed = {**dev, 'context_cleaning_route_entity': 'select.missing'}
        state = step(changed, state, 10_060_000, status='cleaning', vacuum='cleaning')
        self.assertIsNone(state['last_consumption_context']['observed_settings']['cleaning_route']['value'])

    def test_wash_and_delayed_unlock_keep_same_observed_context(self):
        dev = {**device(), 'wash_frequency_entity': 'select.robot_remop',
               'route_entity': 'select.robot_route'}
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        state = step(dev, state, 10_060_000, status='room_cleaning', vacuum='cleaning')
        before = state['last_consumption_context']['observed_settings']
        settings_before = state['last_consumption_context']['settings']
        for i, status in enumerate(('washing', 'clean_add_water', 'washing',
                                    'sweeping_and_mopping', 'returning', 'charging', 'completed'), 2):
            state = step(dev, state, 10_000_000 + i * 60_000, status=status,
                         vacuum='docked' if status in ('charging', 'completed') else 'cleaning',
                         route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
            self.assertEqual(state['last_consumption_context']['observed_settings'], before, status)
            self.assertEqual(state['last_consumption_context']['settings'], settings_before, status)
        state = step(dev, state, 10_480_000, status='charging')
        self.assertEqual(state['last_consumption_context']['observed_settings'], before)

    def test_reverse_transition_and_stale_seed(self):
        dev = device()
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        state = step(dev, state, 10_060_000, route='unavailable', remop='unavailable',
                     reclean='unavailable', genius='unavailable')
        state = step(dev, state, 10_120_000, status='cleaning', vacuum='cleaning',
                     route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        self.assertEqual(state['last_consumption_context']['observed_settings']['cleaning_route']['value'], 'standard')
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        for i in range(1, 5):
            state = step(dev, state, 10_000_000 + i * 60_000, route='unavailable')
        state = step(dev, state, 10_300_000, status='cleaning', vacuum='cleaning', route='unavailable')
        self.assertIsNone(state['last_consumption_context']['observed_settings']['cleaning_route']['value'])

    def test_completed_grace_expires_and_next_task_cannot_inherit(self):
        dev = device()
        locked = dict(route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        for second_task in (False, True):
            state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
            state = step(dev, state, 10_060_000, status='cleaning', vacuum='cleaning', **locked)
            state = step(dev, state, 10_120_000, status='completed', **locked)
            if second_task:
                state = step(dev, state, 10_180_000, status='cleaning', vacuum='cleaning', **locked)
            else:
                for now in (10_180_000, 10_240_000, 10_300_000):
                    state = step(dev, state, now, status='completed', **locked)
            self.assertIsNone(state['last_consumption_context']['observed_settings']['cleaning_route']['value'])

    def test_disagreement_invalidates_unverified_nominal_cycle(self):
        dev = device()
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000)
        state['nominal_time_learning'] = {'version': 1, 'cycle': {'open': True}, 'contexts': []}
        state = step(dev, state, 10_060_000, status='cleaning', vacuum='cleaning', route='unavailable')
        state['nominal_time_learning'] = {'version': 1, 'cycle': {'open': True}, 'contexts': []}
        state['dreame_pending_nominal_sample'] = {'result': 'must not be used'}
        state = step(dev, state, 10_120_000, status='charging', route='other')
        self.assertIsNone(state['nominal_time_learning']['cycle'])
        self.assertNotIn('dreame_pending_nominal_sample', state)

    def test_other_integrations_do_not_use_dreame_lock(self):
        dev = {**device(), 'integration_adapter': 'roborock'}
        state = step(dev, {**BASE, 'last_area': 0}, 10_000_000, mode='normal')
        state = step(dev, state, 10_060_000, status='cleaning', vacuum='cleaning', route='unavailable', mode='normal')
        self.assertTrue(state['accounting_incomplete'])

class LockedNominalLearning(unittest.TestCase):
    def test_locked_full_tanks_are_confirmed_on_unlock_and_rate_remains_usable(self):
        dev = {**device(), 'usage_ml_per_m2': {}, 'tracked_reservoir': 'dock_clean',
               'tracked_capacity_ml': 4500}
        refill = __import__(tick.__package__ + '.refill', fromlist=['apply_refill']).apply_refill
        state = {}
        locked = dict(route='unavailable', remop='unavailable', reclean='unavailable', genius='unavailable')
        for cycle in range(3):
            now = 10_000_000 + cycle * 10_000_000
            refill(state, now, 'service', rebaseline=True)
            state = step(dev, state, now, area=0)
            state = step(dev, state, now + 60_000, status='cleaning', vacuum='cleaning', area=0)
            for minute in range(2, 12):
                state = step(dev, state, now + minute * 60_000, status='cleaning', vacuum='cleaning',
                             area=minute - 1, **locked)
            state['user_empty_active'] = True
            state = step(dev, state, now + 720_000, status='cleaning', vacuum='cleaning', area=11, **locked)
            self.assertIsNotNone(state.get('dreame_pending_nominal_sample'))
            state = step(dev, state, now + 780_000, status='charging', area=11, **locked)
            state = step(dev, state, now + 840_000, status='completed', area=11)
            self.assertIsNone(state.get('dreame_pending_nominal_sample'))
        self.assertEqual(state['nominal_time_resolution']['status'], 'active')
        self.assertEqual(state['nominal_time_resolution']['sample_count'], 3)
        now += 2_000_000
        refill(state, now, 'service', rebaseline=True)
        state = step(dev, state, now, area=0)
        state = step(dev, state, now + 60_000, status='cleaning', vacuum='cleaning', area=0)
        state = step(dev, state, now + 120_000, status='cleaning', vacuum='cleaning', area=1, **locked)
        state = step(dev, state, now + 180_000, status='cleaning', vacuum='cleaning', area=2, **locked)
        self.assertGreater(state['used_ml'], 0)
        self.assertEqual(state['last_accounting_evidence'], 'nominal_full_to_empty_time')
