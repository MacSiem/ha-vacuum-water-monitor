"""Model-family sensitivity: supplied priors are not physical measurements."""
import unittest
from test_beta_runtime_path import BASE, descriptor, effective, hass, tick, sc

class FamilyTraceTests(unittest.TestCase):
    def test_same_floor_and_two_washes_use_each_labeled_family_prior_once(self):
        # Each expected ledger is independent arithmetic from the existing
        # labelled priors, not a claim that these are measured robot rates.
        cases=[('a97','pad','owner_device',150,6,360),
               ('a170','rotating_pads','class_prior',120,7,310),
               ('a245','roller','class_prior',200,10,500)]
        for model,mechanism,basis,wash,per_area,expected in cases:
            with self.subTest(model=model):
                device=effective({},descriptor(model));self.assertEqual(device['mop_system'],mechanism)
                self.assertEqual(device['estimate_basis'],basis)
                self.assertEqual(device['wash_volume_ml'],wash)
                self.assertEqual(device['usage_ml_per_m2']['standard'],per_area)
                state={**BASE,'last_area':0,'cycle_full_confirmed':True}
                for i,(status,vac,area) in enumerate((('washing_the_mop','docked',0),
                    ('cleaning','cleaning',0),('cleaning','cleaning',10),
                    ('washing_the_mop','docked',10)),1):
                    state,_=tick.tick_device(hass(status=status,vac=vac,area=area),device,state,now_ts=10_000_000+i*60000)
                self.assertEqual(state['used_ml'],expected)
                self.assertFalse(sc.estimate_water_state(device,state,{})['physical_accuracy_verified'])
