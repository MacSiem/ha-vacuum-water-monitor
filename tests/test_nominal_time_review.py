"""Runtime regressions from independent nominal-learning review."""
import unittest
from importlib import import_module
from test_nominal_time_runtime import device, tick, sc, _Hass, _S


def observe(dev,state,now,active=False,dock='idle',intensity='high'):
    h=_Hass({'vacuum.tapo':_S('cleaning' if active else 'docked'),
             'sensor.tapo_status':_S('running' if active else 'docked'),
             'select.tapo_mode':_S('vacuum_and_mop'),
             'select.intensity':_S(intensity),'sensor.dock':_S(dock)})
    return tick.tick_device(h,dev,state,now_ts=now)[0]


def trained(dev,intensity='high'):
    refill=import_module(tick.__package__+'.refill').apply_refill
    state={}
    for cycle in range(3):
        now=10000000+cycle*10000000;refill(state,now,'service',rebaseline=True)
        state=observe(dev,state,now,intensity=intensity)
        for minute in range(10):state=observe(dev,state,now+60000+minute*60000,True,intensity=intensity)
        state=observe(dev,state,now+660000,intensity=intensity)
        state['user_empty_active']=True;state=observe(dev,state,now+720000,intensity=intensity)
    assert state['nominal_time_resolution']['status']=='active'
    now+=2000000;refill(state,now,'service',rebaseline=True)
    state=observe(dev,state,now,intensity=intensity)
    state=observe(dev,state,now+60000,True,intensity=intensity)
    return state,now+60000


class NominalReviewTests(unittest.TestCase):
    def test_learned_setting_rate_is_not_scaled_again_or_blocked_by_a_prior(self):
        for intensity,factors in [('high',{'high':1.3,'default':1}),('vendor_level',{})]:
            with self.subTest(intensity=intensity):
                dev=device();dev.update(mop_intensity_entity='select.intensity',intensity_factor=factors)
                state,now=trained(dev,intensity)
                state=observe(dev,state,now+60000,True,intensity=intensity)
                self.assertAlmostEqual(state['used_ml'],475,places=2)
                self.assertFalse(state.get('accounting_incomplete'))

    def test_last_floor_interval_before_wash_is_counted_once_in_whole_tank_rate(self):
        dev=device();dev['dock_status_sensor']='sensor.dock'
        state,now=trained(dev)
        state=observe(dev,state,now+60000,dock='washing')
        self.assertAlmostEqual(state['used_ml'],475,places=2)
        state=observe(dev,state,now+120000,dock='washing')
        self.assertAlmostEqual(state['used_ml'],475,places=2)
        self.assertEqual(state['last_accounting_evidence'],'nominal_full_to_empty_time')
        self.assertIsNone(sc.estimate_water_state(dev,state)['uncertainty_percent'])
        state=observe(dev,state,now+180000,True)
        state=observe(dev,state,now+240000,True)
        self.assertAlmostEqual(state['used_ml'],950,places=2)
