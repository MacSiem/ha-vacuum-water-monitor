"""A dock restoring its defaults must not erase the completed mop run."""
import unittest
from test_beta_runtime_path import BASE, descriptor, effective, hass, tick, sc, _S


class RestoredModeSessionTests(unittest.TestCase):
    def test_docked_default_restore_keeps_final_area_and_session_water(self):
        device=effective({},descriptor())
        device['cleaning_mode_entity']='select.cleaning_mode'
        state={**BASE,'last_area':0,'last_status':'charging'}
        steps=[('washing_the_mop','docked',0,'deep','intense','mop'),
               ('cleaning','cleaning',0,'deep','intense','mop'),
               ('cleaning','cleaning',10,'deep','intense','mop'),
               ('washing_the_mop','docked',10,'deep','intense','mop'),
               ('cleaning','cleaning',15.4,'deep','intense','mop'),
               ('charging','docked',15.5,'standard','extreme','vac_and_mop')]
        for index,(status,vac,area,mode,intensity,clean_mode) in enumerate(steps):
            h=hass(status=status,vac=vac,area=str(area),intensity=intensity,
                   extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+index*60_000)[0]
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertAlmostEqual(state['used_ml'],300+15.5*9*1.3,places=2)
        self.assertIsNotNone(state['automatic_sessions'][0]['water'])
        self.assertEqual(state['automatic_sessions'][0]['context']['settings']['mop_mode'],'deep')

    def test_empty_is_visible_even_when_prior_consumption_was_incomplete(self):
        device=effective({},descriptor())
        result=sc.estimate_water_state(device,{**BASE,'accounting_incomplete':True,
            'water_empty_active':True,'water_anchor_kind':'empty','used_ml':3800},{})
        self.assertEqual(result['remaining_percent'],0)
        self.assertEqual(result['remaining_ml'],0)
        self.assertIsNone(result['used_ml'])
        self.assertEqual(result['state_reason'],'water_empty')

    def test_returning_restore_and_late_area_use_last_floor_rate(self):
        device=effective({},descriptor())
        device['cleaning_mode_entity']='select.cleaning_mode'
        state={**BASE,'last_area':0,'last_status':'charging'}
        steps=[('cleaning','cleaning',0,'deep','intense','mop'),
               ('cleaning','cleaning',10,'deep','intense','mop'),
               ('returning_home','returning',10,'deep','extreme','vac_and_mop'),
               ('returning_home','returning',10.2,'standard','extreme','vac_and_mop'),
               ('charging','docked',10.2,'standard','extreme','vac_and_mop')]
        for i,(status,vac,area,mode,intensity,clean_mode) in enumerate(steps):
            h=hass(status=status,vac=vac,area=area,intensity=intensity,
                   extra={'select.robot_mop_mode':_S(mode),'select.cleaning_mode':_S(clean_mode)})
            state=tick.tick_device(h,device,state,now_ts=10_060_000+i*15_000)[0]
        self.assertFalse(state.get('accounting_incomplete'))
        self.assertAlmostEqual(state['used_ml'],10.2*9*1.3,places=2)
        self.assertTrue(state['automatic_sessions'][0]['accounting_valid'])
        self.assertEqual(state['automatic_sessions'][0]['context']['settings']['water_level'],'intense')

    def test_mode_change_during_floor_exposure_stays_incomplete(self):
        device=effective({},descriptor())
        state={**BASE,'last_area':0,'last_status':'charging'}
        for i,(area,mode) in enumerate([(0,'deep'),(10,'deep'),(11,'standard')]):
            state=tick.tick_device(hass(status='cleaning',vac='cleaning',area=area,intensity='intense',
                extra={'select.robot_mop_mode':_S(mode)}),device,state,now_ts=10_060_000+i*60_000)[0]
        self.assertTrue(state['accounting_incomplete'])
        self.assertFalse(state['session_accounting_valid'])

    def test_shortage_does_not_manufacture_empty_from_incomplete(self):
        result=sc.estimate_water_state(effective({},descriptor()),{**BASE,
            'accounting_incomplete':True,'water_empty_active':True,
            'water_anchor_kind':'shortage','used_ml':3800},{})
        self.assertIsNone(result['remaining_percent'])
        self.assertEqual(result['state_reason'],'accounting_incomplete')
