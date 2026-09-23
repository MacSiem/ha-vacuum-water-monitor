"""Behavior checks for the bundled card's estimator and dock guidance."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const classes = {};
global.HTMLElement = class {
  constructor() { this.tagName = 'HA-VACUUM-WATER-MONITOR'; }
  attachShadow() {
    this.shadowRoot = {
      querySelector() { return null; },
      querySelectorAll() { return []; },
      getElementById() { return null; },
    };
  }
};
global.customElements = {
  get(name) { return classes[name]; },
  define(name, constructor) { classes[name] = constructor; },
};
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.location = { pathname: '/' };
global.window = global;
global.CustomEvent = class {};
vm.runInThisContext(fs.readFileSync(
  'custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js',
  'utf8'
));
const Card = classes['ha-vacuum-water-monitor'];
const card = new Card();
const dock = card._buildDockSection(
  { dock_clean_water_sensor: 'binary_sensor.clean_box' },
  {
    dockCleanWaterFull: true,
    dockDirtyWaterFull: false,
    waterShortage: false,
    mopAttached: false,
    mopDrying: false,
  }
);
const dockEmpty = card._buildDockSection(
  { dock_clean_water_sensor: 'sensor.clean_tank' },
  {
    dockCleanWaterState: 'empty',
    dockCleanWaterProblem: true,
    dockDirtyWaterProblem: false,
    waterShortage: false,
    mopAttached: false,
    mopDrying: false,
  }
);
const dockMissing = card._buildDockSection(
  { dock_clean_water_sensor: 'sensor.clean_tank' },
  {
    dockCleanWaterState: 'missing',
    dockCleanWaterProblem: true,
    dockDirtyWaterProblem: false,
    waterShortage: false,
    mopAttached: false,
    mopDrying: false,
  }
);
const guidance = card._buildAccountingGuidance({
  initialized: true,
  capability: 'automatic_estimate',
  accountingSource: 'active_time',
  accountingRate: 6,
  accountingEvidence: 'cross_model_estimate',
  uncertaintyPercent: 60,
  calibrationSamples: 0,
  calibrationFactor: 1,
  stateReason: null,
});
const awaitingRefillGuidance = card._buildAccountingGuidance({
  initialized: false,
  capability: 'automatic_estimate',
});
const learned = card._buildAccountingGuidance({
  initialized: true,
  capability: 'automatic_estimate',
  accountingSource: 'area',
  accountingRate: 7.5,
  accountingEvidence: 'device_calibrated',
  uncertaintyPercent: 60,
  calibrationSamples: 2,
  calibrationFactor: 1.2,
  stateReason: null,
});
const lowGuidance = card._buildAccountingGuidance({
  initialized: true,
  capability: 'automatic_estimate',
  waterLow: true,
  waterEmpty: false,
  percentRemaining: 10,
  accountingSource: 'low_water',
  accountingEvidence: 'device_calibrated',
  calibrationSamples: 1,
  calibrationFactor: 1.1,
  stateReason: 'water_low',
});
const lowStatus = card._getStatus({
  totalMl: 5000,
  waterEmpty: false,
  waterLow: true,
  waterShortage: true,
  percentRemaining: 10,
}, {});
const diagnostics = card._buildDiagnostics({
  integrationAdapter: 'roomba',
  signalContractVersion: 1,
  mopEvidenceRequired: true,
  profileKey: 'tapo_rv50_pro_omni',
  profileSource: 'model_id',
  profileConfidence: 'high',
  trackedReservoir: 'dock_clean',
  totalMl: 5000,
  reservoirsMl: {},
  signals: {},
  accountingSource: 'active_time',
  accountingRate: 6,
  stateReason: null,
  accountingEvidence: 'cross_model_estimate',
  uncertaintyPercent: 60,
  calibrationSamples: 2,
  calibrationFactor: 1.2,
  estimatedM2PerActiveMinute: 0.8,
  tankSemanticsConfirmed: false,
  tankLevel: 80,
  dockTankLevel: 50,
  waterAnchorSource: 'water_shortage',
  waterAnchorKind: 'shortage',
  waterAnchorConfidence: 'estimated',
  consumptionResolution: {
    source: 'manufacturer_data',
    method: 'action',
    label: 'Manufacturer-declared, limited estimate',
    source_type: 'manufacturer_declaration',
    confidence: 'declared_source_limited',
    estimate_method: 'Use the declared quantity only for the explicitly identified action.',
    basis_ids: ['xiaomi_h50_pro_first_wash'],
    limitations: ['Completion-counter binding is unknown'],
    quantity: { value: 180, unit: 'ml/action' },
  },
});
const hostileDiagnostics = card._buildDiagnostics({
  integrationAdapter: '<img src=x onerror=globalThis.__vwm_xss=1>',
  profileKey: '</span><script>globalThis.__vwm_xss=2</script>',
  signals: { '<svg onload=globalThis.__vwm_xss=3>': 'sensor.hostile<value>' },
  waterAnchorSource: '" autofocus onfocus=globalThis.__vwm_xss=4 x="',
});
card._discoveredVacuums = [{
  entity_id: 'vacuum.adapter_robot',
  integration_adapter: 'valetudo',
  usage_ml_per_active_minute: { default: 6 },
  rate_signal: 'mop_intensity',
  uncertainty_percent: 60,
  time_accounting_evidence: 'derived_from_area_rate',
  estimated_m2_per_active_minute: 0.8,
  low_water_anchor_remaining_percent: 15,
  area_attribute: 'cleaned_area',
  area_attribute_unit: 'ha_unit_system',
  duration_attribute: 'cleaning_time',
  duration_attribute_unit: 'min',
  mop_intensity_attribute: 'fan_speed',
  water_box_attached_attribute: 'tank_present',
  tank_semantics_confirmed: false,
  mop_evidence_required: true,
  signal_contract_version: 1,
  signals: {
    cleaning_active_sensor: 'binary_sensor.robot_cleaning',
    duration_sensor: 'sensor.robot_time',
    water_box_attached_sensor: 'binary_sensor.robot_tank',
    dock_dirty_water_sensor: 'sensor.robot_wastewater',
    water_error_sensor: 'sensor.robot_water_error',
    dock_status_sensor: 'sensor.robot_dock_status',
    tank_level_sensor: 'sensor.robot_tank_level',
    dock_tank_level_sensor: 'sensor.robot_dock_tank_level',
    cleaning_mode_entity: 'select.robot_mode',
  },
}];
const merged = card._withBackendDescriptor({
  vacuum_entity: 'vacuum.adapter_robot',
  __vwmExplicitKeys: [],
  __vwmGeneratedKeys: [],
});
process.stdout.write(JSON.stringify({ dock, dockEmpty, dockMissing, guidance, awaitingRefillGuidance, learned, lowGuidance, lowStatus, diagnostics, hostileDiagnostics, merged }));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.output = json.loads(result.stdout)

    def test_clean_water_problem_is_not_labelled_full(self) -> None:
        dock = self.output["dock"]
        self.assertIn("Out / not installed", dock)
        self.assertNotIn(">⚠️ Full<", dock)
        self.assertIn("Empty", self.output["dockEmpty"])
        self.assertIn("Not installed", self.output["dockMissing"])

    def test_time_fallback_explains_source_and_uncertainty(self) -> None:
        guidance = self.output["guidance"]
        self.assertIn("active time", guidance)
        self.assertIn("60%", guidance)

    def test_unknown_water_state_explains_the_required_refill_baseline(self) -> None:
        guidance = self.output["awaitingRefillGuidance"]
        self.assertIn("Needs a refill baseline", guidance)
        self.assertIn("unknown", guidance)
        self.assertIn("press Refilled", guidance)

    def test_learned_calibration_explains_sample_count(self) -> None:
        learned = self.output["learned"]
        self.assertIn("2 empty tanks", learned)
        self.assertIn("1.2", learned)

    def test_low_water_anchor_is_not_presented_as_an_exact_empty_tank(self) -> None:
        guidance = self.output["lowGuidance"]
        self.assertIn("Low-water", guidance)
        self.assertIn("10%", guidance)
        self.assertNotIn("reservoir is empty", guidance)
        self.assertEqual(self.output["lowStatus"]["label"], "LOW WATER")

    def test_diagnostics_use_readable_rows_and_show_calibration(self) -> None:
        diagnostics = self.output["diagnostics"]
        self.assertIn('class="diagnostics-grid"', diagnostics)
        self.assertIn("2 tanks", diagnostics)
        self.assertIn("60%", diagnostics)
        self.assertIn("roomba", diagnostics)
        self.assertIn("Signal contract", diagnostics)
        self.assertIn("affirmative mop mode", diagnostics)
        self.assertIn("not used automatically", diagnostics)
        self.assertIn("water_shortage", diagnostics)
        self.assertIn("Manufacturer data", diagnostics)
        self.assertIn("180 ml/action", diagnostics)
        self.assertIn("not used automatically", diagnostics)

    def test_new_diagnostics_escape_hostile_home_assistant_values(self) -> None:
        diagnostics = self.output["hostileDiagnostics"]
        self.assertNotIn("<img", diagnostics)
        self.assertNotIn("<script", diagnostics)
        self.assertNotIn("<svg", diagnostics)
        self.assertNotIn("sensor.hostile<value>", diagnostics)
        self.assertIn("&lt;img", diagnostics)
        self.assertIn("&lt;script", diagnostics)
        self.assertIn("sensor.hostile&lt;value&gt;", diagnostics)

    def test_frontend_preserves_all_backend_adapter_roles_and_rate_metadata(self) -> None:
        merged = self.output["merged"]
        self.assertEqual(merged["integration_adapter"], "valetudo")
        self.assertEqual(
            merged["cleaning_active_sensor"], "binary_sensor.robot_cleaning"
        )
        self.assertEqual(merged["duration_sensor"], "sensor.robot_time")
        self.assertEqual(
            merged["water_box_attached_sensor"], "binary_sensor.robot_tank"
        )
        self.assertEqual(
            merged["dock_dirty_water_sensor"], "sensor.robot_wastewater"
        )
        self.assertEqual(merged["water_error_sensor"], "sensor.robot_water_error")
        self.assertEqual(merged["dock_status_sensor"], "sensor.robot_dock_status")
        self.assertEqual(merged["tank_level_sensor"], "sensor.robot_tank_level")
        self.assertEqual(
            merged["dock_tank_level_sensor"], "sensor.robot_dock_tank_level"
        )
        self.assertEqual(merged["cleaning_mode_entity"], "select.robot_mode")
        self.assertEqual(merged["usage_ml_per_active_minute"], {"default": 6})
        self.assertEqual(merged["rate_signal"], "mop_intensity")
        self.assertEqual(merged["uncertainty_percent"], 60)
        self.assertEqual(
            merged["time_accounting_evidence"], "derived_from_area_rate"
        )
        self.assertEqual(merged["estimated_m2_per_active_minute"], 0.8)
        self.assertEqual(merged["low_water_anchor_remaining_percent"], 15)
        self.assertEqual(merged["area_attribute"], "cleaned_area")
        self.assertEqual(merged["area_attribute_unit"], "ha_unit_system")
        self.assertEqual(merged["duration_attribute"], "cleaning_time")
        self.assertEqual(merged["duration_attribute_unit"], "min")
        self.assertEqual(merged["mop_intensity_attribute"], "fan_speed")
        self.assertEqual(merged["water_box_attached_attribute"], "tank_present")
        self.assertFalse(merged["tank_semantics_confirmed"])
        self.assertTrue(merged["mop_evidence_required"])
        self.assertEqual(merged["signal_contract_version"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
