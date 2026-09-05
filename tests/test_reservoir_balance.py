"""Independent physical levels, no invented clean/dirty ratio or transfer totals."""
import unittest
from test_tick import tick,_Hass,_State


class ReservoirBalanceTests(unittest.TestCase):
    def run_tick(self,levels,state=None):
        entries={'vacuum.test':_State('docked')}
        for name,(value,unit) in levels.items():entries['sensor.'+name]=_State(value,{'unit_of_measurement':unit})
        d={'vacuum_entity':'vacuum.test','reservoir_volume_sensors':{name:'sensor.'+name for name in levels}}
        return tick.tick_device(_Hass(entries),d,state or {},now_ts=120000)[0]

    def test_five_independent_levels_and_no_transfer_double_counting(self):
        before=self.run_tick({'dock_clean':('4','L'),'dock_dirty':('0','mL'),'robot_clean':('0','mL'),'robot_dirty':('0','mL'),'detergent':('100','mL')})
        after=self.run_tick({'dock_clean':('3.9','L'),'dock_dirty':('0','mL'),'robot_clean':('100','mL'),'robot_dirty':('0','mL'),'detergent':('100','mL')},before)
        levels=after.get('reservoir_levels',{})
        self.assertEqual(levels.get('dock_clean',{}).get('volume_ml'),3900)
        self.assertEqual(levels['robot_clean']['volume_ml'],100)
        self.assertEqual(levels['dock_dirty']['volume_ml'],0)
        self.assertEqual(after.get('used_ml',0),0)
        self.assertIsNone(after.get('system_consumption_ml'))

    def test_grams_percent_and_unavailable_are_unknown(self):
        after=self.run_tick({'detergent':('10','g'),'robot_dirty':('10','%'),'dock_clean':('unavailable','L')})
        for name in ('detergent','robot_dirty','dock_clean'):
            self.assertIsNone(after.get('reservoir_levels',{}).get(name,{}).get('volume_ml'))
        self.assertEqual(after.get('reservoir_levels',{}).get('detergent',{}).get('reason'),'volume_unit_unknown')

    def test_one_sensor_cannot_be_assigned_to_two_reservoirs(self):
        h=_Hass({'vacuum.test':_State('docked'),'sensor.volume':_State('100',{'unit_of_measurement':'mL'})})
        d={'vacuum_entity':'vacuum.test','reservoir_volume_sensors':{'dock_clean':'sensor.volume','robot_clean':'sensor.volume'}}
        after=tick.tick_device(h,d,{},now_ts=120000)[0]
        self.assertEqual(after.get('reservoir_levels',{}).get('dock_clean',{}).get('reason'),'ambiguous_reservoir_binding')

    def test_unavailable_vacuum_does_not_present_old_levels_as_live(self):
        before=self.run_tick({'dock_clean':('4','L')})
        after=tick.tick_device(_Hass({'vacuum.test':_State('unavailable')}),{'vacuum_entity':'vacuum.test'},before,now_ts=180000)[0]
        self.assertIsNone(after['reservoir_levels']['dock_clean']['volume_ml'])
