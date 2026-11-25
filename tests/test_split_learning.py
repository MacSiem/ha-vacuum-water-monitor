"""Independent split fits must not manufacture unidentifiable rates."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('split_learning', Path(__file__).parents[1] / 'custom_components/ha_vacuum_water_monitor/split_learning.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(i, area, washes, *, purpose='training'):
    return {'id': str(i), 'identity': {'robot': 'r', 'station': 's', 'reservoir': 'dock_clean',
            'floor_context': 'wet', 'wash_context': 'standard'},
            'source': 'measured_refill', 'purpose': purpose,
            'quality': {'boundaries_confirmed': True, 'uninterrupted': True,
                'exposure_complete': True, 'settings_constant': True, 'same_reservoir': True,
                'intervening_refill': False, 'unmeasured_transfer': False},
            'area_m2': area, 'wash_count': washes, 'observed_ml': area * 2 + washes * 30,
            'resolution_ml': 1}


def examples():
    return [sample(1, 10, 0), sample(2, 0, 1), sample(3, 20, 1),
            sample(4, 5, 1, purpose='validation')]


def test_identifiable_measured_cycles_and_holdout():
    result = module.fit(examples())
    assert result['floor_ml_per_m2'] == 2
    assert result['wash_ml_per_completed_action'] == 30


def test_collinear_missing_holdout_duplicate_and_outlier_are_rejected():
    assert module.fit([sample(i, 10, 1, purpose='validation' if i == 4 else 'training') for i in range(1, 5)]) is None
    assert module.fit(examples()[:3]) is None
    data = examples(); data[-1]['id'] = data[0]['id']
    assert module.fit(data) is None
    data = examples(); data[-1]['observed_ml'] = 200
    assert module.fit(data) is None


def test_rejects_transfer_and_fractional_wash():
    data = examples(); data[0]['quality']['unmeasured_transfer'] = True
    assert module.fit(data) is None
    data = examples(); data[1]['wash_count'] = 0.5
    assert module.fit(data) is None
