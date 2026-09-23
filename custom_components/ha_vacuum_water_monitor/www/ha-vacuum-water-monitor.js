/* HA Vacuum Water Monitor v5.7.0-beta.6 — HACS integration bundled card */
(function() {
'use strict';

// XSS protection helper (reuse global from panel, fallback for standalone)
const _asText = (s) => String(s ?? '');
const _escBase = (s) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const _esc = (s) => _escBase(_asText(s));
const ownDonateFooter = () => `<section class="donate-section" data-source="own-card"><div class="donate-text"><h3>❤️ Support HA Tools Development</h3><p>If this tool makes your Home Assistant life easier, consider supporting the project.</p></div><div class="donate-buttons"><a class="donate-btn coffee" href="https://buymeacoffee.com/macsiem" target="_blank" rel="noopener noreferrer">☕ Buy Me a Coffee</a><a class="donate-btn paypal" href="https://www.paypal.com/donate/?hosted_button_id=Y967H4PLRBN8W" target="_blank" rel="noopener noreferrer">💳 PayPal</a></div></section>`;

const VWM_DOMAIN = 'ha_vacuum_water_monitor';
const VWM_VERSION = '5.7.0-beta.6';
const VWM_SHARE_SCHEMA = 'vwm-calibration-share/1';
const VWM_SHARE_ISSUE_URL = 'https://github.com/MacSiem/ha-vacuum-water-monitor/issues/new';
// Mirrors estimation.py: deterministic uncertainty per estimate basis.
const VWM_BASIS_UNCERTAINTY = { fleet_posterior: 15, owner_device: 20, manufacturer_declared: 20, review_measured: 25, family_transfer: 35, class_prior: 50, generic_prior: 65 };
const VWM_BASIS_LABEL = {
  fleet_posterior: 'Learned from calibrated robots of this model',
  owner_device: 'Based on an owner\u2019s measured accounting for this model',
  manufacturer_declared: 'Based on manufacturer-declared quantities',
  review_measured: 'Based on an independent review measurement',
  family_transfer: 'Based on a closely related model',
  class_prior: 'Typical for this mop system',
  generic_prior: 'Generic mopping estimate',
};
const _vwmMedian = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};
// Python round() uses banker's rounding; match it for exact parity.
const _vwmRound = (value) => {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(value);
};
const _vwmUncertainty = (basis, logFactors) => {
  const base = Object.prototype.hasOwnProperty.call(VWM_BASIS_UNCERTAINTY, basis) ? VWM_BASIS_UNCERTAINTY[basis] : null;
  const factors = Array.isArray(logFactors) ? logFactors.map(Number).filter(Number.isFinite) : [];
  if (!factors.length) return base;
  if (factors.length < 3) return Math.max(8, _vwmRound((base === null ? 50 : base) / (factors.length + 1)));
  const center = _vwmMedian(factors);
  const mad = _vwmMedian(factors.map(v => Math.abs(v - center))) * 1.4826;
  return Math.max(5, Math.min(50, _vwmRound((Math.exp(mad * 1.25) - 1) * 100 + 3)));
};
// Mirrors estimation._stored_window: a window written over by an older release is ignored.
const _vwmStoredWindow = (tankState) => {
  const stored = tankState ? tankState.calibration_log_factors : null;
  if (!Array.isArray(stored) || !stored.every(v => typeof v === 'number' && Number.isFinite(v))) return null;
  const window = stored.slice(-8);
  const samples = tankState.calibration_samples;
  if (Number.isInteger(samples) && samples !== window.length) return null;
  return window;
};
const VWM_REFILL_SOURCE_LABEL = {
  card: 'Refilled button',
  service: 'automation / script',
  button: 'refill button',
  lid: 'tank lid',
  dock_cleared: 'dock reported refilled',
  legacy: 'earlier version',
};
const VWM_TANK_REASON_LABEL = {
  calibration_sample_unconfirmed: 'waiting for the next tank',
  calibration_sample_outlier: 'outlier',
  calibration_sample_incomplete_cycle: 'signals missing',
};
const VWM_EVENT = 'ha_vacuum_water_monitor_state_changed';


/**
 * HA Vacuum Water Monitor v3.0.0
 * Lovelace card for tracking vacuum cleaner water levels, history, maintenance and stats
 * Supports Roborock, Dreame, iRobot, Ecovacs, and generic vacuums
 * Multi-device | Tab navigation | Brand profiles | Auto-discovery | Maintenance scheduler
 * v3.0.0 - 2026-03-24
 */

// Brand profiles - pre-filled sensor names per brand/model
const BRAND_PROFILES = {
  'roborock_s8_maxv_ultra': {
    label: 'Roborock S8 MaxV Ultra',
    icon: '\uD83E\uDDA4',
    water_total_ml: 4000,
    vacuum_entity: 'vacuum.roborock_s8_maxv_ultra',
    // Official Roborock integration entities only \u2014 private template sensors
    // and input_helpers (water_used_input, water_sensor, last_session_sensor,
    // last_reset_entity) are NOT baked into the profile because they render
    // as `unknown` on fresh HACS installs. Advanced users can still wire DIY
    // helpers via per-card YAML config (see README "Advanced YAML"). (v5.0.4)
    dock_error_sensor: 'sensor.roborock_s8_maxv_ultra_dock_error',
    main_brush_sensor: 'sensor.roborock_s8_maxv_ultra_main_brush_time_left',
    side_brush_sensor: 'sensor.roborock_s8_maxv_ultra_side_brush_time_left',
    filter_time_sensor: 'sensor.roborock_s8_maxv_ultra_filter_time_left',
    sensor_dirty_sensor: 'sensor.roborock_s8_maxv_ultra_sensor_time_left',
    dock_brush_sensor: 'sensor.roborock_s8_maxv_ultra_dock_maintenance_brush_time_left',
    dock_strainer_sensor: 'sensor.roborock_s8_maxv_ultra_dock_strainer_time_left',
    dock_clean_water_sensor: 'binary_sensor.roborock_s8_maxv_ultra_dock_clean_water_box',
    dock_dirty_water_sensor: 'binary_sensor.roborock_s8_maxv_ultra_dock_dirty_water_box',
    water_shortage_sensor: 'binary_sensor.roborock_s8_maxv_ultra_water_shortage',
    mop_attached_sensor: 'binary_sensor.roborock_s8_maxv_ultra_mop_attached',
    mop_drying_sensor: 'binary_sensor.roborock_s8_maxv_ultra_mop_drying',
    area_sensor: 'sensor.roborock_s8_maxv_ultra_cleaning_area',
    duration_sensor: 'sensor.roborock_s8_maxv_ultra_cleaning_time',
    last_clean_start: 'sensor.roborock_s8_maxv_ultra_last_clean_begin',
    last_clean_end: 'sensor.roborock_s8_maxv_ultra_last_clean_end',
    charge_sensor: 'sensor.roborock_s8_maxv_ultra_battery',
    // Wire the server-side state machine to the real Roborock select
    // entities \u2014 without these the tick falls back to `standard`/`medium`
    // defaults (~50% underestimation at deep/high mopping). (v5.0.4)
    mop_mode_entity: 'select.roborock_s8_maxv_ultra_mop_mode',
    mop_intensity_entity: 'select.roborock_s8_maxv_ultra_mop_intensity',
  },
  'roborock_q7': {
    label: 'Roborock Q7',
    icon: '\uD83E\uDDA4',
    water_total_ml: 200,
    vacuum_entity: 'vacuum.roborock_q7',
    main_brush_sensor: 'sensor.roborock_q7_main_brush_time_left',
    side_brush_sensor: 'sensor.roborock_q7_side_brush_time_left',
    filter_time_sensor: 'sensor.roborock_q7_filter_time_left',
    charge_sensor: 'sensor.roborock_q7_battery',
  },
  'dreame_l20_ultra': {
    label: 'Dreame L20 Ultra',
    icon: '\uD83E\uDD16',
    water_total_ml: 4000,
    vacuum_entity: 'vacuum.dreame_l20_ultra',
    charge_sensor: 'sensor.dreame_l20_ultra_battery',
  },
  'irobot_j7': {
    label: 'iRobot j7+',
    icon: '\uD83E\uDDA4',
    water_total_ml: 0,
    vacuum_entity: 'vacuum.irobot_j7',
    charge_sensor: 'sensor.irobot_j7_battery_level',
  },
  'ecovacs': {
    label: 'Ecovacs (generic)',
    icon: '\uD83E\uDD16',
    water_total_ml: 240,
    vacuum_entity: 'vacuum.ecovacs',
  },
  'generic': {
    label: 'Generic Vacuum',
    icon: '\uD83E\uDDA4',
    water_total_ml: 0,
  },
};

// Mop wash states — status values that indicate the robot is washing or about to wash its mop
// Each transition INTO one of these states consumes `wash_volume_ml` of water (default 150 ml)
const MOP_WASH_STATES = [
  'washing_the_mop',
  'washing_the_mop_2',
  'going_to_wash_the_mop',
  'back_to_dock_washing_duster',
  'clean_mop_cleaning',
  'segment_clean_mop_cleaning',
  'zoned_clean_mop_cleaning',
];

// Default water dosing per m² by mop_mode (ml/m²)
const DEFAULT_USAGE_PER_M2 = {};
// Default multiplier by mop_intensity (or mop_water_level)
const DEFAULT_INTENSITY_FACTOR = { low: 0.8, medium: 1.0, high: 1.2, max: 1.3, custom: 1.0, smart_mode: 1.0, custom_water_flow: 1.0 };
// Default volume (ml) consumed per wash event
const DEFAULT_WASH_VOLUME_ML = null;
// Minimum area delta (m²) that triggers area-based dosing
const AREA_MIN_DELTA = 0.1;
// Minimum seconds between automatic resets (debounce)
const RESET_COOLDOWN_SEC = 60;

// Q1/Q2: Research-based calibration profiles per robot model
// Water usage (ml/m²) and cleaning efficiency data
const CALIBRATION_DATA = {
  "cecotec_conga_3290": {
    "label": "Cecotec Conga 3290",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "cecotec_conga_3790": {
    "label": "Cecotec Conga 3790",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "commodore_cvr_200": {
    "label": "Commodore CVR 200",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_d10s_plus": {
    "label": "Dreame D10s Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_d10s_pro": {
    "label": "Dreame D10s Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_d9": {
    "label": "Dreame D9",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_d9_pro": {
    "label": "Dreame D9 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_f9": {
    "label": "Dreame F9",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10_pro": {
    "label": "Dreame L10 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10_ultra": {
    "label": "Dreame L10 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://support.dreametech.com/hc/en-us/sections/10376680416783-Robot-Vacuums"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10s_pro_ultra": {
    "label": "Dreame L10s Pro Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://store.dreametech.com/robot-vacuum-and-mop-comparison/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10s_pro_ultra_heat": {
    "label": "Dreame L10s Pro Ultra Heat",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://support.dreametech.com/hc/en-us/sections/10376680416783-Robot-Vacuums",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10s_ultra": {
    "label": "Dreame L10s Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/dreamebot-l10s-ultra?gQT=1",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l10s_ultra_gen_2": {
    "label": "Dreame L10s Ultra Gen 2",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://store.dreametech.com/robot-vacuum-and-mop-comparison/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l20_ultra": {
    "label": "Dreame L20 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/l20-ultra?variant=41846212296909",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l30_ultra": {
    "label": "Dreame L30 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://support.dreametech.com/hc/en-us/sections/10376680416783-Robot-Vacuums"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l40_ultra": {
    "label": "Dreame L40 Ultra",
    "tank_ml": 4500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4500,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/l40ultra-robot-vacuum",
      "https://github.com/Tasshack/dreame-vacuum/blob/master/docs/entities.md",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_l40_ultra_gen_2": {
    "label": "Dreame L40 Ultra Gen 2",
    "tank_ml": 4500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4500,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/l40-ultra-gen2-robot-vacuum",
      "https://github.com/Tasshack/dreame-vacuum/blob/master/docs/events.md"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_w10": {
    "label": "Dreame W10",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_w10_pro": {
    "label": "Dreame W10 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_x30_ultra": {
    "label": "Dreame X30 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/dreame-x30-ultra/",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_x40_master": {
    "label": "Dreame X40 Master",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_x40_ultra": {
    "label": "Dreame X40 Ultra",
    "tank_ml": 4500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": 80,
    "dock_clean_tank_ml": 4500,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": 80,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/dreametech-x40-ultra-robot-vacuum",
      "https://github.com/Tasshack/dreame-vacuum/blob/master/docs/entities.md",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_x50_ultra": {
    "label": "Dreame X50 Ultra",
    "tank_ml": 4500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4500,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.dreametech.com/products/x50-ultra-robot-vacuum",
      "https://github.com/Tasshack/dreame-vacuum/blob/master/docs/entities.md"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "dreame_z10_pro": {
    "label": "Dreame Z10 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_n30_pro_omni": {
    "label": "Ecovacs ECOVACS DEEBOT N30 PRO OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.ecovacs.com/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_t30_pro_omni": {
    "label": "Ecovacs ECOVACS DEEBOT T30 PRO OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://site-static.ecovacs.com/upload/global/file/product_manual_edit/2024/05/20/094053_6297-DEEBOTT30PROOMNI-UserManual.pdf",
      "https://www.home-assistant.io/integrations/ecovacs"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_t50_pro_omni": {
    "label": "Ecovacs ECOVACS DEEBOT T50 PRO OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.ecovacs.com/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_x1_omni": {
    "label": "Ecovacs ECOVACS DEEBOT X1 OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.home-assistant.io/integrations/ecovacs"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_x2_omni": {
    "label": "Ecovacs ECOVACS DEEBOT X2 OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.home-assistant.io/integrations/ecovacs"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_x5_hybrid": {
    "label": "Ecovacs ECOVACS DEEBOT X5 HYBRID",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://site-static.ecovacs.com/upload/de/file/support/2025/06/24/024923_5962%24DEEBOTX5HYBRIDInstructionManual.pdf"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ecovacs_deebot_x8_pro_omni": {
    "label": "Ecovacs ECOVACS DEEBOT X8 PRO OMNI",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://site-static.ecovacs.com/upload/file/support/2025/07/04/012124_8335%24X8ProOMNIwithautorefill-EMEA.pdf",
      "https://www.home-assistant.io/integrations/ecovacs"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_c20": {
    "label": "eufy Omni C20",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_c28": {
    "label": "eufy Omni C28",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_e25": {
    "label": "eufy Omni E25",
    "tank_ml": 2500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 2500,
    "dock_dirty_tank_ml": 1800,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide",
      "https://www.eufy.com/uk/robot-vacuum-e28"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_e28": {
    "label": "eufy Omni E28",
    "tank_ml": 2500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 2500,
    "dock_dirty_tank_ml": 1800,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide",
      "https://www.eufy.com/uk/robot-vacuum-e28"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_s1": {
    "label": "eufy Omni S1",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_omni_s2": {
    "label": "eufy Omni S2",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eufy_x10_pro_omni": {
    "label": "eufy X10 Pro Omni",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.eufy.com/blogs/robovac/eufy-robot-vacuum-buying-guide"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_e20_evo_plus": {
    "label": "Eureka E20 Evo Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_e20_plus": {
    "label": "Eureka E20 Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_j12_ultra": {
    "label": "Eureka J12 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_j15_max_ultra": {
    "label": "Eureka J15 Max Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_j15_pro_ultra": {
    "label": "Eureka J15 Pro Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "eureka_j15_ultra": {
    "label": "Eureka J15 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "ikohs_netbot_ls22": {
    "label": "IKOHS Netbot LS22",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_braava_jet_m6": {
    "label": "iRobot Braava jet m6",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.irobot.com/sfsites/c/cms/delivery/media/MCLJTXTOSTTBDWDNWBJ3AEPORTHM",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_10_max_plus_autowash_dock": {
    "label": "iRobot Roomba Combo 10 Max + AutoWash Dock",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://homesupport.irobot.com/articles/en_US/Knowledge/10009",
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_i5": {
    "label": "iRobot Roomba Combo i5",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_i5_plus": {
    "label": "iRobot Roomba Combo i5+",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_j7": {
    "label": "iRobot Roomba Combo j7",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_j7_plus": {
    "label": "iRobot Roomba Combo j7+",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "irobot_roomba_combo_j9_plus": {
    "label": "iRobot Roomba Combo j9+",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://answers.irobot.com/nl-NL/knowledge/163",
      "https://www.home-assistant.io/integrations/roomba"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_p10_pro_ultra": {
    "label": "MOVA P10 Pro Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mova-tech.com/",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_p10_pro_ultra_gen2": {
    "label": "MOVA P10 Pro Ultra Gen2",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.mova.tech/products/mova-p10-pro-ultra-gen2-robot-vacuum"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_p20_ultra": {
    "label": "MOVA P20 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://us.mova.tech/products/mova-p10-pro-ultra-robot-vacuum-live-only"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_s20_ultra": {
    "label": "MOVA S20 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_v50_ultra_complete": {
    "label": "MOVA V50 Ultra Complete",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 3500,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mova.tech/products/mova-v50-ultra-robot-vacuum"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_z500": {
    "label": "MOVA Z500",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "mova_z50_ultra": {
    "label": "MOVA Z50 Ultra",
    "tank_ml": 4500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4500,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mova.tech/products/mova-z50-ultra-robot-vacuum"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "proscenic_m6_pro": {
    "label": "Proscenic M6 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_q5_max_plus": {
    "label": "Roborock Q5 Max+",
    "tank_ml": 180,
    "tracked_reservoir": "robot_clean",
    "robot_tank_ml": 180,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 180,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-q5-max-plus"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_q7_max": {
    "label": "Roborock Q7 Max",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_q_revo": {
    "label": "Roborock Q Revo",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://github.com/rytilahti/python-miio/blob/master/miio/integrations/roborock/vacuum/vacuum.py",
      "https://github.com/home-assistant/core/issues/103213"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_2_pro": {
    "label": "Roborock Qrevo 2 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-2-pro"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_5ae": {
    "label": "Roborock Qrevo 5AE",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": 80,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 3500,
    "robot_clean_tank_ml": 80,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.roborock.sg/products/roborock-qrevo-5ae-white-certified-refurbished",
      "https://github.com/MacSiem/ha-vacuum-water-monitor/issues/12"
    ],
    "data_quality": "capacity_verified",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curv": {
    "label": "Roborock Qrevo Curv",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curv_2_flow": {
    "label": "Roborock Qrevo Curv 2 Flow",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 3000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "roller",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 7,
      "standard": 10,
      "deep": 13,
      "deep_plus": 15
    },
    "mop_wash_ml": 200,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-2-flow",
      "https://github.com/MacSiem/ha-vacuum-water-monitor/issues/12",
      "https://www.notebookcheck.net/Roborock-now-also-mops-with-a-roller-Roborock-Qrevo-Curv-2-Flow-review.1234769.0.html",
      "https://kr.roborock.com/blogs/roborock-kr/qrevo-curv-2-flow-faq"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curv_2_pro": {
    "label": "Roborock Qrevo Curv 2 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curv_5xc": {
    "label": "Roborock Qrevo Curv 5XC",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curvc": {
    "label": "Roborock Qrevo CurvC",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_curvx": {
    "label": "Roborock Qrevo CurvX",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge": {
    "label": "Roborock Qrevo Edge",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-edge-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_2": {
    "label": "Roborock Qrevo Edge 2",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_2_flow": {
    "label": "Roborock Qrevo Edge 2 Flow",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "roller",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 7,
      "standard": 10,
      "deep": 13,
      "deep_plus": 15
    },
    "mop_wash_ml": 200,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_2_pro": {
    "label": "Roborock Qrevo Edge 2 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_3_pro": {
    "label": "Roborock Qrevo Edge 3 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_5v1": {
    "label": "Roborock Qrevo Edge 5V1",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-edge-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edge_s5a": {
    "label": "Roborock Qrevo Edge S5A",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-edge-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edgec": {
    "label": "Roborock Qrevo EdgeC",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-edge-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_edget": {
    "label": "Roborock Qrevo EdgeT",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_master": {
    "label": "Roborock Qrevo Master",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_maxv": {
    "label": "Roborock Qrevo MaxV",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_plus": {
    "label": "Roborock Qrevo Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_pro": {
    "label": "Roborock Qrevo Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_s": {
    "label": "Roborock Qrevo S",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_s_pro": {
    "label": "Roborock Qrevo S Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_qrevo_slim": {
    "label": "Roborock Qrevo Slim",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s5": {
    "label": "Roborock S5",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s5_max": {
    "label": "Roborock S5 Max",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s6": {
    "label": "Roborock S6",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s6_pure": {
    "label": "Roborock S6 Pure",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s7": {
    "label": "Roborock S7",
    "tank_ml": 300,
    "tracked_reservoir": "robot_clean",
    "robot_tank_ml": 300,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 300,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-s7",
      "https://github.com/rytilahti/python-miio/blob/master/miio/integrations/roborock/vacuum/vacuum.py",
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s7_maxv": {
    "label": "Roborock S7 MaxV",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://github.com/rytilahti/python-miio/blob/master/miio/integrations/roborock/vacuum/vacuum.py",
      "https://global.roborock.com/pages/roborock-auto-empty-dock"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s7_pro_ultra": {
    "label": "Roborock S7 Pro Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s8_maxv_ultra": {
    "label": "Roborock S8 MaxV Ultra",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": 100,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 100,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "owner_device",
    "estimate_label": "Measured accounting on an owner's device of this model",
    "uncertainty_percent": 20,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://support.roborock.com/hc/en-us/articles/33954114436761-What-is-the-difference-among-of-S8-Pro-Ultra-S8-Max-Ultra-and-S8-MaxV-Ultra"
    ],
    "data_quality": "capacity_verified",
    "notes": "Measured accounting on an owner's device of this model. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_s8_pro_ultra": {
    "label": "Roborock S8 Pro Ultra",
    "tank_ml": 3500,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": 200,
    "dock_clean_tank_ml": 3500,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 200,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "family_transfer",
    "estimate_label": "Transferred from a closely related model",
    "uncertainty_percent": 35,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://support.roborock.com/hc/en-us/articles/33954114436761-What-is-the-difference-among-of-S8-Pro-Ultra-S8-Max-Ultra-and-S8-MaxV-Ultra",
      "https://global.roborock.com/pages/roborock-academy"
    ],
    "data_quality": "capacity_verified",
    "notes": "Transferred from a closely related model. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_10": {
    "label": "Roborock Saros 10",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-saros-10"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_10r": {
    "label": "Roborock Saros 10R",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-saros-10r"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_20": {
    "label": "Roborock Saros 20",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "rotating_pads",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 5,
      "standard": 7,
      "deep": 10,
      "deep_plus": 12
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-saros-20"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_20_flow": {
    "label": "Roborock Saros 20 Flow",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "roller",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 7,
      "standard": 10,
      "deep": 13,
      "deep_plus": 15
    },
    "mop_wash_ml": 200,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-qrevo-curv-series"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_20_sonic": {
    "label": "Roborock Saros 20 Sonic",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "pad",
    "estimate_basis": "class_prior",
    "estimate_label": "Typical for this mop system; calibrates automatically",
    "uncertainty_percent": 50,
    "water_per_m2": {
      "fast": 4,
      "standard": 6,
      "deep": 9,
      "deep_plus": 11
    },
    "mop_wash_ml": 150,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-saros-20-sonic"
    ],
    "data_quality": "researched",
    "notes": "Typical for this mop system; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "roborock_saros_z70": {
    "label": "Roborock Saros Z70",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://global.roborock.com/pages/roborock-saros-z70"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "samsung_bespoke_jet_bot_combo_steam_plus_vr7md96514g_sp": {
    "label": "Samsung Bespoke Jet Bot Combo Steam+ VR7MD96514G/SP",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 3600,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://news.samsung.com/sg/samsung-sets-new-standards-for-cleanliness-and-hygiene-with-the-new-bespoke-jet-bot-combo"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "samsung_bespoke_jet_bot_combo_steam_vr7md96514g_eu": {
    "label": "Samsung Bespoke Jet Bot Combo Steam VR7MD96514G/EU",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.samsung.com/uk/vacuum-cleaners/robot/70w--jet-bot-combo--all-in-one-clean-station-steam-plus-with-steamwash-satin-greige-vr7md96514g-eu/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "switchbot_s10": {
    "label": "SwitchBot S10",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.switch-bot.com/pages/your-dream-cleaning-assistant-is-here-2"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "switchbot_s20": {
    "label": "SwitchBot S20",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.switch-bot.com/pages/your-dream-cleaning-assistant-is-here-2"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv20_max": {
    "label": "Tapo RV20 Max",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv20_max_plus": {
    "label": "Tapo RV20 Max Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv20_mop_plus": {
    "label": "Tapo RV20 Mop Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv30_max": {
    "label": "Tapo RV30 Max",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv30_max_plus": {
    "label": "Tapo RV30 Max Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv30_max_plus_gen_2": {
    "label": "Tapo RV30 Max Plus Gen 2",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/faq/290/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv30_plus": {
    "label": "Tapo RV30 Plus",
    "tank_ml": 300,
    "tracked_reservoir": "robot_clean",
    "robot_tank_ml": 300,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 300,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/en/product/robot-vacuum/tapo-rv30-plus/",
      "https://www.tapo.com/pl/faq/834/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv50_omni": {
    "label": "Tapo RV50 Omni",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/pl/faq/834/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "tapo_rv50_pro_omni": {
    "label": "Tapo RV50 Pro Omni",
    "tank_ml": 5000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": 95,
    "dock_clean_tank_ml": 5000,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": 95,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.tapo.com/us/product/robot-vacuum/tapo-rv50-pro-omni/",
      "https://github.com/MacSiem/ha-vacuum-water-monitor/issues/10"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "viomi_se": {
    "label": "Viomi SE",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "viomi_v6": {
    "label": "Viomi V6",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_1c": {
    "label": "Xiaomi 1C",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_1t": {
    "label": "Xiaomi 1T",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_h50": {
    "label": "Xiaomi Robot Vacuum H50",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-h50/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_h50_pro": {
    "label": "Xiaomi Robot Vacuum H50 Pro",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 4000,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-h50-pro/",
      "https://www.mi.com/global/support/faq/details/KA-673648/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_p2148": {
    "label": "Xiaomi P2148",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_5": {
    "label": "Xiaomi Robot Vacuum 5",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-5/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_5_pro": {
    "label": "Xiaomi Robot Vacuum 5 Pro",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-5-pro/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_s10": {
    "label": "Xiaomi Robot Vacuum S10",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-s10/specs/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_x10": {
    "label": "Xiaomi Robot Vacuum X10",
    "tank_ml": 200,
    "tracked_reservoir": "robot_clean",
    "robot_tank_ml": 200,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": 200,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-x10/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_x20": {
    "label": "Xiaomi Robot Vacuum X20",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-x20/",
      "https://www.home-assistant.io/integrations/xiaomi_miio/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_x20_plus": {
    "label": "Xiaomi Robot Vacuum X20+",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-x20-plus/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_robot_vacuum_x20_pro": {
    "label": "Xiaomi Robot Vacuum X20 Pro",
    "tank_ml": 4000,
    "tracked_reservoir": "dock_clean",
    "robot_tank_ml": null,
    "dock_clean_tank_ml": 4000,
    "dock_dirty_tank_ml": 3800,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://www.mi.com/global/product/xiaomi-robot-vacuum-x20-pro/"
    ],
    "data_quality": "capacity_verified",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_vacuum_mop_2_ultra": {
    "label": "Xiaomi Vacuum-Mop 2 Ultra",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_vacuum_mop_p": {
    "label": "Xiaomi Vacuum-Mop P",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "xiaomi_x10_plus": {
    "label": "Xiaomi X10 Plus",
    "tank_ml": null,
    "tracked_reservoir": null,
    "robot_tank_ml": null,
    "dock_clean_tank_ml": null,
    "dock_dirty_tank_ml": null,
    "robot_clean_tank_ml": null,
    "robot_dirty_tank_ml": null,
    "detergent_tank_ml": null,
    "mop_system": "unknown",
    "estimate_basis": "generic_prior",
    "estimate_label": "Generic mopping estimate; calibrates automatically",
    "uncertainty_percent": 65,
    "water_per_m2": {
      "any mode": 7
    },
    "mop_wash_ml": 120,
    "source_urls": [
      "https://valetudo.cloud/pages/general/supported-robots/"
    ],
    "data_quality": "researched",
    "notes": "Generic mopping estimate; calibrates automatically. Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals."
  },
  "generic": {
    "label": "Unknown model",
    "tank_ml": null,
    "robot_tank_ml": null,
    "water_per_m2": {},
    "mop_wash_ml": null,
    "estimate_basis": null,
    "uncertainty_percent": null,
    "notes": "Model not recognised: set the tank capacity to enable percentages."
  }
};

// Published, model-specific facts are kept separate from estimated ml/m²
// values. This avoids treating conditional manufacturer maxima (for example
// "up to 240 m² per fill") as measured water-dosing rates.
function _calibrationFacts(model) {
  if (!model) return [];
  const facts = [];
  const number = (value) => Number(value).toLocaleString('en-US');
  const add = (value, label) => {
    if (value !== undefined && value !== null) facts.push(`${number(value)} ${label}`);
  };
  add(model.dock_clean_tank_ml, 'ml clean dock');
  add(model.dock_dirty_tank_ml, 'ml dirty dock');
  add(model.robot_clean_tank_ml, 'ml robot');
  add(model.robot_dirty_tank_ml, 'ml robot dirty');
  if (model.tested_max_area_per_fill_m2) facts.push(`up to ${number(model.tested_max_area_per_fill_m2)} m²/fill (manufacturer test)`);
  if (model.mop_max_rpm) facts.push(`${number(model.mop_max_rpm)} rpm max`);
  if (model.mop_lift_max_mm) facts.push(`${number(model.mop_lift_max_mm)} mm lift max`);
  if (model.mop_pressure_max_n) facts.push(`${number(model.mop_pressure_max_n)} N pressure max`);
  if (model.water_flow_levels_count) facts.push(`${number(model.water_flow_levels_count)} water levels`);
  if (model.mop_wash_stages) facts.push(`${number(model.mop_wash_stages)}-stage mop wash`);
  if (model.continuous_fresh_water) facts.push('continuous fresh-water delivery');
  if (model.mop_wash_pre_task_ml) facts.push(`${number(model.mop_wash_pre_task_ml)} ml pre-task`);
  if (model.mop_wash_mid_task_ml) facts.push(`${number(model.mop_wash_mid_task_ml)} ml mid-task`);
  if (model.mop_wash_interval_m2_options) facts.push(`wash interval: ${model.mop_wash_interval_m2_options.join(' / ')} m² (default ${model.mop_wash_interval_m2_default} m²)`);
  if (model.mop_wash_interval_min_options) facts.push(`wash interval: ${model.mop_wash_interval_min_options.join(' / ')} min (default ${model.mop_wash_interval_min_default} min)`);
  if (model.mop_wash_frequency_levels) facts.push(`${number(model.mop_wash_frequency_levels)} wash-frequency levels`);
  if (model.mop_cleaning_preferences) facts.push(`${number(model.mop_cleaning_preferences)} mop-cleaning preferences`);
  if (model.mop_wash_temp_c) facts.push(`${number(model.mop_wash_temp_c)}°C wash`);
  if (model.drying_temp_c) facts.push(`${number(model.drying_temp_c)}°C drying air`);
  if (model.smart_dirt_detection) facts.push('smart dirt detection');
  if (model.auto_detergent) facts.push('automatic detergent dosing');
  return facts;
}

// Vendor/app model identifiers are not stable human product names. Resolve
// them through a canonical alias table instead of duplicating capacities.
const MODEL_ALIASES = {
  'a170': 'roborock_qrevo_5ae',
  'roborock_vacuum_a170': 'roborock_qrevo_5ae',
  'roborock_q_revo_5ae': 'roborock_qrevo_5ae',
  'a245': 'roborock_qrevo_curv_2_flow',
  'roborock_vacuum_a245': 'roborock_qrevo_curv_2_flow',
  'roborock_qrevo_curv_2_flowx': 'roborock_qrevo_curv_2_flow',
  'roborock_q_revo_curv_2_flow': 'roborock_qrevo_curv_2_flow',
  'roborock_q_revo_curv_2_flowx': 'roborock_qrevo_curv_2_flow',
  'xiaomi_robot_vacuum_h50': 'xiaomi_h50',
  'xiaomi_robot_vacuum_h50_pro': 'xiaomi_h50_pro',
  'tapo_rv50_pro': 'tapo_rv50_pro_omni',
};


/* ===== HA Tools split — inline shared infrastructure ===== */
// Bento Design System CSS (inline copy — keeps tool standalone)
const HA_VACUUM_WATER_MONITOR_BENTO_CSS = `
/* ═══════════════════════════════════════════════
   HA Tools — Bento Design System v2.0 (Premium)
   ═══════════════════════════════════════════════ */


/* keyboard a11y */
:focus-visible { outline: 2px solid var(--bento-primary, #6366f1); outline-offset: 2px; border-radius: 3px; }
:host {
  /* Brand palette — diamond top, gradient-friendly */
  --bento-primary: #6366f1;
  --bento-primary-2: #8b5cf6;
  --bento-primary-3: #ec4899;
  --bento-primary-hover: #4f46e5;
  --bento-primary-light: rgba(99, 102, 241, 0.08);
  --bento-primary-glow: rgba(99, 102, 241, 0.35);
  --bento-success: #10B981;
  --bento-success-light: rgba(16, 185, 129, 0.10);
  --bento-success-border: rgba(16, 185, 129, 0.25);
  --bento-error: #EF4444;
  --bento-error-light: rgba(239, 68, 68, 0.10);
  --bento-error-border: rgba(239, 68, 68, 0.25);
  --bento-warning: #F59E0B;
  --bento-warning-light: rgba(245, 158, 11, 0.10);
  --bento-warning-border: rgba(245, 158, 11, 0.25);
  --bento-info: #06b6d4;
  --bento-info-light: rgba(6, 182, 212, 0.10);
  --bento-info-border: rgba(6, 182, 212, 0.25);

  /* Theme */
  --bento-bg:     var(--primary-background-color, #fafaf9);
  --bento-bg-2:   var(--card-background-color, #f5f5f4);
  --bento-card:   var(--card-background-color, #ffffff);
  --bento-glass:  rgba(255, 255, 255, 0.7);
  --bento-border: var(--divider-color, #e7e5e4);
  --bento-border-strong: rgba(0, 0, 0, 0.08);
  --bento-text:           var(--primary-text-color,   #0c0a09);
  --bento-text-secondary: var(--secondary-text-color, #57534e);
  --bento-text-muted:     var(--disabled-text-color,  #a8a29e);

  /* Radii */
  --bento-radius-xs: 8px;
  --bento-radius-sm: 12px;
  --bento-radius-md: 18px;
  --bento-radius-lg: 24px;
  --bento-radius-pill: 999px;

  /* Shadows — modern, layered */
  --bento-shadow-sm: 0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.02);
  --bento-shadow-md: 0 4px 12px rgba(0,0,0,0.05), 0 2px 6px rgba(0,0,0,0.03);
  --bento-shadow-lg: 0 24px 48px -12px rgba(0,0,0,0.10), 0 12px 24px -8px rgba(0,0,0,0.05);
  --bento-shadow-glow: 0 0 0 1px rgba(99,102,241,0.15), 0 8px 32px -8px rgba(99,102,241,0.25);

  /* Gradients */
  --bento-grad-primary: linear-gradient(135deg, #6366f1, #8b5cf6);
  --bento-grad-rainbow: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #ec4899 100%);
  --bento-grad-success: linear-gradient(135deg, #10b981, #34d399);
  --bento-grad-error:   linear-gradient(135deg, #ef4444, #f87171);
  --bento-grad-warning: linear-gradient(135deg, #f59e0b, #fbbf24);

  /* Motion */
  --bento-trans-fast: 0.15s cubic-bezier(0.4, 0, 0.2, 1);
  --bento-trans:      0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --bento-trans-slow: 0.4s cubic-bezier(0.4, 0, 0.2, 1);

  /* Typography */
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", system-ui, sans-serif;
  font-feature-settings: "cv11" 1, "ss01" 1;
  letter-spacing: -0.01em;
  display: block;
  color: var(--bento-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ── Dark mode ───────────────────────────────── */
:host(.bento-dark) {
    --bento-bg:     var(--primary-background-color, #0a0a0f);
    --bento-bg-2:   var(--card-background-color,    #111119);
    --bento-card:   var(--card-background-color,    #16161f);
    --bento-glass:  rgba(22, 22, 31, 0.7);
    --bento-border: var(--divider-color,            #27272f);
    --bento-border-strong: rgba(255, 255, 255, 0.08);
    --bento-text:           var(--primary-text-color,   #fafaf9);
    --bento-text-secondary: var(--secondary-text-color, #d6d3d1);
    --bento-text-muted:     var(--disabled-text-color,  #78716c);
    --bento-primary:        #818cf8;
    --bento-primary-2:      #a78bfa;
    --bento-primary-3:      #f472b6;
    --bento-primary-light:  rgba(129, 140, 248, 0.12);
    --bento-primary-glow:   rgba(129, 140, 248, 0.45);
    --bento-success: #34d399;
    --bento-success-light:  rgba(52, 211, 153, 0.12);
    --bento-success-border: rgba(52, 211, 153, 0.30);
    --bento-error:   #f87171;
    --bento-error-light:    rgba(248, 113, 113, 0.12);
    --bento-error-border:   rgba(248, 113, 113, 0.30);
    --bento-warning: #fbbf24;
    --bento-warning-light:  rgba(251, 191, 36, 0.12);
    --bento-warning-border: rgba(251, 191, 36, 0.30);
    --bento-info:    #22d3ee;
    --bento-info-light:     rgba(34, 211, 238, 0.12);
    --bento-info-border:    rgba(34, 211, 238, 0.30);
    --bento-shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
    --bento-shadow-md: 0 4px 12px rgba(0,0,0,0.4), 0 2px 6px rgba(0,0,0,0.2);
    --bento-shadow-lg: 0 24px 48px -12px rgba(0,0,0,0.6), 0 12px 24px -8px rgba(0,0,0,0.3);
    --bento-shadow-glow: 0 0 0 1px rgba(129,140,248,0.2), 0 8px 32px -8px rgba(129,140,248,0.5);
    --bento-grad-primary: linear-gradient(135deg, #818cf8, #a78bfa);
    --bento-grad-rainbow: linear-gradient(135deg, #818cf8, #a78bfa 50%, #f472b6);
    color-scheme: dark !important;
  }
:host(.bento-dark) .card, :host(.bento-dark) .card-container, :host(.bento-dark) .main-card, :host(.bento-dark) .panel-card {
    background: var(--bento-card) !important; color: var(--bento-text) !important; border-color: var(--bento-border) !important;
  }
:host(.bento-dark) input, :host(.bento-dark) select, :host(.bento-dark) textarea { background: var(--bento-bg-2); color: var(--bento-text); border-color: var(--bento-border); }
:host(.bento-dark) table th { background: var(--bento-bg-2); color: var(--bento-text-secondary); border-color: var(--bento-border); }
:host(.bento-dark) table td { color: var(--bento-text); border-color: var(--bento-border); }
:host(.bento-dark) pre, :host(.bento-dark) code { background: #1e1e2e !important; color: #e2e8f0 !important; }

/* ── Reset & motion preferences ──────────────── */
* { box-sizing: border-box; }
@media (prefers-reduced-motion: reduce) { * { animation-duration: 0s !important; transition-duration: 0s !important; } }

/* ── Main Card Wrapper ───────────────────────── */
.card {
  background: var(--bento-card);
  border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-md);
  box-shadow: var(--bento-shadow-md);
  color: var(--bento-text);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
  position: relative;
  transition: box-shadow var(--bento-trans), border-color var(--bento-trans);
}

/* ── Header ──────────────────────────────────── */
.header {
  padding: 20px 24px 0;
  display: flex; align-items: center; gap: 12px;
}
.header-icon { font-size: 24px; }
.header-title {
  font-size: 18px; font-weight: 700; letter-spacing: -0.02em;
  color: var(--bento-text);
}
.header-badge {
  margin-left: auto;
  background: var(--bento-grad-primary); color: #fff;
  font-size: 11px; padding: 4px 10px; border-radius: var(--bento-radius-pill);
  font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  box-shadow: 0 4px 14px -2px var(--bento-primary-glow);
}
.content { padding: 20px 24px 24px; }

/* ── Tabs (modern pill style) ────────────────── */
.tabs, .tab-bar, .tab-nav, .tab-header {
  display: flex !important; gap: 4px !important;
  padding: 4px !important;
  background: var(--bento-bg-2) !important;
  border-radius: var(--bento-radius-pill) !important;
  margin-bottom: 20px !important;
  overflow: visible !important;
  -webkit-overflow-scrolling: touch !important;
  flex-wrap: wrap !important; border-bottom: 0 !important;
  width: 100%; max-width: 100%; box-sizing: border-box;
}
.tab, .tab-btn, .tab-button, .dtab {
  padding: 8px 16px !important;
  border: none !important; background: transparent !important; cursor: pointer !important;
  font-size: 13px !important; font-weight: 600 !important;
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, system-ui, sans-serif !important;
  color: var(--bento-text-secondary) !important;
  border-radius: var(--bento-radius-pill) !important;
  margin-bottom: 0 !important;
  transition: all var(--bento-trans) !important;
  white-space: nowrap !important; flex: 1 1 auto !important; text-align: center !important; min-height: 40px !important;
  letter-spacing: -0.005em !important;
}
.tab:hover, .tab-btn:hover, .tab-button:hover, .dtab:hover {
  color: var(--bento-text) !important;
  background: var(--bento-card) !important;
}
.tab.active, .tab-btn.active, .tab-button.active, .dtab.active {
  background: var(--bento-card) !important;
  color: var(--bento-primary) !important;
  box-shadow: var(--bento-shadow-sm) !important;
  font-weight: 700 !important;
}
.tab-content { display: block; }
.tab-content.active { animation: bentoFadeIn 0.35s cubic-bezier(0.4, 0, 0.2, 1); }
@keyframes bentoFadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Stat / KPI cards (premium) ──────────────── */
.stat-card, .stat-item, .metric-card, .kpi-card {
  background: var(--bento-bg-2) !important;
  border: 1px solid var(--bento-border) !important;
  border-radius: var(--bento-radius-sm) !important;
  padding: 18px !important;
  text-align: left !important;
  transition: transform var(--bento-trans), box-shadow var(--bento-trans), border-color var(--bento-trans);
  position: relative; overflow: hidden;
}
.stat-card::before, .metric-card::before, .kpi-card::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--bento-grad-primary);
  opacity: 0; transition: opacity var(--bento-trans);
}
.stat-card:hover, .stat-item:hover, .metric-card:hover, .kpi-card:hover {
  transform: translateY(-2px); box-shadow: var(--bento-shadow-lg); border-color: var(--bento-primary-light);
}
.stat-card:hover::before, .metric-card:hover::before, .kpi-card:hover::before { opacity: 1; }
.stat-icon { font-size: 22px; margin-bottom: 6px; opacity: 0.85; }
.stat-value, .stat-val, .metric-value, .kpi-val {
  font-size: 26px; font-weight: 800; line-height: 1.1;
  letter-spacing: -0.02em; color: var(--bento-text);
  font-feature-settings: "tnum" 1;
}
.stat-label, .stat-lbl, .metric-label, .kpi-lbl {
  font-size: 11px; color: var(--bento-text-secondary);
  margin-top: 4px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
}
.stat-num {
  font-size: 24px; font-weight: 800; color: var(--bento-primary);
  font-feature-settings: "tnum" 1; letter-spacing: -0.02em;
}
.stat-sub { font-size: 12px; color: var(--bento-text-muted); font-weight: 500; }

/* ── Overview grid ───────────────────────────── */
.overview-grid, .stats-grid, .summary-grid, .stat-cards, .kpi-grid, .metrics-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px; margin-bottom: 20px;
}

/* ── Section headers ─────────────────────────── */
.section-header, .section-title {
  display: flex; align-items: center; justify-content: space-between;
  position: relative; padding-left: 12px;
  font-size: 12px; font-weight: 700; color: var(--bento-text-secondary);
  text-transform: uppercase; letter-spacing: 0.08em;
  margin: 16px 0 10px;
}
.section-header::before, .section-title::before {
  content: ""; width: 4px; height: 4px; border-radius: 50%; background: var(--bento-primary);
  position: absolute; left: 0; top: 50%; transform: translateY(-50%); flex-shrink: 0;
}

/* ── Loading / Empty / Info ──────────────────── */
.loading-bar {
  height: 3px; border-radius: var(--bento-radius-pill);
  background: linear-gradient(90deg, var(--bento-primary), var(--bento-primary-2), transparent);
  background-size: 200% 100%;
  animation: bentoLoad 1.5s linear infinite; margin-bottom: 12px;
}
@keyframes bentoLoad { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

.empty-state, .no-data, .no-results {
  text-align: center; color: var(--bento-text-secondary);
  padding: 40px 20px; font-size: 14px;
  background: var(--bento-bg-2); border-radius: var(--bento-radius-md);
  border: 1px dashed var(--bento-border);
}
.info-note, .tip-box {
  font-size: 13px; color: var(--bento-text-secondary);
  background: var(--bento-primary-light);
  border-radius: var(--bento-radius-sm); padding: 12px 14px;
  border-left: 3px solid var(--bento-primary); margin-top: 12px;
  line-height: 1.55;
}
.last-updated {
  font-size: 11px; color: var(--bento-text-muted);
  text-align: right; margin-top: 12px; font-feature-settings: "tnum" 1;
}

/* ── Buttons (premium) ───────────────────────── */
.refresh-btn {
  background: var(--bento-bg-2); border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-pill); padding: 6px 14px;
  font-size: 12px; color: var(--bento-text-secondary);
  cursor: pointer; font-weight: 600; transition: all var(--bento-trans);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, system-ui, sans-serif;
}
.refresh-btn:hover {
  background: var(--bento-card); color: var(--bento-primary);
  border-color: var(--bento-primary); transform: translateY(-1px);
  box-shadow: var(--bento-shadow-sm);
}
.toggle-btn, .action-btn {
  background: var(--bento-grad-primary); border: none;
  border-radius: var(--bento-radius-xs); padding: 8px 16px;
  font-size: 13px; color: #fff; cursor: pointer; font-weight: 600;
  transition: all var(--bento-trans); font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, system-ui, sans-serif;
  letter-spacing: -0.005em;
  box-shadow: 0 4px 12px -2px var(--bento-primary-glow);
}
.toggle-btn:hover, .action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px -4px var(--bento-primary-glow);
}
.send-btn, .btn-primary {
  width: 100%;
  background: var(--bento-grad-primary); color: #fff;
  border: none; border-radius: var(--bento-radius-sm);
  padding: 12px 20px; font-size: 14px; font-weight: 700;
  cursor: pointer; font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, system-ui, sans-serif;
  letter-spacing: -0.01em;
  transition: all var(--bento-trans);
  box-shadow: 0 4px 14px -2px var(--bento-primary-glow);
}
.send-btn:hover, .btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px -6px var(--bento-primary-glow);
}
.send-btn:active, .btn-primary:active { transform: translateY(0); }
.send-btn:disabled, .btn-primary:disabled {
  opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none;
}

/* ── Badges / Status (modern pill) ───────────── */
.badge, .status-badge, .tag, .chip {
  padding: 4px 12px; border-radius: var(--bento-radius-pill);
  font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px;
  letter-spacing: 0.04em; text-transform: uppercase;
  border: 1px solid;
}
.badge-ok, .badge-success { background: var(--bento-success-light); color: var(--bento-success); border-color: var(--bento-success-border); }
.badge-er, .badge-error   { background: var(--bento-error-light);   color: var(--bento-error);   border-color: var(--bento-error-border); }
.badge-warn, .badge-warning { background: var(--bento-warning-light); color: var(--bento-warning); border-color: var(--bento-warning-border); }
.badge-info { background: var(--bento-info-light); color: var(--bento-info); border-color: var(--bento-info-border); }

.count-badge {
  font-size: 11px; font-weight: 700; padding: 3px 10px;
  border-radius: var(--bento-radius-pill); display: inline-flex; align-items: center;
  font-feature-settings: "tnum" 1;
}
.error-badge { background: var(--bento-error-light); color: var(--bento-error); border: 1px solid var(--bento-error-border); }
.warn-badge  { background: var(--bento-warning-light); color: var(--bento-warning); border: 1px solid var(--bento-warning-border); }
.info-badge  { background: var(--bento-primary-light); color: var(--bento-primary); border: 1px solid var(--bento-border); }
.ok-badge    { background: var(--bento-success-light); color: var(--bento-success); border: 1px solid var(--bento-success-border); }

/* ── Tables (modern) ─────────────────────────── */
table { width: 100%; border-collapse: separate; border-spacing: 0; }
th {
  background: var(--bento-bg-2); color: var(--bento-text-secondary);
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
  padding: 12px 16px; text-align: left;
  border-bottom: 1px solid var(--bento-border);
}
th:first-child { border-top-left-radius: var(--bento-radius-sm); }
th:last-child  { border-top-right-radius: var(--bento-radius-sm); }
td {
  padding: 14px 16px; border-bottom: 1px solid var(--bento-border);
  color: var(--bento-text); font-size: 13px;
}
tr { transition: background var(--bento-trans-fast); }
tr:hover td { background: var(--bento-primary-light); }
tr:last-child td { border-bottom: 0; }

/* ── Forms / Inputs ──────────────────────────── */
input, select, textarea {
  padding: 10px 14px; border: 1.5px solid var(--bento-border);
  border-radius: var(--bento-radius-xs);
  background: var(--bento-card); color: var(--bento-text);
  font-size: 14px; font-family: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, system-ui, sans-serif;
  transition: all var(--bento-trans); outline: none;
  letter-spacing: -0.005em;
}
input:focus, select:focus, textarea:focus {
  border-color: var(--bento-primary);
  box-shadow: 0 0 0 4px var(--bento-primary-light);
}
input::placeholder, textarea::placeholder { color: var(--bento-text-muted); }

/* ── Code blocks ─────────────────────────────── */
code {
  background: var(--bento-bg-2); padding: 2px 6px;
  border-radius: 4px; font-size: 12px;
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
  border: 1px solid var(--bento-border);
}
pre {
  background: #1e1e2e; color: #e2e8f0;
  padding: 16px; border-radius: var(--bento-radius-sm);
  font-size: 12.5px; overflow-x: auto; line-height: 1.65;
  white-space: pre-wrap; word-break: break-word;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  box-shadow: var(--bento-shadow-md);
}

/* ── Grid layouts ────────────────────────────── */
.schedule-grid, .send-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
.schedule-card, .send-card, .info-card {
  background: var(--bento-bg-2); border: 1px solid var(--bento-border);
  border-radius: var(--bento-radius-sm); padding: 16px;
  transition: all var(--bento-trans);
}
.schedule-card:hover, .send-card:hover, .info-card:hover {
  border-color: var(--bento-primary-light); transform: translateY(-1px);
  box-shadow: var(--bento-shadow-md);
}

/* ── Log entries ─────────────────────────────── */
.log-entry {
  display: flex; flex-wrap: wrap; align-items: flex-start;
  gap: 4px 8px; padding: 10px 12px;
  border-radius: var(--bento-radius-sm); margin-bottom: 6px;
  font-size: 12.5px; min-width: 0; overflow: hidden;
  border: 1px solid transparent; transition: all var(--bento-trans-fast);
}
.error-entry { background: var(--bento-error-light); border-color: var(--bento-error-border); }
.warn-entry  { background: var(--bento-warning-light); border-color: var(--bento-warning-border); }
.log-time { color: var(--bento-text-muted); font-feature-settings: "tnum" 1; flex-shrink: 0; font-family: "JetBrains Mono", monospace; }
.log-domain {
  font-weight: 700; flex-shrink: 1; min-width: 0; max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; word-break: break-all;
}
.error-domain { color: var(--bento-error); }
.warn-domain  { color: var(--bento-warning); }
.log-msg {
  color: var(--bento-text-secondary); flex-basis: 100%;
  word-break: break-word; overflow-wrap: anywhere;
  white-space: pre-wrap; min-width: 0; line-height: 1.55;
}

/* ── Send status ─────────────────────────────── */
.send-status {
  padding: 12px 16px; border-radius: var(--bento-radius-sm);
  margin-top: 14px; font-size: 13px; font-weight: 600;
  text-align: center; letter-spacing: -0.005em;
  border: 1px solid;
}
.send-status.sending { background: var(--bento-primary-light); color: var(--bento-primary); border-color: var(--bento-border); }
.send-status.success { background: var(--bento-success-light); color: var(--bento-success); border-color: var(--bento-success-border); }
.send-status.error   { background: var(--bento-error-light);   color: var(--bento-error);   border-color: var(--bento-error-border); }

/* ── Scrollbar ───────────────────────────────── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--bento-border); border-radius: var(--bento-radius-pill); border: 2px solid transparent; background-clip: content-box; }
::-webkit-scrollbar-thumb:hover { background: var(--bento-text-muted); background-clip: content-box; }

/* ── Animations ──────────────────────────────── */
@keyframes bentoSpin  { to { transform: rotate(360deg); } }
@keyframes bentoPulse { 0%,100% { opacity: 1; } 50% { opacity: .5; } }
@keyframes bentoSlideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes bentoStaggerIn { from { opacity: 0; transform: translateY(12px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }

/* Apply stagger to grids of stat-cards */
.stats-grid > *, .overview-grid > *, .summary-grid > * {
  animation: bentoStaggerIn 0.35s cubic-bezier(0.4, 0, 0.2, 1) both;
}
.stats-grid > *:nth-child(1)  { animation-delay: 0.02s; }
.stats-grid > *:nth-child(2)  { animation-delay: 0.06s; }
.stats-grid > *:nth-child(3)  { animation-delay: 0.10s; }
.stats-grid > *:nth-child(4)  { animation-delay: 0.14s; }
.stats-grid > *:nth-child(5)  { animation-delay: 0.18s; }
.stats-grid > *:nth-child(6)  { animation-delay: 0.22s; }

/* ── Mobile — 768 px ─────────────────────────── */
@media (max-width: 768px) {
  .content { padding: 16px; }
  .header { padding: 16px 16px 0; }
  .tabs { gap: 2px !important; padding: 3px !important; }
  .tab, .tab-button, .tab-btn { padding: 6px 12px !important; font-size: 12px !important; }
  .overview-grid, .stats-grid, .summary-grid, .stat-cards, .kpi-grid, .metrics-grid {
    grid-template-columns: repeat(2, 1fr); gap: 10px;
  }
  .stat-value, .stat-val, .kpi-val, .metric-val { font-size: 22px; }
  .stat-label, .stat-lbl, .kpi-lbl, .metric-lbl { font-size: 10px; }
  .send-grid, .schedule-grid { grid-template-columns: 1fr; }
  .log-entry { flex-wrap: wrap; gap: 2px 6px; padding: 8px 10px; }
  .log-domain { max-width: 60%; font-size: 11.5px; }
  .log-msg { flex-basis: 100%; max-width: 100%; font-size: 11.5px; }
  pre { padding: 12px; font-size: 11.5px; }
  h2 { font-size: 18px; }
  h3 { font-size: 15px; }
  table { font-size: 12.5px; }
  th, td { padding: 10px 12px; }
}
@media (max-width: 480px) {
  .tabs { gap: 1px !important; padding: 2px !important; }
  .tab, .tab-button, .tab-btn { padding: 5px 10px !important; font-size: 11px !important; }
  .overview-grid, .stats-grid, .summary-grid { grid-template-columns: 1fr 1fr; }
  .stat-value, .stat-val, .kpi-val { font-size: 18px; }
}
`;
/* ============================================================ */

class HAVacuumWaterMonitor extends HTMLElement {
  static getConfigElement() { return document.createElement('ha-vacuum-water-monitor-editor'); }
  constructor() {
    super();
    this._toolId = this.tagName.toLowerCase().replace('ha-', '');
    this._lang = (navigator.language || '').startsWith('pl') ? 'pl' : 'en';
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = {};
    this._lastRenderTime = 0;
    this._renderScheduled = false;
    this._firstRender = true;
    this._activeTab = 'water';
    this._activeDeviceIdx = 0;
    this._maintenanceItems = []; // custom maintenance items from HA Store
    this._userDevices = []; // user-added devices from HA Store
    this._refillConfig = {}; // refill method config from HA Store
    this._lastHtml = ''; // cache to prevent unnecessary DOM updates
    this._serverState = { settings: {}, tank_states: {} };
    this._discoveredVacuums = [];
    this._serverReady = false;
    this._serverLoadPromise = null;
    this._serverUnsub = null;
  }

  set hass(hass) {
    try {
      var _bg = (getComputedStyle(this).getPropertyValue('--card-background-color') || getComputedStyle(this).getPropertyValue('--primary-background-color') || '').trim();
      var _d = false;
      if (_bg) {
        var _h, _r, _g, _b, _m;
        if (_bg.charAt(0) === '#') { _h = _bg.slice(1); if (_h.length === 3) _h = _h.replace(/(.)/g, '$1$1'); _r = parseInt(_h.slice(0,2),16); _g = parseInt(_h.slice(2,4),16); _b = parseInt(_h.slice(4,6),16); }
        else { _m = _bg.match(/[\d.]+/g); if (_m) { _r = +_m[0]; _g = +_m[1]; _b = +_m[2]; } }
        if (_r != null) _d = (0.2126*_r + 0.7152*_g + 0.0722*_b) / 255 < 0.5;
      } else if (hass && hass.themes) { _d = !!hass.themes.darkMode; }
      this.classList.toggle('bento-dark', _d);
    } catch (e) {}
    if (hass?.language) this._lang = hass.language.startsWith('pl') ? 'pl' : 'en';
    this._hass = hass;
    if (!hass) return;

    this._ensureServerState();

    // Gate ONLY the periodic hass-driven refresh: server Store changes render
    // independently via _ensureServerState(), and UI/tab actions call _render()
    // directly. Skipping when no vacuum.* state changed avoids a full DOM
    // rebuild (and scroll/focus loss) every 10s while nothing is happening.
    const sig = this._hassSignature(hass);
    if (!this._firstRender && sig === this._lastHassSig) return;

    const now = Date.now();
    if (!this._firstRender && now - this._lastRenderTime < 10000) {
      if (!this._renderScheduled) {
        this._renderScheduled = true;
        setTimeout(() => {
          this._renderScheduled = false;
          this._lastHassSig = this._hassSignature(this._hass);
          this._render({ preserveDraft: true });
          this._lastRenderTime = Date.now();
        }, 10000 - (now - this._lastRenderTime));
      }
      return;
    }
    this._firstRender = false;
    this._lastHassSig = sig;
    this._render({ preserveDraft: true });
    this._lastRenderTime = now;
  }

  _hassSignature(hass) {
    if (!hass || !hass.states) return '';
    let s = '';
    const st = hass.states;
    for (const id in st) {
      if (id.startsWith('vacuum.')) s += id + '=' + st[id].state + ';';
    }
    return s;
  }

  _captureDraftState() {
    const sr = this.shadowRoot;
    const active = sr && sr.activeElement;
    const activeEditable = active && active.matches?.('input, select, textarea') ? active : null;
    const calibrationExpanded = sr.getElementById('vwm-custom-calibration-body')?.style.display === 'block';
    if (!activeEditable && !calibrationExpanded) return null;
    const controls = [...sr.querySelectorAll('input, select, textarea')];
    const activeIndex = activeEditable ? controls.indexOf(activeEditable) : -1;
    return {
      controls: controls.map((control, index) => ({
        index,
        id: control.id || '',
        value: control.value,
        checked: !!control.checked,
      })),
      activeIndex,
      activeId: activeEditable?.id || '',
      selectionStart: typeof activeEditable?.selectionStart === 'number' ? activeEditable.selectionStart : null,
      selectionEnd: typeof activeEditable?.selectionEnd === 'number' ? activeEditable.selectionEnd : null,
      calibrationExpanded,
    };
  }

  _restoreDraftState(draft) {
    if (!draft) return;
    const sr = this.shadowRoot;
    const controls = [...sr.querySelectorAll('input, select, textarea')];
    for (const saved of draft.controls) {
      const control = saved.id ? sr.getElementById(saved.id) : controls[saved.index];
      if (!control) continue;
      control.value = saved.value;
      if ('checked' in control) control.checked = saved.checked;
    }
    const expanded = sr.getElementById('vwm-custom-calibration-body');
    if (expanded && draft.calibrationExpanded) { expanded.style.display = 'block'; expanded.previousElementSibling?.setAttribute('aria-expanded', 'true'); }
    const active = draft.activeId ? sr.getElementById(draft.activeId) : (draft.activeIndex >= 0 ? controls[draft.activeIndex] : null);
    if (!active) return;
    active.focus();
    if (draft.selectionStart !== null && typeof active.setSelectionRange === 'function') {
      try { active.setSelectionRange(draft.selectionStart, draft.selectionEnd); } catch (e) {}
    }
  }

  get _t() {
    const T = {
      pl: {
        title: 'Monitor Odkurzacza i Wody',
        loading: 'Wczytywanie...',
        noData: 'Brak danych',
        error: 'B\u0142\u0105d',
        water: 'Woda',
        vacuum: 'Odkurzacz',
        maintenance: 'Konserwacja',
        status: 'Status',
        lastRun: 'Ostatnie uruchomienie',
        nextRun: 'Nast\u0119pne uruchomienie',
        fillLevel: 'Poziom nape\u0142nienia',
        tankEmpty: 'Zbiornik pusty',
        tankFull: 'Zbiornik pe\u0142ny',
        refill: 'Nape\u0142nij',
        clean: 'Wyczy\u015B\u0107',
        history: 'Historia',
        noDevices: 'Brak skonfigurowanych urz\u0105dze\u0144.',
        addVacuum: 'Dodaj odkurzacz w zak\u0142adce \u2699\uFE0F Ustawienia.',
      },
      en: {
        title: 'Vacuum & Water Monitor',
        loading: 'Loading...',
        noData: 'No data',
        error: 'Error',
        water: 'Water',
        vacuum: 'Vacuum',
        maintenance: 'Maintenance',
        status: 'Status',
        lastRun: 'Last run',
        nextRun: 'Next run',
        fillLevel: 'Fill level',
        tankEmpty: 'Tank empty',
        tankFull: 'Tank full',
        refill: 'Refill',
        clean: 'Clean',
        history: 'History',
        noDevices: 'No configured devices.',
        addVacuum: 'Add a vacuum in the ⚙️ Settings tab.',
      },
    };
    return T[this._lang] || T.en;
  }

  setConfig(config) {
    if (!config) throw new Error('Configuration required');

    this._authoredConfigKeys = new Set(Object.keys(config));
    const authoredDevices = Array.isArray(config.devices)
      ? config.devices.map(device => this._withAuthoredProvenance(device, Object.keys(device || {})))
      : config.devices;

    this._config = {
      title: config.title || 'Vacuum Monitor',
      brand_profile: config.brand_profile || null,
      warning_threshold: config.warning_threshold || 20,
      critical_threshold: config.critical_threshold || 10,
      show_filter: config.show_filter !== false,
      show_session: config.show_session !== false,
      show_refill_button: config.show_refill_button !== false,
      show_consumables: config.show_consumables !== false,
      show_dock_status: config.show_dock_status !== false,
      show_history: config.show_history !== false,
      show_stats: config.show_stats !== false,
      default_tab: config.default_tab || 'water',
      ...config,
      ...(Array.isArray(authoredDevices) ? { devices: authoredDevices } : {}),
    };

    this._activeTab = this._config.default_tab || 'water';
    try { localStorage.setItem('ha-tools-vacuum-water-monitor-settings', JSON.stringify({ _activeTab: this._activeTab, _activeDeviceIdx: this._activeDeviceIdx })); } catch(e) { console.debug('[ha-vacuum-water-monitor] caught:', e); }
    this._applyServerSettings();
    const configuredDevices = this._filterExistingVacuums(this._configuredDevicesFromConfig());
    if (configuredDevices.length) this._saveServerSettings({ configured_devices: configuredDevices });
    this._ensureServerState();
  }

  // Drop config devices whose vacuum_entity does not exist in HA: persisting
  // them would create ghost devices server-side (issue #1). Without hass we
  // cannot verify, so defer — _ensureServerState() re-runs this with hass set.
  _filterExistingVacuums(devices) {
    if (!this._hass) return devices;
    return devices.filter(d => !d.vacuum_entity || !!this._hass.states[d.vacuum_entity]);
  }

  getCardSize() { return 4; }

  getGridOptions() { return { rows: 8, columns: 12, min_rows: 3, min_columns: 6 }; }

  async _ensureServerState() {
    if (!this._hass || this._serverLoadPromise) return this._serverLoadPromise;
    this._serverLoadPromise = (async () => {
      try {
        const [state, listed] = await Promise.all([
          this._hass.callWS({ type: `${VWM_DOMAIN}/get_state` }),
          this._hass.callWS({ type: `${VWM_DOMAIN}/list_vacuums` }),
        ]);
        this._serverState = {
          settings: (state && state.settings) || {},
          tank_states: (state && state.tank_states) || {},
        };
        this._discoveredVacuums = (listed && listed.vacuums) || [];
        this._applyServerSettings();
        const configuredDevices = this._filterExistingVacuums(this._configuredDevicesFromConfig());
        if (configuredDevices.length) {
          const saved = await this._hass.callWS({ type: `${VWM_DOMAIN}/set_settings`, patch: { configured_devices: configuredDevices } });
          if (saved && saved.settings) {
            this._serverState.settings = saved.settings;
            this._applyServerSettings();
          }
        }
        this._subscribeServerEvents();
        this._serverReady = true;
        this._lastHtml = '';
        this._render({ preserveDraft: true });
      } catch (err) {
        console.error('[ha-vacuum-water-monitor] server state load failed:', err);
      } finally {
        this._serverLoadPromise = null;
      }
    })();
    return this._serverLoadPromise;
  }

  _subscribeServerEvents() {
    if (this._serverUnsub || !this._hass?.connection?.subscribeEvents) return;
    this._hass.connection.subscribeEvents((event) => {
      const data = (event && event.data) || {};
      if (data.settings) {
        this._serverState.settings = data.settings;
        this._applyServerSettings();
      }
      if (data.tank_states) {
        // Events carry the live balance only (history stays out of the
        // recorder); merge per vacuum so sessions and refills are kept.
        const merged = { ...(this._serverState.tank_states || {}) };
        for (const [vacuum, tank] of Object.entries(data.tank_states)) {
          merged[vacuum] = data.partial ? { ...(merged[vacuum] || {}), ...tank } : tank;
        }
        this._serverState.tank_states = merged;
      }
      this._lastHtml = '';
      this._render({ preserveDraft: true });
    }, VWM_EVENT).then((unsub) => { this._serverUnsub = unsub; }).catch((err) => {
      console.debug('[ha-vacuum-water-monitor] event subscription failed:', err);
    });
  }

  _applyServerSettings() {
    const settings = (this._serverState && this._serverState.settings) || {};
    this._maintenanceItems = Array.isArray(settings.maintenance_items) ? [...settings.maintenance_items] : [];
    this._userDevices = Array.isArray(settings.user_devices) ? [...settings.user_devices] : [];
    this._refillConfig = settings.refill_config && typeof settings.refill_config === 'object' ? { ...settings.refill_config } : {};
    const custom = settings.custom_calibration || {};
    const activeDevice = this._getDevices?.()[this._activeDeviceIdx] || null;
    this._customCalib = this._customCalibrationFor(activeDevice, custom);
    if (settings.warning_threshold && this._config.warning_threshold == null) this._config.warning_threshold = settings.warning_threshold;
    if (settings.critical_threshold && this._config.critical_threshold == null) this._config.critical_threshold = settings.critical_threshold;
  }

  async _saveServerSettings(patch) {
    if (!this._hass) return { ok: false, error: new Error('Home Assistant is unavailable') };
    try {
      const result = await this._hass.callWS({ type: `${VWM_DOMAIN}/set_settings`, patch });
      if (result && result.settings) {
        this._serverState.settings = result.settings;
        this._applyServerSettings();
      }
      return { ok: true, settings: (result && result.settings) || this._serverState.settings };
    } catch (err) {
      console.error('[ha-vacuum-water-monitor] settings save failed:', err);
      return { ok: false, error: err };
    }
  }

  _sanitize(s) { try { return decodeURIComponent(escape(s)); } catch(e) { return s; } }

  _configuredDevicesFromConfig() {
    if (!this._config) return [];
    if (this._config.devices && Array.isArray(this._config.devices)) {
      return this._config.devices.map(d => this._withAuthoredProvenance(
        d,
        d?.config_provenance?.authored_fields || Object.keys(d || {}).filter(key => key !== 'config_provenance')
      ));
    }
    const single = {};
    const keys = [
      'device_name','water_volume_sensor','water_volume_reservoir','water_anchor_reservoir','refill_on_clear','water_sensor','water_used_sensor','water_used_input','water_total_ml',
      'vacuum_entity','dock_error_sensor','filter_sensor','last_session_sensor',
      'last_reset_entity','main_brush_sensor','side_brush_sensor','filter_time_sensor',
      'sensor_dirty_sensor','dock_brush_sensor','dock_strainer_sensor',
      'dock_clean_water_sensor','dock_dirty_water_sensor','water_shortage_sensor','water_error_sensor',
      'mop_attached_sensor','water_box_attached_sensor','mop_drying_sensor','area_sensor','duration_sensor','cleaning_active_sensor',
      'last_clean_start','last_clean_end','charge_sensor','status_sensor',
      'reset_door_sensor','mop_mode_entity','mop_intensity_entity','cleaning_mode_entity','usage_ml_per_m2','usage_ml_per_active_minute','rate_signal','calibration_scope',
      'water_per_m2','intensity_factor','wash_volume_ml','mop_wash_ml','icon',
      'brand_profile','tracked_capacity_ml','tank_ml','tracked_reservoir','signals',
      'accounting_evidence','evidence','uncertainty_percent','profile_locked','profile_override','locked_profile',
      'area_anomaly_ceiling_m2',
    ];
    const authored = this._authoredConfigKeys || new Set();
    keys.forEach(k => { if (authored.has(k)) single[k] = this._config[k]; });
    if (!Object.keys(single).length || !single.vacuum_entity) return [];
    return [this._withAuthoredProvenance(single, [...authored].filter(key => key in single))];
  }

  static getStubConfig() {
    // Keep the stub minimal: a brand_profile here used to leak the profile's
    // default vacuum_entity into saved settings, creating a ghost device for
    // every user who added the card from the UI picker (issue #1, v5.1.7).
    return {
      title: 'Vacuum Water Monitor',
      warning_threshold: 20,
      critical_threshold: 10,
    };
  }

  // ── PERSISTENCE ──────────────────────────────────────────────────────────

  _loadMaintenanceItems() {
    this._applyServerSettings();
  }

  _saveMaintenanceItems() {
    this._saveServerSettings({ maintenance_items: this._maintenanceItems });
  }

  _loadUserDevices() {
    this._applyServerSettings();
  }

  _saveUserDevices() {
    this._saveServerSettings({ user_devices: this._userDevices });
  }

  _addUserDevice(entityId) {
    if (!entityId || !entityId.startsWith('vacuum.')) return false;
    if (this._userDevices.find(d => d.vacuum_entity === entityId)) return false;
    const state = this._hass && this._hass.states[entityId];
    const name = (state && state.attributes && state.attributes.friendly_name) || entityId;
    const descriptor = this._backendDescriptor({ vacuum_entity: entityId });
    this._userDevices.push(this._withAuthoredProvenance({
      vacuum_entity: entityId,
      name: descriptor?.name || name,
      icon: '\uD83E\uDD16',
    }, ['vacuum_entity']));
    this._saveUserDevices();
    return true;
  }

  async _removeUserDevice(entityId) {
    if (!this._hass) return;
    const prev = this._userDevices;
    this._userDevices = this._userDevices.filter(d => d.vacuum_entity !== entityId);
    try {
      const result = await this._hass.callWS({ type: `${VWM_DOMAIN}/remove_user_device`, vacuum_entity: entityId });
      if (result && result.settings) {
        this._serverState.settings = result.settings;
        this._applyServerSettings();
      }
      this._toast('Device removed');
      this._render();
    } catch (err) {
      this._userDevices = prev;
      console.error('[ha-vacuum-water-monitor] remove device failed:', err);
      this._toast('Could not remove device: ' + ((err && err.message) || 'unknown error'), true);
      this._render();
    }
  }

  _toast(message, isError) {
    try {
      this.dispatchEvent(new CustomEvent('hass-notification', {
        detail: { message: (isError ? '⚠️ ' : '') + message },
        bubbles: true,
        composed: true,
      }));
    } catch (e) {}
  }

  _upsertUserDevicePatch(device, patch) {
    const entityId = device && device.vacuum_entity;
    if (!entityId) return;
    const idx = this._userDevices.findIndex(d => d.vacuum_entity === entityId);
    if (idx >= 0) {
      const current = this._userDevices[idx];
      const authored = new Set([
        ...this._legacyFieldProvenance(current).explicit,
        'vacuum_entity',
        ...Object.keys(patch || {}),
      ]);
      this._userDevices[idx] = this._withAuthoredProvenance(
        { ...current, ...patch },
        [...authored]
      );
    } else {
      const created = {
        vacuum_entity: entityId,
        name: device.name || entityId,
        icon: device.icon || '\uD83E\uDD16',
        brand_profile: device.brand_profile || null,
        ...patch,
      };
      this._userDevices.push(this._withAuthoredProvenance(
        created,
        ['vacuum_entity', 'name', 'icon', 'brand_profile', ...Object.keys(patch || {})]
      ));
    }
    this._saveUserDevices();
  }

  // ── SERVER WATER STATE (replaces helper automations + browser app state) ───
  // The integration ticks the water state every 60s and stores it via HA Store.

  _loadWaterState(device) {
    const vid = (device && device.vacuum_entity) || 'unknown';
    const state = (this._serverState.tank_states || {})[vid];
    return { ...this._defaultWaterState(), ...(state || {}) };
  }

  _saveWaterState(device, state) {
    const vid = (device && device.vacuum_entity) || 'unknown';
    this._serverState.tank_states = { ...(this._serverState.tank_states || {}), [vid]: state };
  }

  _defaultWaterState() {
    return {
      used_ml: 0,
      initialized: false,
      last_reset_iso: null,
      last_status: null,
      last_area: null,
      last_duration_seconds: null,
      last_dock_err: null,
      last_door: null,
      last_reset_ts: 0,
      last_tick_ts: 0,
      water_empty_active: false,
      water_anchor_source: null,
      water_anchor_kind: null,
      water_anchor_confidence: null,
      water_anchor_candidate_source: null,
      water_anchor_candidate_since_ts: 0,
      calibration_factor: 1,
      calibration_samples: 0,
    };
  }

  // Returns true if HA already has helper entities for this device.
  // Mirror of the Python `_has_user_priv_helpers` in tick.py — if the device
  // config points at an existing input_number/template sensor for water tracking,
  // the user already has DIY automation/template accounting and we must defer.
  // Both card and tick must agree on this so the integration never overwrites
  // a user's pre-existing helper from JS, and never displays double-counted state.
  _hasPrivHelpers(device) {
    if (!this._hass || !device) return false;
    const inp = device.water_used_input && this._hass.states[device.water_used_input];
    return !!inp;
  }

  // Core state machine moved to Python tick.py in v5.
  _tickWaterState(device) {
    // Server-side tick owns accounting in v5.
  }

  // Manual reset (called from refill button when helper entities are absent)
  _resetWaterState(device) {
    if (!this._hass || !device?.vacuum_entity) return Promise.reject(new Error('Missing vacuum entity'));
    return this._hass.callWS({ type: `${VWM_DOMAIN}/reset_tank`, vacuum_entity: device.vacuum_entity })
      .then((result) => {
        if (result && result.state) this._saveWaterState(device, result.state);
        this._lastHtml = '';
        this._render();
        return result;
      })
      .catch((err) => {
        console.error('[ha-vacuum-water-monitor] reset failed:', err);
        throw err;
      });
  }

  // Returns effective used_ml from integration state.
  _getEffectiveUsedMl(device) {
    const state = this._loadWaterState(device);
    return state.used_ml || 0;
  }

  _getEffectiveLastReset(device) {
    const state = this._loadWaterState(device);
    if (state.last_reset_iso) return state.last_reset_iso;
    const raw = Number(state.last_reset_ts);
    if (!Number.isFinite(raw) || raw <= 0) return null;
    return raw > 10000000000 ? raw : raw * 1000;
  }

  // Auto-add discovered vacuums that aren't yet in user devices (fresh HACS install UX)
  _autoAddDiscoveredVacuums() {
    return false;
  }

  _loadRefillConfig() {
    this._applyServerSettings();
  }

  _saveRefillConfig() {
    this._saveServerSettings({ refill_config: this._refillConfig || {} });
  }

  // Get all input_button entities from HA
  _getInputButtons() {
    if (!this._hass) return [];
    return Object.values(this._hass.states)
      .filter(s => s.entity_id.startsWith('input_button.') || s.entity_id.startsWith('button.'))
      .map(s => ({ id: s.entity_id, name: (s.attributes && s.attributes.friendly_name) || s.entity_id }));
  }

  // Get all binary_sensor door/window/opening entities
  _getDoorSensors() {
    if (!this._hass) return [];
    return Object.values(this._hass.states)
      .filter(s => s.entity_id.startsWith('binary_sensor.') &&
        s.attributes && ['door', 'window', 'opening', 'garage_door'].includes(s.attributes.device_class))
      .map(s => ({ id: s.entity_id, name: (s.attributes && s.attributes.friendly_name) || s.entity_id, state: s.state }));
  }

  // Create input_button helper via HA API
  async _createRefillButton(device) {
    const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
    try {
      await this._hass.callWS({
        type: 'input_button/create',
        name: `Refill ${shortId}`,
        icon: 'mdi:water-sync',
      });
      return `input_button.refill_${shortId}`;
    } catch (e) {
      console.error('[VWM] Create input_button failed:', e);
      return null;
    }
  }


  // ── HELPERS ───────────────────────────────────────────────────────────────

  _getStateValue(entityId) {
    if (!this._hass || !entityId) return null;
    const state = this._hass.states[entityId];
    return state ? state.state : null;
  }

  _getAttr(entityId, attr) {
    if (!this._hass || !entityId) return null;
    const state = this._hass.states[entityId];
    return state && state.attributes ? state.attributes[attr] : null;
  }

  _normaliseModelKey(value) {
    return String(value || '').toLowerCase().replace(/\+/g, ' plus ').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  _resolveProfileKey(device) {
    // The integration resolves profiles from the HA device registry. That
    // descriptor is authoritative; the legacy browser catalog below exists
    // only for older integrations that do not return profile_key yet.
    const authored = this._explicitDeviceKeys(device);
    if (device?.profile_locked && authored.has('profile_locked')) {
      const locked = device.profile_override || device.locked_profile || device.brand_profile;
      const normalized = this._normaliseModelKey(locked);
      const canonical = MODEL_ALIASES[normalized] || normalized;
      if (CALIBRATION_DATA[canonical]) return canonical;
    }
    if (device?.profile_key) return String(device.profile_key);
    // Auto-resolve the model profile from brand_profile or the vacuum entity id,
    // so a known model (e.g. vacuum.roborock_s8_maxv_ultra) gets its real tank
    // capacity OOTB without the user manually picking a Brand Profile.
    if (!device) return null;
    const bp = device.brand_profile;
    if (bp) {
      const normalized = this._normaliseModelKey(bp);
      const canonical = MODEL_ALIASES[normalized] || normalized;
      if (CALIBRATION_DATA[canonical]) return canonical;
    }
    const ent = String(device.vacuum_entity || '').toLowerCase();
    if (ent.startsWith('vacuum.')) {
      const normalized = this._normaliseModelKey(ent.slice(7));
      const canonical = MODEL_ALIASES[normalized] || normalized;
      if (CALIBRATION_DATA[canonical]) return canonical;
    }
    if (typeof BRAND_PROFILES !== 'undefined') {
      for (const k in BRAND_PROFILES) {
        if (BRAND_PROFILES[k].vacuum_entity && BRAND_PROFILES[k].vacuum_entity === device.vacuum_entity) return k;
      }
    }
    return null;
  }

  _backendDescriptor(device) {
    const entity = String(device?.vacuum_entity || '').trim();
    if (!entity) return null;
    return (this._discoveredVacuums || []).find(item => item?.entity_id === entity) || null;
  }

  _explicitDeviceKeys(device) {
    return new Set(Array.isArray(device?.__vwmExplicitKeys) ? device.__vwmExplicitKeys : []);
  }

  _generatedDeviceKeys(device) {
    return new Set(Array.isArray(device?.__vwmGeneratedKeys) ? device.__vwmGeneratedKeys : []);
  }

  _withAuthoredProvenance(device, keys) {
    const source = device && typeof device === 'object' ? { ...device } : {};
    delete source.__vwmExplicitKeys;
    delete source.__vwmGeneratedKeys;
    return {
      ...source,
      config_provenance: { authored_fields: [...new Set((keys || []).map(String))] },
    };
  }

  _legacyFieldProvenance(device) {
    const source = device && typeof device === 'object' ? device : {};
    const provenance = source.config_provenance;
    if (provenance && Array.isArray(provenance.authored_fields)) {
      const explicit = new Set(provenance.authored_fields.map(String));
      return { explicit, generated: new Set(Object.keys(source).filter(key => key !== 'config_provenance' && !explicit.has(key))) };
    }
    const profile = BRAND_PROFILES[source.brand_profile];
    if (!profile) {
      return { explicit: new Set(Object.keys(source).filter(key => !['config_provenance', '__vwmExplicitKeys', '__vwmGeneratedKeys'].includes(key))), generated: new Set() };
    }
    const normalizedProfile = this._normaliseModelKey(source.brand_profile);
    const canonicalProfile = MODEL_ALIASES[normalizedProfile] || normalizedProfile;
    const calibration = CALIBRATION_DATA[canonicalProfile] || {};
    const migrationDefaults = {
      ...profile,
      tracked_capacity_ml: calibration.tank_ml,
      tank_ml: calibration.tank_ml,
      usage_ml_per_m2: calibration.mop_modes,
      water_per_m2: calibration.water_per_m2,
      intensity_factor: calibration.intensity_factors,
      wash_volume_ml: calibration.mop_wash_ml,
      mop_wash_ml: calibration.mop_wash_ml,
    };
    const explicit = new Set();
    const generated = new Set();
    for (const [key, value] of Object.entries(source)) {
      if (['config_provenance', '__vwmExplicitKeys', '__vwmGeneratedKeys'].includes(key)) continue;
      if (key === 'signals' || key === 'profile_locked') explicit.add(key);
      else if (key === 'brand_profile') (source.profile_locked ? explicit : generated).add(key);
      else if (Object.prototype.hasOwnProperty.call(migrationDefaults, key) && JSON.stringify(value) === JSON.stringify(migrationDefaults[key])) generated.add(key);
      else explicit.add(key);
    }
    return { explicit, generated };
  }

  _withExplicitKeys(device, keys = null) {
    const source = { ...(device || {}) };
    const inferred = this._legacyFieldProvenance(source);
    const explicit = keys === null ? inferred.explicit : new Set(keys);
    const generated = keys === null
      ? inferred.generated
      : new Set(Object.keys(source).filter(key => !explicit.has(key) && !['config_provenance', '__vwmExplicitKeys', '__vwmGeneratedKeys'].includes(key)));
    return { ...source, __vwmExplicitKeys: [...explicit], __vwmGeneratedKeys: [...generated] };
  }

  _decorateLegacyProfile(device) {
    const source = device && typeof device === 'object' ? device : {};
    const provenance = this._legacyFieldProvenance(source);
    const profile = BRAND_PROFILES[source.brand_profile];
    const decorated = profile ? { ...profile, ...source } : { ...source };
    return {
      ...decorated,
      __vwmExplicitKeys: [...provenance.explicit],
      __vwmGeneratedKeys: [...new Set([
        ...provenance.generated,
        ...Object.keys(profile || {}).filter(key => !provenance.explicit.has(key)),
      ])],
    };
  }

  _withBackendDescriptor(device) {
    const descriptor = this._backendDescriptor(device);
    if (!descriptor) return device || {};
    const explicit = this._explicitDeviceKeys(device);
    const generated = this._generatedDeviceKeys(device);
    const signals = descriptor.signals && typeof descriptor.signals === 'object' ? descriptor.signals : {};
    const merged = { ...(device || {}), vacuum_entity: descriptor.entity_id || device?.vacuum_entity };
    const bindingFields = new Set([
      'water_volume_sensor','water_volume_reservoir','water_anchor_reservoir','refill_on_clear','water_total_ml','tracked_capacity_ml','tank_ml','tracked_reservoir','low_water_anchor_remaining_percent','signals',
      'status_sensor','cleaning_active_sensor','area_sensor','duration_sensor',
      'area_attribute','area_attribute_unit','duration_attribute','duration_attribute_unit','mop_intensity_attribute','water_box_attached_attribute','tank_semantics_confirmed','mop_evidence_required','signal_contract_version',
      'mop_mode_entity','mop_intensity_entity','cleaning_mode_entity','mop_attached_sensor','water_box_attached_sensor','water_box_detached_sensor',
      'usage_ml_per_m2','usage_ml_per_active_minute','rate_signal','calibration_scope','water_per_m2','intensity_factor','wash_volume_ml','mop_wash_ml',
      'accounting_evidence','time_accounting_evidence','estimated_m2_per_active_minute','evidence','profile_locked','profile_override','locked_profile','brand_profile',
      'dock_error_sensor','water_sensor','water_used_sensor','water_used_input',
      'dock_clean_water_sensor','dock_dirty_water_sensor','water_shortage_sensor','water_error_sensor','dock_status_sensor','tank_level_sensor','dock_tank_level_sensor','reset_door_sensor',
      'filter_sensor','last_session_sensor','last_reset_entity','main_brush_sensor','side_brush_sensor',
      'filter_time_sensor','sensor_dirty_sensor','dock_brush_sensor','dock_strainer_sensor',
      'mop_drying_sensor','last_clean_start','last_clean_end','charge_sensor','uncertainty_percent',
    ]);
    for (const key of generated) if (bindingFields.has(key)) delete merged[key];
    // Match backend merge semantics: an authored `signals: {}` is an opt-out,
    // and every authored YAML field wins over discovery. Unmarked legacy card
    // profile defaults are not authored configuration and can be superseded.
    if (!explicit.has('signals')) {
      const effectiveSignals = { ...signals };
      for (const role of [
        'status_sensor','cleaning_active_sensor','area_sensor','duration_sensor',
        'mop_mode_entity','mop_intensity_entity','cleaning_mode_entity',
        'mop_attached_sensor','water_box_attached_sensor','water_box_detached_sensor','water_shortage_sensor',
        'dock_clean_water_sensor','dock_dirty_water_sensor','dock_error_sensor','dock_status_sensor','water_error_sensor','tank_level_sensor','dock_tank_level_sensor',
      ]) {
        const entity = signals[role];
        if (explicit.has(role)) {
          if (merged[role]) effectiveSignals[role] = merged[role];
          else delete effectiveSignals[role];
        }
        else if (entity) merged[role] = entity;
      }
      merged.signals = effectiveSignals;
    }
    const locked = Boolean(merged.profile_locked) && explicit.has('profile_locked');
    const profileFields = new Set(['profile_key','profile_source','profile_confidence','capability','evidence','tracked_reservoir','tracked_capacity_ml','reservoirs_ml','usage_ml_per_m2','usage_ml_per_active_minute','rate_signal','calibration_scope','wash_volume_ml','accounting_evidence','time_accounting_evidence','estimated_m2_per_active_minute','uncertainty_percent','low_water_anchor_remaining_percent']);
    for (const [key, value] of Object.entries(descriptor)) {
      if (key === 'entity_id' || key === 'vacuum_entity' || key === 'signals' || key === 'name') continue;
      if (locked && profileFields.has(key)) continue;
      if (value != null && !explicit.has(key)) merged[key] = value;
    }
    if (descriptor.name && (!merged.name || merged.name === merged.vacuum_entity)) merged.name = descriptor.name;
    // A hand-picked assignment from the Settings tab is the most recent human
    // decision about this device, so it wins over discovery here exactly as it
    // does in the backend tick — otherwise the card would render one binding
    // while the water counter used another.
    const signalOverrides = this._signalOverridesFor(merged.vacuum_entity);
    const overriddenRoles = Object.keys(signalOverrides).filter(role => this._overridableSignalRoles().has(role));
    if (overriddenRoles.length) {
      const overriddenSignals = { ...(merged.signals && typeof merged.signals === 'object' ? merged.signals : {}) };
      for (const role of overriddenRoles) {
        const entityId = signalOverrides[role];
        if (typeof entityId !== 'string' || !entityId.trim()) continue;
        merged[role] = entityId.trim();
        overriddenSignals[role] = entityId.trim();
      }
      merged.signals = overriddenSignals;
    }
    return merged;
  }

  _customCalibrationKey(device = null) {
    const active = device || this._getDevices()[this._activeDeviceIdx] || null;
    const entity = String(active?.vacuum_entity || '').trim().toLowerCase();
    if (entity) return `entity:${entity}`;
    return this._resolveProfileKey(active) || active?.brand_profile || this._config?.brand_profile || 'default';
  }

  _customCalibrationFor(device, customMap = null) {
    const custom = customMap || this._serverState?.settings?.custom_calibration || {};
    if (!custom || typeof custom !== 'object') return null;
    const entity = String(device?.vacuum_entity || '').trim().toLowerCase();
    const profile = device?.brand_profile;
    const resolved = this._resolveProfileKey(device);
    const keys = [
      entity ? `entity:${entity}` : '',
      profile || '',
      resolved || '',
      'default',
    ];
    for (const key of [...new Set(keys.filter(Boolean))]) {
      if (custom[key] && typeof custom[key] === 'object') return custom[key];
    }
    return null;
  }

  _normaliseCalibrationLayer(layer) {
    const source = layer && typeof layer === 'object' ? layer : {};
    const normalized = { ...source };
    const usage = {};
    for (const key of ['water_per_m2', 'usage_ml_per_m2']) {
      if (source[key] && typeof source[key] === 'object') Object.assign(usage, source[key]);
    }
    if (Object.keys(usage).length) normalized.usage_ml_per_m2 = usage;
    delete normalized.water_per_m2;
    for (const [canonical, legacy] of [['wash_volume_ml', 'mop_wash_ml'], ['tracked_capacity_ml', 'tank_ml']]) {
      const canonicalValue = Number(source[canonical]);
      const legacyValue = Number(source[legacy]);
      if (Number.isFinite(canonicalValue) && canonicalValue > 0) normalized[canonical] = canonicalValue;
      else if (Number.isFinite(legacyValue) && legacyValue > 0) normalized[canonical] = legacyValue;
      else delete normalized[canonical];
      delete normalized[legacy];
    }
    return normalized;
  }

  _effectiveCustomCalibration(device, customMap = null) {
    const custom = customMap || this._serverState?.settings?.custom_calibration || {};
    if (!custom || typeof custom !== 'object') return {};
    const entity = String(device?.vacuum_entity || '').trim().toLowerCase();
    const profile = device?.profile_key || this._resolveProfileKey(device);
    const keys = ['default', profile, entity ? `entity:${entity}` : ''].filter(Boolean);
    const merged = {};
    for (const key of keys) {
      const layer = custom[key];
      if (!layer || typeof layer !== 'object') continue;
      for (const [name, value] of Object.entries(this._normaliseCalibrationLayer(layer))) {
        merged[name] = value && typeof value === 'object' && !Array.isArray(value) && merged[name] && typeof merged[name] === 'object'
          ? { ...merged[name], ...value }
          : value;
      }
    }
    return merged;
  }

  _getDevices() {
    const devices = this._getDeviceCandidates();
    const groups = new Map();
    const stored = this._serverState?.tank_states || {};
    for (const device of devices) {
      const descriptor = this._backendDescriptor(device);
      const key = descriptor?.identity_group || device.vacuum_entity;
      const current = groups.get(key);
      const rank = d => [Object.hasOwn(stored, d.vacuum_entity) ? 0 : 1,
        ['matter', 'generic'].includes(this._backendDescriptor(d)?.integration_adapter) ? 1 : 0,
        d.vacuum_entity || ''].join('|');
      if (!current || rank(device) < rank(current)) groups.set(key, device);
    }
    return [...groups.values()];
  }

  _getDeviceCandidates() {
    if (this._config.devices && Array.isArray(this._config.devices)) {
      return this._config.devices.map(d => this._withBackendDescriptor(this._decorateLegacyProfile(d)));
    }
    // Single device mode
    const single = {};
    const keys = [
      'device_name','water_volume_sensor','water_volume_reservoir','water_anchor_reservoir','refill_on_clear','water_sensor','water_used_sensor','water_used_input','water_total_ml',
      'vacuum_entity','dock_error_sensor','filter_sensor','last_session_sensor',
      'last_reset_entity','main_brush_sensor','side_brush_sensor','filter_time_sensor',
      'sensor_dirty_sensor','dock_brush_sensor','dock_strainer_sensor',
      'dock_clean_water_sensor','dock_dirty_water_sensor','water_shortage_sensor','water_error_sensor',
      'mop_attached_sensor','water_box_attached_sensor','mop_drying_sensor','area_sensor','duration_sensor','cleaning_active_sensor',
      'last_clean_start','last_clean_end','charge_sensor','status_sensor',
      'reset_door_sensor','mop_mode_entity','mop_intensity_entity','cleaning_mode_entity',
      'usage_ml_per_m2','usage_ml_per_active_minute','rate_signal','calibration_scope',
      'water_per_m2','intensity_factor','wash_volume_ml','mop_wash_ml','icon',
      'brand_profile','tracked_capacity_ml','tank_ml','tracked_reservoir','signals',
      'accounting_evidence','evidence','uncertainty_percent','profile_locked','profile_override','locked_profile',
      'area_anomaly_ceiling_m2',
    ];
    const authoredSingle = this._authoredConfigKeys || new Set();
    keys.forEach(k => { if (authoredSingle.has(k)) single[k] = this._config[k]; });
    if (Object.keys(single).length === 0) {
      const serverDevices = (this._userDevices && this._userDevices.length)
        ? this._userDevices
        : (this._discoveredVacuums || []).map(v => ({
            vacuum_entity: v.entity_id,
            name: v.name || v.entity_id,
            icon: '\uD83E\uDD16',
          }));
      return serverDevices.map(d => {
        return this._withBackendDescriptor(this._decorateLegacyProfile(d));
      });
    }
    single.name = single.device_name || this._config.device_name || 'Vacuum';
    // Merge config single device + user-added devices
    const userDevs = (this._userDevices || []).filter(ud => ud.vacuum_entity !== single.vacuum_entity).map(d => {
      return this._decorateLegacyProfile(d);
    });
    const singleProvenance = this._withAuthoredProvenance(
      single,
      [...(this._authoredConfigKeys || [])].filter(key => key in single)
    );
    return [this._decorateLegacyProfile(singleProvenance), ...userDevs].map(d => this._withBackendDescriptor(d));
  }

  // Old backends return no stable physical-device identity. Keep every vacuum
  // entity in that fallback instead of guessing that a shared manufacturer
  // means the native/Matter entities are one physical robot.
  _autoDiscoverVacuums() {
    if (this._discoveredVacuums && this._discoveredVacuums.length) return this._discoveredVacuums;
    if (!this._hass) return [];
    const all = Object.values(this._hass.states)
      .filter(s => s.entity_id.startsWith('vacuum.'));
    return all
      .map(s => ({
        entity_id: s.entity_id,
        name: (s.attributes && s.attributes.friendly_name) || s.entity_id,
        state: s.state,
        battery: s.attributes && s.attributes.battery_level,
      }));
  }

  _calcDeviceData(device) {
    device = this._withBackendDescriptor(device);
    // The descriptor is authoritative when available. The old client catalog
    // is retained strictly as a fallback for pre-5.2 integration responses.
    const profileKey = this._resolveProfileKey(device);
    const calib = profileKey ? (CALIBRATION_DATA[profileKey] || null) : null;
    const customCalib = this._effectiveCustomCalibration(device);
    const explicit = this._explicitDeviceKeys(device);
    const configuredCapacity = ['water_total_ml', 'tracked_capacity_ml', 'tank_ml']
      .filter(key => explicit.has(key))
      .map(key => Number(device[key])).find(value => Number.isFinite(value) && value > 0);
    const descriptor = this._backendDescriptor(device);
    const backendCapacity = descriptor ? Number(descriptor.tracked_capacity_ml) : null;
    const profileCapacity = calib ? Number(calib.tank_ml) : null;
    const lockedProfile = Boolean(device.profile_locked) && explicit.has('profile_locked');
    const resolvedCapacity = lockedProfile
      ? (Number.isFinite(profileCapacity) && profileCapacity > 0 ? profileCapacity : null)
      : (Number.isFinite(backendCapacity) && backendCapacity > 0 ? backendCapacity : null);
    const totalMl = configuredCapacity || customCalib.tracked_capacity_ml || resolvedCapacity || ((!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'profile_key')) && Number.isFinite(profileCapacity) && profileCapacity > 0 ? profileCapacity : 0);
    let remainingL = null, percentRemaining = null, usedMl = null;
    const tankState = this._loadWaterState(device);
    const legacyResetTs = Number(tankState.last_reset_ts);
    let initialized = Boolean(
      tankState.initialized
      || tankState.last_reset_iso
      || (Number.isFinite(legacyResetTs) && legacyResetTs > 0)
    );
    let stateReason = initialized ? (tankState.last_accounting_reason || null) : 'awaiting_refill';

    // The integration state machine populates usedMl when no live water sensor exists.
    const configMissing = false; // standalone mode works out of the box — never flag as misconfigured

    // A fresh Store record defaults used_ml to zero. Treating that default as a
    // refill would falsely manufacture a 100% tank. Only show accounting after
    // an explicit/manual refill baseline has initialized the state.
    if (totalMl > 0 && initialized) {
      const jsUsed = tankState.used_ml;
      if (typeof jsUsed === 'number' && Number.isFinite(jsUsed)) {
        usedMl = jsUsed;
        remainingL = Math.max(0, totalMl - usedMl) / 1000;
        percentRemaining = Math.max(0, Math.min(100, (totalMl - usedMl) / totalMl * 100));
        if (tankState.water_empty_active && tankState.water_anchor_kind === 'empty') {
          remainingL = 0;
          percentRemaining = 0;
        }
      }
    }

    const userRate = Boolean(customCalib.usage_ml_per_m2 || customCalib.water_per_m2 || customCalib.usage_ml_per_active_minute || customCalib.wash_volume_ml || customCalib.mop_wash_ml)
      || ['usage_ml_per_m2', 'usage_ml_per_active_minute', 'wash_volume_ml'].some(key => explicit.has(key))
      || Boolean(device.consumption_calibration);
    const hasMopSignal = ['mop_attached_sensor', 'mop_mode_entity', 'cleaning_mode_entity', 'water_box_attached_sensor', 'water_box_attached_attribute', 'water_box_detached_sensor'].some(key => device[key])
      || Boolean(device.mop_intensity_entity && device.mop_intensity_is_evidence);
    if (!userRate && device.estimate_basis && device.mop_evidence_required === true && !hasMopSignal) {
      remainingL = percentRemaining = usedMl = null;
      stateReason = 'mop_signal_unbound';
    }

    if (tankState.accounting_incomplete) {
      remainingL = percentRemaining = usedMl = null;
      stateReason = 'accounting_incomplete';
    }

    if (device.accounting_event_sensor) {
      const balance = tankState.accounting_v2 || {};
      const measured = balance.balances_ml?.[device.tracked_reservoir];
      const valid = balance.status === 'known' && typeof measured === 'number' && Number.isFinite(measured) && measured >= 0;
      initialized = valid;
      remainingL = valid ? measured / 1000 : null;
      percentRemaining = usedMl = null;
      stateReason = valid ? null : (balance.reason || 'unknown_stream_reservoir');
    }

    if (device.water_volume_sensor || tankState.last_accounting_source === 'real_sensor') {
      const measured = tankState.last_water_volume_ml;
      const valid = typeof measured === 'number' && Number.isFinite(measured) && measured >= 0;
      initialized = valid;
      stateReason = tankState.last_accounting_reason || null;
      remainingL = valid ? measured / 1000 : null;
      usedMl = valid && totalMl > 0 ? Math.max(0, totalMl - measured) : null;
      percentRemaining = valid && totalMl > 0 ? Math.max(0, Math.min(100, measured / totalMl * 100)) : null;
    }

    const dockErr = this._getStateValue(device.dock_error_sensor);
    const waterAnchorKind = tankState.water_anchor_kind || null;
    const anchorActive = Boolean(tankState.water_empty_active);
    const waterLow = anchorActive && waterAnchorKind === 'shortage';
    const waterEmpty = anchorActive && !waterLow;
    const vacState = this._getStateValue(device.vacuum_entity);
    const isCleaning = ['cleaning', 'running', 'sweeping', 'mopping', 'vacuuming'].includes(this._normaliseModelKey(vacState));
    const charge = this._getStateValue(device.charge_sensor) ||
      this._getAttr(device.vacuum_entity, 'battery_level');

    let filterDays = null;
    const filterRaw = this._getStateValue(device.filter_sensor);
    if (filterRaw !== null && filterRaw !== 'unavailable') filterDays = parseFloat(filterRaw);

    let sessionMl = null;
    const sessionRaw = this._getStateValue(device.last_session_sensor);
    if (sessionRaw !== null && sessionRaw !== 'unavailable') sessionMl = parseFloat(sessionRaw);

    const lastReset = this._getEffectiveLastReset(device);

    // Cleaning stats
    const areaCleaned = this._getStateValue(device.area_sensor) ?? this._getAttr(device.vacuum_entity, device.area_attribute);
    const durationSec = this._getStateValue(device.duration_sensor) ?? this._getAttr(device.vacuum_entity, device.duration_attribute);
    const lastCleanStart = this._getStateValue(device.last_clean_start);
    const lastCleanEnd = this._getStateValue(device.last_clean_end);

    const _parseHours = (sensor) => {
      const raw = this._getStateValue(sensor);
      if (raw === null || raw === 'unavailable' || raw === 'unknown') return null;
      return parseFloat(raw);
    };

    const mainBrushH = _parseHours(device.main_brush_sensor);
    const sideBrushH = _parseHours(device.side_brush_sensor);
    const filterH = _parseHours(device.filter_time_sensor);
    const sensorH = _parseHours(device.sensor_dirty_sensor);
    const dockBrushH = _parseHours(device.dock_brush_sensor);
    const dockStrainerH = _parseHours(device.dock_strainer_sensor);

    const dockCleanWaterState = this._normaliseModelKey(this._getStateValue(device.dock_clean_water_sensor));
    const dockDirtyWaterState = this._normaliseModelKey(this._getStateValue(device.dock_dirty_water_sensor));
    const dockCleanWaterProblem = ['on', 'empty', 'missing'].includes(dockCleanWaterState);
    const dockDirtyWaterProblem = ['on', 'full', 'missing'].includes(dockDirtyWaterState);
    const dockCleanWaterFull = dockCleanWaterProblem; // compatibility with old render helpers
    const dockDirtyWaterFull = dockDirtyWaterProblem;
    const waterShortage = ['on', 'true', 'shortage', 'low'].includes(this._normaliseModelKey(this._getStateValue(device.water_shortage_sensor)));
    const mopAttached = ['on', 'true', 'attached', 'installed', 'present', 'ok'].includes(this._normaliseModelKey(this._getStateValue(device.mop_attached_sensor)));
    const mopDrying = ['on', 'true', 'active', 'drying', 'drying_mop'].includes(this._normaliseModelKey(this._getStateValue(device.mop_drying_sensor)));
    const tankLevel = this._getStateValue(device.tank_level_sensor);
    const dockTankLevel = this._getStateValue(device.dock_tank_level_sensor);

    return {
      totalMl, remainingL, percentRemaining, usedMl,
      initialized, stateReason,
      profileKey: device.profile_key || profileKey || null,
      profileSource: device.profile_source || (device.profile_key ? 'backend' : 'legacy_client_fallback'),
      profileConfidence: device.profile_confidence || null,
      integrationAdapter: device.integration_adapter || null,
      signalContractVersion: device.signal_contract_version ?? null,
      mopEvidenceRequired: device.mop_evidence_required === true,
      capability: device.capability || 'unknown',
      evidence: device.evidence || null,
      accountingEvidence: tankState.last_accounting_evidence || ((customCalib.usage_ml_per_m2 || customCalib.wash_volume_ml) ? 'user_calibration' : device.accounting_evidence || null),
      accountingSource: tankState.last_accounting_source || null,
      accountingRate: tankState.last_accounting_rate_ml ?? null,
      consumptionResolution: tankState.consumption_resolution || null,
      reservoirLevels: tankState.reservoir_levels || null,
      accountingV2: tankState.accounting_v2 || null,
      estimateBasis: userRate ? null : (device.estimate_basis || null),
      mopSystem: device.mop_system || null,
      calibrationLogFactors: _vwmStoredWindow(tankState) || [],
      calibrationHistory: Array.isArray(tankState.calibration_history) ? tankState.calibration_history : [],
      uncertaintyPercent: userRate ? null : device.estimate_basis
        ? _vwmUncertainty(device.estimate_basis, _vwmStoredWindow(tankState)
          || (Number(tankState.calibration_samples) > 0 && Number(tankState.calibration_factor) > 0 ? [Math.log(Number(tankState.calibration_factor))] : []))
        : (Number.isFinite(Number(device.uncertainty_percent)) ? Number(device.uncertainty_percent) : null),
      lastResetSource: tankState.last_reset_source || null,
      refillHistory: Array.isArray(tankState.refill_history) ? tankState.refill_history : [],
      calibrationPending: tankState.calibration_pending_log_factor != null,
      intensityUnmapped: tankState.intensity_unmapped || null,
      bridgedGaps: Number.isFinite(Number(tankState.bridged_gaps)) ? Number(tankState.bridged_gaps) : 0,
      calibrationFactor: Number.isFinite(Number(tankState.calibration_factor)) ? Number(tankState.calibration_factor) : 1,
      calibrationSamples: Number.isFinite(Number(tankState.calibration_samples)) ? Number(tankState.calibration_samples) : 0,
      estimatedM2PerActiveMinute: Number.isFinite(Number(device.estimated_m2_per_active_minute)) ? Number(device.estimated_m2_per_active_minute) : null,
      waterAnchorSource: tankState.water_anchor_source || null,
      waterAnchorKind: tankState.water_anchor_kind || null,
      waterAnchorConfidence: tankState.water_anchor_confidence || null,
      tankSemanticsConfirmed: device.tank_semantics_confirmed === true,
      tankLevel, dockTankLevel,
      reservoirsMl: device.reservoirs_ml && typeof device.reservoirs_ml === 'object' ? device.reservoirs_ml : {},
      trackedReservoir: device.tracked_reservoir || null,
      signals: device.signals && typeof device.signals === 'object' ? device.signals : {},
      waterEmpty, waterLow, isCleaning, filterDays, sessionMl, lastReset, vacState, charge,
      mainBrushH, sideBrushH, filterH, sensorH, dockBrushH, dockStrainerH,
      dockCleanWaterState, dockDirtyWaterState, dockCleanWaterProblem, dockDirtyWaterProblem,
      dockCleanWaterFull, dockDirtyWaterFull, waterShortage, mopAttached, mopDrying,
      areaCleaned, durationSec, lastCleanStart, lastCleanEnd,
      configMissing,
    };
  }

  _getStatus(data, cfg) {
    if (data.totalMl === 0) return { label: 'No Water', color: '#6b7280', icon: '\uD83D\uDCA7' };
    if (data.waterEmpty) return { label: 'EMPTY', color: '#ef4444', icon: '\u26A0\uFE0F' };
    if (data.waterLow || data.waterShortage) return { label: 'LOW WATER', color: '#f59e0b', icon: '\u26A0\uFE0F' };
    if (data.percentRemaining === null) return { label: 'Unknown', color: '#6b7280', icon: '\u2753' };
    if (data.percentRemaining <= (cfg.critical_threshold || 10)) return { label: 'Critical', color: '#ef4444', icon: '\uD83D\uDEA8' };
    if (data.percentRemaining <= (cfg.warning_threshold || 20)) return { label: 'Low', color: '#f59e0b', icon: '\u26A0\uFE0F' };
    return { label: 'OK', color: '#22c55e', icon: '\u2705' };
  }

  _formatReset(dt) {
    if (!dt || dt === 'unknown') return 'Never';
    try {
      const d = new Date(dt);
      if (isNaN(d.getTime())) return dt;
      const now = new Date();
      const diffH = (now - d) / 3600000;
      if (diffH < 1) return 'Just now';
      if (diffH < 24) return Math.round(diffH) + 'h ago';
      return Math.round(diffH / 24) + ' days ago';
    } catch { return dt; }
  }

  _hoursToDisplay(hours) {
    if (hours === null) return null;
    if (hours < 0) return { text: 'Overdue', color: '#ef4444' };
    const h = Math.round(hours);
    if (h < 24) return { text: h + 'h', color: h < 5 ? '#ef4444' : '#f59e0b' };
    const d = Math.round(hours / 24);
    return { text: d + ' days', color: d < 3 ? '#ef4444' : d < 14 ? '#f59e0b' : '#22c55e' };
  }

  _formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return null;
    const sec = parseInt(seconds);
    const m = Math.floor(sec / 60);
    const h = Math.floor(m / 60);
    if (h > 0) return h + 'h ' + (m % 60) + 'm';
    return m + 'm';
  }

  // ── GAUGE SVG ─────────────────────────────────────────────────────────────

  _buildGaugeSVG(percent, color, size = 110) {
    const r = 42, cx = 55, cy = 55;
    const circumference = 2 * Math.PI * r;
    const clampedPct = Math.max(0, Math.min(100, percent || 0));
    const dashOffset = circumference * (1 - clampedPct / 100);
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 110 110">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--vwm-overlay-medium, rgba(0,0,0,0.1))" stroke-width="9"/>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
          stroke="${color}" stroke-width="9"
          stroke-dasharray="${circumference}"
          stroke-dashoffset="${dashOffset}"
          stroke-linecap="round"
          transform="rotate(-90 ${cx} ${cy})"
          style="transition: stroke-dashoffset 0.6s ease; filter: drop-shadow(0 0 4px ${color})"/>
        <text x="${cx}" y="${cy - 3}" text-anchor="middle" fill="var(--vwm-text, #1a1a2e)" font-size="17" font-weight="700" font-family="Inter,sans-serif">
          ${percent !== null ? Math.round(clampedPct) + '%' : '--'}
        </text>
        <text x="${cx}" y="${cy + 13}" text-anchor="middle" fill="var(--vwm-text-secondary, #6b7280)" font-size="9" font-family="Inter,sans-serif">remaining</text>
      </svg>`;
  }

  _buildBatteryBar(charge) {
    if (charge === null) return '';
    const pct = parseInt(charge) || 0;
    const color = pct < 20 ? '#ef4444' : pct < 40 ? '#f59e0b' : '#22c55e';
    return `<div class="battery-bar">
      <span class="battery-icon">\uD83D\uDD0B</span>
      <div class="battery-track"><div class="battery-fill" style="width:${pct}%;background:${color}"></div></div>
      <span class="battery-pct" style="color:${color}">${pct}%</span>
    </div>`;
  }

  // ── TAB: WATER ─────────────────────────────────────────────────────────────

  _buildWaterTab(device, data) {
    const cfg = this._config;
    const status = this._getStatus(data, cfg);
    const gaugeSvg = data.totalMl > 0 ? this._buildGaugeSVG(data.percentRemaining, status.color) : '';

    const remainingText = data.remainingL != null ? `${Number(data.remainingL).toFixed(2)} L` : '--';
    const usedText = data.usedMl != null ? `${(Number(data.usedMl) / 1000).toFixed(2)} L` : '--';

    const vacStateChip = data.vacState
      ? `<span class="chip ${data.isCleaning ? 'chip-active' : 'chip-idle'}">${data.isCleaning ? '\uD83E\uDDF9 Cleaning' : '\uD83D\uDECC Idle'}</span>`
      : '';

    let extraRows = '';
    if (cfg.show_session !== false && data.sessionMl != null && !isNaN(data.sessionMl)) {
      extraRows += `<div class="row"><span class="row-label">\uD83D\uDCA7 Last session</span><span class="row-val">${data.sessionMl} ml</span></div>`;
    }
    if (cfg.show_filter !== false && data.filterDays != null && !isNaN(data.filterDays)) {
      const filterColor = data.filterDays < 7 ? '#ef4444' : data.filterDays < 30 ? '#f59e0b' : '#22c55e';
      extraRows += `<div class="row"><span class="row-label">\uD83D\uDD0D Filter life</span><span class="row-val" style="color:${filterColor}">${(data.filterDays || 0).toFixed(0)} days</span></div>`;
    }
    if (data.lastReset) {
      const refillSource = data.lastResetSource && VWM_REFILL_SOURCE_LABEL[data.lastResetSource] ? ` \u00B7 ${VWM_REFILL_SOURCE_LABEL[data.lastResetSource]}` : '';
      extraRows += `<div class="row"><span class="row-label">\uD83D\uDD04 Last refill</span><span class="row-val">${_esc(this._formatReset(data.lastReset) + refillSource)}</span></div>`;
    }
    if (data.charge !== null && data.charge !== undefined) {
      extraRows += this._buildBatteryBar(data.charge);
    }

    // Refill button resets the integration's HA Store state.
    const refillBtn = (cfg.show_refill_button !== false)
      ? `<button class="refill-btn" data-vacuum="${_esc(device.vacuum_entity || '')}">\uD83D\uDCA7 Refilled</button>` : '';

    const alertBanner = (data.waterEmpty || data.waterShortage)
      ? `<div class="alert-banner">\u26A0\uFE0F Water shortage! Please refill now.</div>`
      : (data.dockDirtyWaterFull ? `<div class="alert-banner alert-warn">\u26A0\uFE0F Dirty water box is full - empty it.</div>` : '')
        + (data.percentRemaining !== null && data.percentRemaining <= (cfg.critical_threshold || 10) && !data.waterEmpty
          ? `<div class="alert-banner alert-warn">\u26A0\uFE0F Water low (${Math.round(data.percentRemaining)}%) - refill soon.</div>` : '');

    const configMissingBanner = data.configMissing
      ? `<div style="padding:12px 16px;background:rgba(245,158,11,0.08);border:1.5px solid #f59e0b;border-radius:8px;margin-bottom:12px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:18px">\u{1F527}</span>
            <div style="font-size:13px;color:var(--bento-text,#1a1a2e);">
              <b>Setup:</b> The water counter is not ready yet. Check the vacuum entity configuration.
            </div>
          </div>
        </div>`
      : '';

    const accountingHtml = this._buildAccountingGuidance(data);
    const diagnosticsHtml = this._buildDiagnostics(data);

    const dockHtml = (cfg.show_dock_status !== false) ? this._buildDockSection(device, data) : '';
    // Q1/Q2: Calibration info based on brand profile
    let calibHtml = '';
    // Prefer per-device brand_profile (auto-detected) over card-level YAML config.
    // Mirror of the v4 plugin fix — see ha-vacuum-water-monitor.js commit
    // 6f6444a for rationale.
    const profileKey = (device && this._resolveProfileKey(device)) || cfg.brand_profile || 'generic';
    const calib = typeof CALIBRATION_DATA !== 'undefined' ? CALIBRATION_DATA[profileKey] || CALIBRATION_DATA['generic'] : null;
    if (calib) {
      const usage = calib.water_per_m2 || {};
      const levels = Object.entries(usage).map(([k,v]) => `<span style="display:inline-block;padding:3px 10px;background:var(--bento-bg,#f0f4f8);border-radius:6px;margin:2px 4px;font-size:12px;"><b>${k}:</b> ${v} ml/m²</span>`).join('');
      const referenceUsage = usage.standard || usage.medium || usage.default || Object.values(usage)[0] || null;
      const estAreaPerTank = referenceUsage && data.totalMl > 0 ? Math.round(data.totalMl / referenceUsage) : null;
      const facts = _calibrationFacts(calib);
      calibHtml = `
        <div style="margin-top:16px;padding:16px;background:var(--bento-bg,#f8fafc);border:1.5px solid var(--bento-border,#e2e8f0);border-radius:12px;">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px;">📐 Calibration: ${calib.label}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
            <div>🪣 Tank: <b>${calib.tank_ml ? `${Number(calib.tank_ml).toLocaleString('en-US')} ml` : 'unknown'}</b></div>
            <div>🧹 Mop: <b>${_esc(calib.mop_type || (calib.mop_system && calib.mop_system !== 'unknown' ? String(calib.mop_system).replace(/_/g, ' ') : 'unknown'))}</b></div>
            ${calib.avg_area_per_charge ? `<div>📏 Est. area/charge: <b>~${calib.avg_area_per_charge} m²</b></div>` : ''}
            ${estAreaPerTank ? `<div>📏 Est. floor area/tank: <b>~${estAreaPerTank} m²</b> <span style="font-size:11px;color:var(--bento-text-secondary,#64748b)">(standard route, excl. washes)</span></div>` : ''}
          </div>
          ${facts.length ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:10px">${facts.map(fact => `<span style="padding:3px 8px;border-radius:6px;background:rgba(59,130,246,0.08);font-size:11px;color:var(--bento-text-secondary,#64748b)">${_esc(fact)}</span>`).join('')}</div>` : ''}
          ${levels ? `<div style="margin-top:10px;font-size:12px;"><b>Estimated water usage per m²${calib.uncertainty_percent ? ` (\u00B1${calib.uncertainty_percent}%)` : ''}:</b> ${levels}</div>` : `<div style="margin-top:10px;font-size:12px;color:var(--bento-text-secondary,#64748b)">${calib.estimate_basis ? _esc(VWM_BASIS_LABEL[calib.estimate_basis] || '') + ' \u00B7 calibrates automatically.' : 'No estimate for this model yet; set the tank capacity to enable tracking.'}</div>`}
          ${calib.notes ? '<div style="margin-top:8px;font-size:12px;color:var(--bento-text-secondary,#64748b);font-style:italic;">💡 ' + calib.notes + '</div>' : ''}
        </div>`;
    }


    // Only show "doesn't track water" if no water tracking capability at all:
    // No explicit water_total_ml AND no brand_profile match AND no water sensors
    const noWaterTracking = !device.water_total_ml &&
      !data.totalMl &&  // No calibration data either
      !device.water_sensor;

    return `
      <div class="tab-content">
        ${alertBanner}
        ${configMissingBanner}
        ${accountingHtml}
        ${noWaterTracking ? `<div class="no-water-note">\uD83D\uDCCC This device doesn't track water levels</div>` : `
        <div class="device-body">
          <div class="gauge-wrap">
            ${gaugeSvg}
            ${vacStateChip}
          </div>
          <div class="details">
            <div class="row"><span class="row-label">\uD83D\uDD30 Remaining</span><span class="row-val">${remainingText} / ${data.totalMl > 0 ? (data.totalMl / 1000).toFixed(1) : "--"} L</span></div>
            <div class="row"><span class="row-label">\uD83D\uDCA6 Used</span><span class="row-val">${usedText}</span></div>
            ${extraRows}
          </div>
        </div>
        ${refillBtn ? `<div class="refill-wrap">${refillBtn}</div>` : ''}`}
        ${noWaterTracking && data.charge !== null ? `<div class="details">${this._buildBatteryBar(data.charge)}</div>` : ''}
        ${dockHtml}
        ${diagnosticsHtml}
        ${calibHtml}
      </div>`;
  }

  _buildAccountingGuidance(data) {
    const box = (title, text, color = '#64748b') => `<div class="accounting-guidance" style="border-color:${color}"><b>${title}</b><span>${text}</span></div>`;
    if (data.stateReason === 'mop_signal_unbound') {
      return box('Mop signal needed.', 'This robot does not expose a signal that shows when it mops (mop attached, mop mode or water level). Map one in Settings \u2192 Signal mapping so water use can be estimated.', '#f59e0b');
    }
    if (data.stateReason === 'accounting_incomplete') {
      return box('Water balance paused.', 'Water may have been used while a signal was missing, so the remaining volume is unknown until the next refill. Tracking continues automatically after that refill.', '#f59e0b');
    }
    if (!data.initialized) {
      const capability = data.capability === 'manual_only'
        ? ' Manual-only: add calibration and use manual refill to maintain the estimate.'
        : '';
      return box('Needs a refill baseline.', `Water remaining and used are unknown until you press Refilled with a full tracked reservoir.${capability}`, '#f59e0b');
    }
    const blockedReasons = {
      water_anchor_reservoir_unverified: 'The water warning does not identify the tracked reservoir. Accounting is unchanged.',
      shortage_volume_unmeasured: 'Low-water threshold has no measured remaining volume. It cannot calibrate consumption.',
      accounting_context_changed: 'Model or accounting signals changed. A new sample baseline is being established.',
      vacuum_unavailable: 'The vacuum is missing or unavailable. Accounting is paused.',
      duration_unavailable: 'The configured duration signal is unavailable. No elapsed time is inferred.',
      real_sensor_unavailable: 'The authoritative volume sensor is unavailable. Estimates will not replace it.',
      real_sensor_reservoir_unverified: 'Confirm which reservoir the volume sensor measures.',
      real_sensor_unit_unknown: 'Volume sensor must publish mL or L.',
    };
    if (blockedReasons[data.stateReason]) return box('Accounting paused.', blockedReasons[data.stateReason], '#f59e0b');
    if (data.accountingSource === 'real_sensor') return box('Measured volume.', 'The configured sensor for this reservoir takes precedence over all estimates.');
    if (data.stateReason === 'water_empty'  || data.waterEmpty) {
      return box('Tracked reservoir is empty.', 'A machine-readable empty state closed this calibration cycle. Refill the reservoir; the learned device factor is preserved.', '#ef4444');
    }
    if (data.stateReason === 'water_low' || data.waterLow || data.waterShortage) {
      const reserve = Number.isFinite(Number(data.percentRemaining)) ? ` The current estimate preserves approximately ${Number(data.percentRemaining)}% reserve.` : '';
      return box('Low-water alert confirmed.', `This threshold is an estimated calibration anchor, not a direct volume measurement.${reserve} Refill the reservoir when convenient; the learned device factor is preserved.`, '#f59e0b');
    }
    if (data.stateReason === 'missing_area_rate' || data.stateReason === 'missing_wash_rate' || data.stateReason === 'missing_time_rate') {
      return box('Missing rate.', 'Automatic estimate is paused until an applicable measured calibration rate is available.', '#f59e0b');
    }
    if (data.stateReason === 'area_unavailable' || data.stateReason === 'area_gap' || data.stateReason === 'status_unavailable') {
      return box('Unavailable signal.', 'Automatic estimate is waiting for a usable configured same-device status or area signal.', '#f59e0b');
    }
    const active = Boolean(data.accountingSource && Number.isFinite(Number(data.accountingRate)) && Number(data.accountingRate) > 0 && !data.stateReason);
    const uncertainty = Number.isFinite(Number(data.uncertaintyPercent))
      ? ` Initial uncertainty: approximately ${Number(data.uncertaintyPercent)}%.`
      : '';
    const samples = Math.max(0, Number(data.calibrationSamples) || 0);
    const accuracy = Number.isFinite(Number(data.uncertaintyPercent)) ? ` About \u00B1${Number(data.uncertaintyPercent)}%.` : '';
    if (samples > 0) {
      const factor = Number.isFinite(Number(data.calibrationFactor)) ? Number(data.calibrationFactor) : 1;
      return box('Calibrated for this robot.', `Calibrated on ${samples} empty ${samples === 1 ? 'tank' : 'tanks'} (correction \u00D7${Number(factor.toFixed(2))}).${accuracy} Every empty-tank signal refines it automatically.`, '#22c55e');
    }
    if (data.estimateBasis) {
      const label = VWM_BASIS_LABEL[data.estimateBasis] || 'Labelled estimate';
      return box(active ? 'Estimating now.' : 'Estimated usage.', `${_esc(label)}.${accuracy} It calibrates automatically the first time the dock reports an empty clean-water tank; no manual measurement is needed.`, '#22c55e');
    }
    if (data.capability === 'manual_only' && active && data.accountingEvidence === 'user_calibration') {
      return box('Measured calibration active.', 'This manual-only model is currently accounting from your measured calibration and same-device signal.', '#22c55e');
    }
    if (data.capability === 'manual_only') {
      return box('Manual-only.', 'This model has capacity data but no published automatic usage telemetry. Add calibration and use manual refill to maintain the estimate.', '#f59e0b');
    }
    if (data.capability === 'automatic_estimate') {
      const activeSource = data.accountingSource === 'active_time'
        ? `Usage is being estimated from active time while mopping because this integration does not expose cleaned area.${uncertainty}`
        : `Usage is being estimated from the discovered mode, intensity, area, and wash signals.${uncertainty}`;
      return box(active ? 'Active automatic estimate.' : 'Automatic estimate ready.', active ? activeSource : `Accounting will begin after a refill baseline when a supported mopping status is observed.${uncertainty}`, '#22c55e');
    }
    return box('Accounting status unknown.', 'No authoritative usage capability was supplied by the integration.', '#64748b');
  }

  _buildDiagnostics(data) {
    const rows = [];
    for (const [name, level] of Object.entries(data.reservoirLevels || {})) {
      if (level && typeof level === 'object') rows.push([`Physical ${name}`, level.volume_ml == null
        ? `Unknown: ${level.reason || 'no measurement'}` : this._formatMl(level.volume_ml)]);
    }
    const balance = data.accountingV2;
    if (balance && typeof balance === 'object') {
      rows.push(['Physical transfer balance', balance.status === 'known' ? 'Measured event stream' : `Unknown: ${balance.reason || 'source unavailable'}`]);
      if (balance.status === 'known') {
        if (balance.source_contract_id) rows.push(['Transfer source', balance.source_contract_id]);
        for (const [name, ml] of Object.entries(balance.balances_ml || {})) {
          if (typeof ml === 'number' && Number.isFinite(ml) && ml >= 0) rows.push([`Balanced ${name}`, this._formatMl(ml)]);
        }
        for (const [label, ml] of [['External supply', balance.external_supply_ml], ['External drain', balance.external_drain_ml]]) {
          if (typeof ml === 'number' && Number.isFinite(ml) && ml >= 0) rows.push([label, this._formatMl(ml)]);
        }
      }
    }
    const resolved = data.consumptionResolution;
    const labelledEstimate = Boolean(data.estimateBasis) && (!resolved || resolved.source === 'unknown');
    if (labelledEstimate) {
      rows.push(['Consumption method', 'Labelled estimate: cleaned area \u00D7 route/water level + dock washes']);
      rows.push(['Evidence tier', Number(data.calibrationSamples) > 0 ? 'Derived estimate, calibrated on this robot' : 'Derived estimate']);
    }
    if (resolved && typeof resolved === 'object' && !labelledEstimate) {
      rows.push(['Consumption method', [resolved.source, resolved.method, resolved.reason].filter(Boolean).join(' / ')]);
      if (resolved.source === 'manufacturer_data') {
        rows.push(['Evidence tier', 'Manufacturer data — limited estimate; not used automatically']);
        if (resolved.label) rows.push(['Estimate label', resolved.label]);
        if (resolved.quantity?.value != null && resolved.quantity?.unit) rows.push(['Declared quantity', `${resolved.quantity.value} ${resolved.quantity.unit}`]);
        if (resolved.basis_ids?.length) rows.push(['Estimate basis', resolved.basis_ids.join(', ')]);
        if (resolved.limitations?.length) rows.push(['Estimate limitations', resolved.limitations.join('; ')]);
      } else if (resolved.source === 'verified_model' || resolved.source === 'device_calibration') {
        rows.push(['Evidence tier', resolved.source === 'device_calibration' ? 'Measured calibration' : 'Measured']);
      } else if (resolved.source === 'unknown') {
        rows.push(['Evidence tier', 'Unknown']);
      }
      if (resolved.profile_id) rows.push(['Consumption profile', resolved.profile_id]);
      if (resolved.dataset_version) rows.push(['Dataset version', resolved.dataset_version]);
      if (resolved.confidence) rows.push(['Consumption evidence', resolved.confidence]);
      if (resolved.validation?.max_error_ml != null) rows.push(['Observed holdout maximum error', `${resolved.validation.max_error_ml} ml (not a guaranteed bound)`]);
      else rows.push(['Independent accuracy', 'Not measured']);
      if (resolved.exposure_domain) rows.push(['Applicable exposure', `${resolved.exposure_domain.min}–${resolved.exposure_domain.max}; ${resolved.unit || ''}`]);
    }
    if (data.integrationAdapter) rows.push(['Integration adapter', data.integrationAdapter]);
    if (data.signalContractVersion != null) rows.push(['Signal contract', `v${data.signalContractVersion}`]);
    if (data.mopEvidenceRequired) rows.push(['Mop accounting gate', 'affirmative mop mode or attachment required']);
    if (data.profileKey) rows.push(['Profile', data.profileKey]);
    if (data.profileSource || data.profileConfidence) rows.push(['Resolution', [data.profileSource, data.profileConfidence].filter(Boolean).join(' / ')]);
    if (data.trackedReservoir || data.totalMl) rows.push(['Tracked reservoir', `${data.trackedReservoir || 'unknown'}${data.totalMl ? ` (${this._formatMl(data.totalMl)})` : ''}`]);
    for (const [key, value] of Object.entries(data.reservoirsMl || {})) {
      if (value != null) rows.push([key, this._formatMl(value)]);
    }
    for (const [role, entity] of Object.entries(data.signals || {})) {
      if (entity) rows.push([role, entity]);
    }
    if (data.accountingSource || data.stateReason || data.accountingEvidence) rows.push(['Accounting', [data.accountingSource, data.accountingRate != null ? `rate ${data.accountingRate}` : null, data.stateReason, data.accountingEvidence].filter(Boolean).join(' / ')]);
    if (data.estimatedM2PerActiveMinute != null && Number.isFinite(Number(data.estimatedM2PerActiveMinute))) rows.push(['Active-time conversion', `${Number(data.estimatedM2PerActiveMinute)} m\u00B2/min`]);
    if (data.estimateBasis) rows.push(['Estimate basis', VWM_BASIS_LABEL[data.estimateBasis] || data.estimateBasis]);
    if (data.mopSystem) rows.push(['Mop system', String(data.mopSystem).replace(/_/g, ' ')]);
    if (data.uncertaintyPercent != null && Number.isFinite(Number(data.uncertaintyPercent))) rows.push(['Estimated accuracy', `\u00B1${Number(data.uncertaintyPercent)}%`]);
    const tanks = (data.calibrationHistory || []).slice(0, 5);
    if (tanks.length) rows.push(['Last empty tanks', tanks.map(t => `${Number.isFinite(Number(t.error_percent)) ? (Number(t.error_percent) > 0 ? '+' : '') + Number(t.error_percent) + '%' : '?'}${t.accepted ? '' : ` (${VWM_TANK_REASON_LABEL[t.reason] || 'skipped'})`}`).join(', ')]);
    if (data.calibrationPending) rows.push(['Calibration check', 'An unusual tank result waits for the next tank to confirm it']);
    if (data.intensityUnmapped) rows.push(['Water level', `\u201C${data.intensityUnmapped}\u201D has no own factor; the average level is used`]);
    if (Number(data.bridgedGaps) > 0) rows.push(['Signal gaps bridged', String(Number(data.bridgedGaps))]);
    const refills = (data.refillHistory || []).slice(0, 5);
    if (refills.length) rows.push(['Recent refills', refills.map(r => `${this._formatReset(r.ts)} (${VWM_REFILL_SOURCE_LABEL[r.source] || r.source})`).join(', ')]);
    if (Number(data.calibrationSamples) > 0) rows.push(['Device calibration', `${Number(data.calibrationSamples)} ${Number(data.calibrationSamples) === 1 ? 'tank' : 'tanks'} / correction \u00D7${Number(Number(data.calibrationFactor || 1).toFixed(2))}`]);
    if (data.waterAnchorSource || data.waterAnchorKind || data.waterAnchorConfidence) rows.push(['Water anchor', [data.waterAnchorSource, data.waterAnchorKind, data.waterAnchorConfidence].filter(Boolean).join(' / ')]);
    if ((data.tankLevel != null || data.dockTankLevel != null) && !data.tankSemanticsConfirmed) {
      rows.push(['Tank percentages', `available (${[data.tankLevel, data.dockTankLevel].filter(value => value != null).join(' / ')}), not used automatically until the model confirms clean/dirty semantics`]);
    }
    if (!rows.length) return '';
    return `<details class="diagnostics"><summary>Diagnostics</summary><div class="diagnostics-grid">${rows.map(([label, value]) => `<span class="diagnostics-label">${_esc(label)}</span><span class="diagnostics-value">${_esc(value)}</span>`).join('')}</div></details>`;
  }

  _formatMl(value) {
    let numeric = NaN;
    try { numeric = Number(value); } catch (err) {}
    return Number.isFinite(numeric) ? `${numeric.toLocaleString('en-US')} ml` : `${_asText(value)} ml`;
  }


  _buildDockSection(device, data) {
    const items = [];
    if (device.dock_clean_water_sensor) {
      const problem = data.dockCleanWaterProblem ?? data.dockCleanWaterFull;
      const value = data.dockCleanWaterState === 'empty' ? 'Empty'
        : data.dockCleanWaterState === 'missing' ? 'Not installed'
        : problem ? 'Out / not installed' : 'OK';
      items.push({ label: '\uD83D\uDCA7 Clean Water Box', value, color: problem ? '#ef4444' : '#22c55e', icon: problem ? '\u26A0\uFE0F' : '\u2705' });
    }
    if (device.dock_dirty_water_sensor) {
      const problem = data.dockDirtyWaterProblem ?? data.dockDirtyWaterFull;
      const value = data.dockDirtyWaterState === 'full' ? 'Full — empty it'
        : data.dockDirtyWaterState === 'missing' ? 'Not installed'
        : problem ? 'Full — empty it' : 'OK';
      items.push({ label: '\uD83E\uDEA3 Dirty Water Box', value, color: problem ? '#ef4444' : '#22c55e', icon: problem ? '\uD83D\uDEA8' : '\u2705' });
    }
    if (device.water_shortage_sensor) {
      items.push({ label: '\uD83D\uDD30 Water Shortage', value: data.waterShortage ? 'Shortage!' : 'Normal', color: data.waterShortage ? '#ef4444' : '#22c55e', icon: data.waterShortage ? '\u26A0\uFE0F' : '\u2705' });
    }
    if (device.mop_attached_sensor) {
      items.push({ label: '\uD83E\uDDF9 Mop Pad', value: data.mopAttached ? (data.mopDrying ? 'Drying...' : 'Attached') : 'Detached', color: data.mopAttached ? (data.mopDrying ? '#f59e0b' : '#22c55e') : '#6b7280', icon: data.mopAttached ? (data.mopDrying ? '\uD83C\uDF2C\uFE0F' : '\u2705') : '\u274C' });
    }
    if (items.length === 0) return '';
    return `<div class="section-block"><div class="section-title">\uD83C\uDFE0 Dock Status</div>
      ${items.map(item => `<div class="dock-row"><span class="row-label">${item.label}</span><span class="dock-val" style="color:${item.color}">${item.icon} ${item.value}</span></div>`).join('')}
    </div>`;
  }

  // ── TAB: MAINTENANCE ───────────────────────────────────────────────────────

  _buildMaintenanceTab(device, data) {
    const customCalibration = this._customCalibrationFor(device) || {};
    const effectiveCalibrationData = this._effectiveCustomCalibration(device);
    const reservoirRows = Object.entries(data.reservoirsMl || {})
      .filter(([, value]) => value != null)
      .map(([name, value]) => `<span>${_esc(name)}: <b>${_esc(this._formatMl(value))}</b></span>`)
      .join(' · ');
    const reservoirLabel = data.trackedReservoir ? `${_asText(data.trackedReservoir).replace(/_/g, ' ')} capacity` : 'Tracked reservoir capacity';
    const effectiveCalibration = `<div style="margin:0 0 12px;padding:10px 12px;background:var(--vwm-overlay-light,rgba(0,0,0,0.04));border-radius:8px;font-size:11px;line-height:1.5"><b>Effective ${_esc(reservoirLabel)}:</b> ${data.totalMl ? _esc(this._formatMl(data.totalMl)) : 'unknown'}${data.trackedReservoir ? ` (${_esc(data.trackedReservoir)})` : ''}<br><b>Effective calibration layers:</b> default → resolved profile → device (${_esc(effectiveCalibrationData.tracked_capacity_ml || 'no device capacity override')})<br><b>Estimate evidence:</b> ${_esc(data.accountingEvidence || data.evidence || 'not available')}<br>${reservoirRows ? `<b>Distinct reservoirs:</b> ${reservoirRows}` : ''}</div>`;
    const savedModeRows = Object.entries(customCalibration.usage_ml_per_m2 || customCalibration.water_per_m2 || {});
    const calibrationModeRows = [
      ...savedModeRows,
      ...Array.from({ length: Math.max(0, 3 - savedModeRows.length) }, () => ['', '']),
    ].map(([name, value]) => `
      <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;min-width:0">
        <input type="text" value="${_esc(String(name))}" placeholder="e.g. standard" style="flex:1;min-width:80px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name" aria-label="Mopping mode name">
        <input type="number" min="0.1" step="0.1" value="${_esc(value === '' ? '' : String(value))}" placeholder="ml/m\u00B2" style="width:70px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val" aria-label="Measured ml per square metre">
      </div>`).join('');
    // Known default max lifespans (hours) per consumable type.
    // These match Roborock factory defaults; other brands vary but are similar order-of-magnitude.
    // The HA sensor may expose a `max` attribute — we prefer that when available.
    const CON_MAX_H = {
      main_brush:    300,
      side_brush:    200,
      filter:        150,
      sensor:         30,
      dock_brush:    300,
      dock_strainer: 200,
    };

    // Helper: resolve life % remaining for a consumable.
    // Tries sensor's own `max` attribute first, then falls back to CON_MAX_H default.
    const _lifePct = (sensorKey, hours) => {
      if (hours === null || isNaN(hours)) return null;
      const sensorField = {
        main_brush:    device.main_brush_sensor,
        side_brush:    device.side_brush_sensor,
        filter:        device.filter_time_sensor,
        sensor:        device.sensor_dirty_sensor,
        dock_brush:    device.dock_brush_sensor,
        dock_strainer: device.dock_strainer_sensor,
      }[sensorKey];
      const attrMax = sensorField ? this._getAttr(sensorField, 'max') : null;
      const maxH = (attrMax !== null && !isNaN(parseFloat(attrMax)) && parseFloat(attrMax) > 0)
        ? parseFloat(attrMax)
        : (CON_MAX_H[sensorKey] || 200);
      if (hours <= 0) return 0;
      return Math.min(100, Math.max(0, (hours / maxH) * 100));
    };

    // Bar color based on life % remaining: GREEN >50%, AMBER 20-50%, RED <=20%
    const _lifePctColor = (pct) => {
      if (pct === null) return '#6b7280';
      if (pct > 50) return '#22c55e';
      if (pct > 20) return '#f59e0b';
      return '#ef4444';
    };

    // HA consumables from sensors
    const haItems = [
      { label: '🧹 Main Brush', hours: data.mainBrushH, key: 'main_brush' },
      { label: '📍 Side Brush', hours: data.sideBrushH, key: 'side_brush' },
      { label: '🔍 Filter', hours: data.filterH, key: 'filter' },
      { label: '💧 Sensor Cleaning', hours: data.sensorH, key: 'sensor' },
      { label: '🔄 Dock Brush', hours: data.dockBrushH, key: 'dock_brush' },
      { label: '🔗 Dock Strainer', hours: data.dockStrainerH, key: 'dock_strainer' },
    ].filter(i => i.hours !== null);

    const haRows = haItems.map(item => {
      const pct = _lifePct(item.key, item.hours);
      if (pct === null) return '';
      const barColor = _lifePctColor(pct);
      const hoursDisp = this._hoursToDisplay(item.hours);
      const pctLabel = Math.round(pct) + '%';
      const hoursLabel = hoursDisp ? hoursDisp.text : '';
      const valLabel = hoursLabel ? `${pctLabel} · ${hoursLabel}` : pctLabel;
      return `<div class="consumable-row">
        <span class="con-label">${item.label}</span>
        <div class="con-bar-wrap"><div class="con-bar"><div class="con-bar-fill" style="background:${barColor};opacity:0.85;width:${pct.toFixed(1)}%"></div></div></div>
        <span class="con-val con-val-wide" style="color:${barColor}">${valLabel}</span>
      </div>`;
    }).join('');
    // Custom maintenance items from HA Store
    const now = Date.now();
    const customRows = this._maintenanceItems.map((item, idx) => {
      const daysSince = item.lastDone ? Math.floor((now - item.lastDone) / 86400000) : null;
      const daysLeft = item.intervalDays && daysSince !== null ? item.intervalDays - daysSince : null;
      let color = '#22c55e', statusText = 'OK';
      if (daysLeft !== null) {
        if (daysLeft < 0) { color = '#ef4444'; statusText = `${Math.abs(daysLeft)}d overdue`; }
        else if (daysLeft < 7) { color = '#f59e0b'; statusText = `${daysLeft}d left`; }
        else { statusText = `${daysLeft}d left`; }
      } else if (daysSince !== null) {
        statusText = `${daysSince}d ago`;
        color = '#6b7280';
      }
      return `<div class="custom-maint-row" data-idx="${idx}">
        <span class="con-label">${_esc(this._sanitize(item.icon || '\uD83D\uDD27'))} ${_esc(this._sanitize(item.name))}</span>
        <span class="con-val" style="color:${color}">${statusText}</span>
        <button class="maint-done-btn" data-idx="${idx}" title="Mark as done today">\u2705</button>
        <button class="maint-del-btn" data-idx="${idx}" title="Delete">\uD83D\uDDD1\uFE0F</button>
      </div>`;
    }).join('');

    return `
      <div class="tab-content">
        ${haRows ? `<div class="section-block"><div class="section-title">\u23F1\uFE0F HA Consumables</div>${haRows}</div>` : ''}
        ${haItems.length === 0 && this._maintenanceItems.length === 0 ? '<div class="empty-state">No maintenance data available.<br>Add custom items below.</div>' : ''}
        ${this._maintenanceItems.length > 0 ? `<div class="section-block"><div class="section-title">\uD83D\uDCCB Custom Maintenance</div>${customRows}</div>` : ''}
        <div class="section-block">
          <div class="section-title">\u2795 Add Maintenance Item</div>
          <div class="add-maint-form">
            <input class="maint-input" id="maint-name" placeholder="Name (e.g. Clean sensors)" type="text"/>
            <input class="maint-input maint-days" id="maint-days" placeholder="Every N days" type="number" min="1" max="365"/>
            <select class="maint-input maint-icon" id="maint-icon">
              <option value="\uD83D\uDD27">\uD83D\uDD27 Wrench</option>
              <option value="\uD83E\uDDF9">\uD83E\uDDF9 Brush</option>
              <option value="\uD83D\uDCA7">\uD83D\uDCA7 Water</option>
              <option value="\uD83D\uDD0D">\uD83D\uDD0D Filter</option>
              <option value="\uD83D\uDCCB">\uD83D\uDCCB Task</option>
              <option value="\uD83E\uDEA3">\uD83E\uDEA3 Container</option>
            </select>
            <button class="maint-add-btn">\u2795 Add</button>
          </div>
        </div>

        <div class="section-block">
          <button type="button" class="section-title" aria-expanded="false" aria-controls="vwm-custom-calibration-body" style="cursor:pointer;background:transparent;border:0;color:inherit;text-align:left" onclick="const open=this.nextElementSibling.style.display==='none';this.nextElementSibling.style.display=open?'block':'none';this.setAttribute('aria-expanded',String(open))">
            \u2699\uFE0F Custom calibration values <span style="font-size:10px;color:var(--bento-text-muted);font-weight:400">(click to expand)</span>
          </button>
          <div id="vwm-custom-calibration-body" style="display:none;margin-top:8px">
            ${effectiveCalibration}
            <button type="button" style="padding:8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);cursor:pointer" onclick="this.getRootNode().host._reprofileDevice()">Refresh detected profile</button>
            <div id="vwm-reprofile-status" role="status" aria-live="polite"></div>
            <p>Refresh reads the current Home Assistant registry and releases the profile lock. Authored capacities, calibration, signal assignments and history are preserved.</p>
            <div style="font-size:11px;color:var(--bento-text-secondary);margin-bottom:10px;line-height:1.5">
              If your robot is not on the list or you want to correct values — enter your own data. They are saved per device in Home Assistant Store.
            </div>
            <p>Use measured water loss for this reservoir and mode. A whole-cycle dock measurement includes washes: do not also enter a wash dose for that same water. Capacity and advertised floor coverage are not consumption measurements. The scope applies only to rates you enter here; changing the tank size restarts this robot's learned correction.</p>
            <label>Calibration measurement scope
              <select id="vwm-custom-scope" style="width:100%;max-width:100%;min-width:0;background:var(--bento-bg);color:var(--bento-text);padding:8px;border:1px solid var(--bento-border);border-radius:6px">
                <option value="whole_cycle" ${(customCalibration.calibration_scope || (device && device.calibration_scope)) === 'whole_cycle' ? 'selected' : ''}>Whole cycle (includes dock washes)</option>
                <option value="floor_only" ${(customCalibration.calibration_scope || (device && device.calibration_scope)) !== 'whole_cycle' ? 'selected' : ''}>Floor only (dock washes measured separately)</option>
              </select>
            </label>
            <label>Measured water use (ml/active minute)
              <input type="number" id="vwm-custom-minute-rate" min="0.001" step="any" value="${_esc(String(customCalibration.usage_ml_per_active_minute?.default || ''))}">
            </label>
            <div id="vwm-custom-form" style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                ${_esc(reservoirLabel)} (ml)
                <input type="number" id="vwm-custom-tank" min="1" step="1" value="${_esc(String(customCalibration.tracked_capacity_ml || customCalibration.tank_ml || ''))}" placeholder="e.g. 3000" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Robot tank (ml)
                <input type="number" id="vwm-custom-robot-tank" min="1" step="1" value="${_esc(String(customCalibration.robot_tank_ml || ''))}" placeholder="e.g. 350" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Mop washing (ml/cycle)
                <input type="number" id="vwm-custom-wash" min="1" step="1" value="${_esc(String(customCalibration.wash_volume_ml || customCalibration.mop_wash_ml || ''))}" placeholder="e.g. 150" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Coverage / charge (m\u00B2)
                <input type="number" id="vwm-custom-area" min="1" step="1" value="${_esc(String(customCalibration.avg_area_per_charge || ''))}" placeholder="e.g. 250" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Remaining water at low-water alert (%)
                <input type="number" id="vwm-custom-low-water" min="0" max="50" step="1" value="${_esc(String(customCalibration.low_water_anchor_remaining_percent ?? ''))}" placeholder="10" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>

            </div>
            <div style="margin-top:10px">
              <div style="font-size:11px;color:var(--bento-text-secondary);margin-bottom:6px">Mopping modes — mode name and ml/m\u00B2 usage:</div>
              <div id="vwm-custom-modes" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px">
                ${calibrationModeRows}
              </div>
              <div style="margin-top:6px;text-align:right">
                <button onclick="this.getRootNode().host._addCustomMode()" style="padding:4px 10px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-card);color:var(--bento-text-secondary);font-size:10px;cursor:pointer">+ Add mode</button>
              </div>
            </div>
            <div style="margin-top:12px;display:flex;gap:8px">
              <button id="vwm-custom-save" onclick="this.getRootNode().host._saveCustomCalibration()" style="flex:1;padding:8px 16px;border:none;border-radius:8px;background:#3b82f6;color:white;font-weight:600;font-size:12px;cursor:pointer">\uD83D\uDCBE Save</button>
              <button onclick="this.getRootNode().host._clearCustomCalibration()" style="padding:8px 16px;border:1px solid var(--bento-border);border-radius:8px;background:var(--bento-card);color:var(--bento-text-secondary);font-size:12px;cursor:pointer">\uD83D\uDDD1 Clear</button>
            </div>
            <div id="vwm-custom-status" role="status" aria-live="polite" style="min-height:18px;margin-top:6px;font-size:11px;color:var(--bento-text-secondary)"></div>
          </div>
        </div>
        <div class="section-block" style="text-align:center;padding:16px">
          <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:8px">
            Missing your robot or have more accurate data?
          </div>
          <a href="https://github.com/MacSiem/ha-vacuum-water-monitor/issues/new?title=Calibration+data+for+[MODEL]&body=Model:%0ATank+ml:%0AWater+per+m2:%0AMop+wash+ml:%0ASource:%0A" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:6px;padding:8px 20px;border-radius:8px;background:#24292e;color:white;font-size:12px;font-weight:600;text-decoration:none;cursor:pointer">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            Report data or correction on GitHub
          </a>
          <div style="margin-top:6px;font-size:10px;color:var(--bento-text-muted)">
            Catalog: linked primary sources. Consumption: your measured calibration; unknown until measured.
          </div>
        </div>
      </div>`;
  }

  // ── TAB: HISTORY ───────────────────────────────────────────────────────────

  _buildHistoryTab(device, data) {
    const sessions = this._getSessionsFromStorage(device);

    // Show current session stats if cleaning
    let currentSession = '';
    if (data.isCleaning && data.areaCleaned) {
      currentSession = `<div class="current-session-card">
        <div class="cs-title">\uD83D\uDD04 Current session</div>
        <div class="cs-row"><span>\uD83D\uDDFA\uFE0F Area cleaned</span><span>${data.areaCleaned != null ? parseFloat(data.areaCleaned).toFixed(1) : '--'} m\u00B2</span></div>
        ${data.sessionMl ? `<div class="cs-row"><span>\uD83D\uDCA7 Water used</span><span>${data.sessionMl} ml</span></div>` : ''}
        ${data.durationSec ? `<div class="cs-row"><span>\u23F1\uFE0F Duration</span><span>${this._formatDuration(data.durationSec)}</span></div>` : ''}
      </div>`;
    }

    // Last session from HA sensors
    let lastSessionHtml = '';
    if (data.lastCleanEnd && data.lastCleanEnd !== 'unknown') {
      const endDate = new Date(data.lastCleanEnd);
      const daysAgo = Math.floor((Date.now() - endDate) / 86400000);
      const label = daysAgo === 0 ? 'Today' : daysAgo === 1 ? 'Yesterday' : daysAgo + 'd ago';
      lastSessionHtml = `<div class="session-row">
        <div class="session-date">${label} <span class="session-time">${endDate.getHours()}:${String(endDate.getMinutes()).padStart(2,'0')}</span></div>
        <div class="session-stats">
          ${data.areaCleaned ? `<span class="session-stat">\uD83D\uDDFA\uFE0F ${data.areaCleaned != null ? parseFloat(data.areaCleaned).toFixed(0) : '--'} m\u00B2</span>` : ''}
          ${data.durationSec ? `<span class="session-stat">\u23F1\uFE0F ${this._formatDuration(data.durationSec)}</span>` : ''}
        </div>
      </div>`;
    }

    // Manual sessions from HA Store
    const manualRows = sessions.slice(0, 10).map(s => {
      const d = new Date(s.ts);
      const daysAgo = Math.floor((Date.now() - s.ts) / 86400000);
      const label = daysAgo === 0 ? 'Today' : daysAgo === 1 ? 'Yesterday' : daysAgo + 'd ago';
      return `<div class="session-row">
        <div class="session-date">${label} <span class="session-time">${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}</span></div>
        <div class="session-stats">
          ${s.area ? `<span class="session-stat">\uD83D\uDDFA\uFE0F ${s.area} m\u00B2</span>` : ''}
          ${s.water ? `<span class="session-stat" title="${s.evidence === 'labeled_estimate' ? 'Labelled estimate' : 'Recorded'}">\uD83D\uDCA7 ${s.evidence === 'labeled_estimate' ? '~' : ''}${s.water} ml</span>` : ''}
          ${s.duration ? `<span class="session-stat">\u23F1\uFE0F ${s.duration}</span>` : ''}
        </div>
      </div>`;
    }).join('');

    const noHistory = !lastSessionHtml && !manualRows && !data.isCleaning;
    const rawCycles = this._serverState?.tank_states?.[device?.vacuum_entity]?.automatic_sessions;
    const recordedCycles = Array.isArray(rawCycles) ? rawCycles.filter(s => s && typeof s === 'object' && Number.isFinite(s.ts)) : [];
    const contributionForm = `<div class="section-block contribution-form">
      <div class="section-title">Help improve consumption data</div>
      <p>Select a recorded cycle. Optionally enter the water measured to refill the same reservoir to its starting level and your measurement resolution. Review the draft before downloading; nothing is uploaded.</p>
      <label>Recorded cycle <select id="cal-cycle" class="maint-input" ${recordedCycles.length ? '' : 'disabled'}>
        ${recordedCycles.slice(0, 50).map((s, i) => `<option value="${rawCycles.indexOf(s)}" data-cycle-ts="${Number(s.ts)}">Cycle ${i + 1} — ${_esc(new Date(s.ts).toLocaleString())}</option>`).join('')}
      </select></label>
      <label>Measured refill (ml) <input id="cal-observed" class="maint-input" type="number" min="0" step="any" /></label>
      <label>Measurement resolution (ml) <input id="cal-resolution" class="maint-input" type="number" min="0" step="any" /></label>
      <div class="section-title">Private measured calibration</div>
      <p id="cal-readiness">${_esc(this._measurementReadiness(recordedCycles[0]))}</p>
      <p>Save a full-to-full refill for this device. Three distinct complete cycles with the same historical settings fit a whole-cycle dose per m². Independent validation cycles never change that fit. Partial cycles, missing context and changed settings cannot be used.</p>
      <label>Instrument <select id="cal-instrument" class="maint-input"><option value="graduated_jug">Graduated jug</option><option value="scale_water">Scale (water, converted to ml)</option><option value="flow_meter">Flow meter</option></select></label>
      <label>Sample purpose <select id="cal-purpose" class="maint-input"><option value="training">Training</option><option value="validation">Independent validation</option></select></label>
      <label><span><input type="checkbox" id="cal-boundaries" /> Same full reservoir level before and after; no intermediate refill or unmeasured transfer</span></label>
      <label><span><input type="checkbox" id="cal-uninterrupted" /> Complete cycle observed from zero area, with unchanged settings and no interruption</span></label>
      <button type="button" id="cal-save" class="maint-add-btn" ${recordedCycles.length ? '' : 'disabled'}>Save private measurement</button>
      <div id="cal-local-status" role="status" aria-live="polite"></div>
      <p>The draft excludes identifiers and dates. Historical settings still need verification; estimates and elapsed time are not physical measurements or active mopping time.</p>
      <button type="button" id="cal-preview" class="maint-add-btn" ${recordedCycles.length ? '' : 'disabled'}>Preview contribution draft</button>
      <div id="cal-export-status" role="status" aria-live="polite"></div>
      <textarea id="cal-export-preview" aria-label="Contribution draft preview" readonly hidden style="width:100%;box-sizing:border-box;min-height:220px"></textarea>
      <button type="button" id="cal-download" class="maint-add-btn" disabled>Download reviewed draft</button>
    </div>`;

    return `
      <div class="tab-content">
        ${currentSession}
        ${lastSessionHtml ? `<div class="section-block"><div class="section-title">\uD83D\uDDD3\uFE0F Last Session (HA)</div>${lastSessionHtml}</div>` : ''}
        ${manualRows ? `<div class="section-block"><div class="section-title">\uD83D\uDCCA Logged Sessions</div>${manualRows}</div>` : ''}
        ${noHistory ? '<div class="empty-state">No session history available.<br>Start a cleaning to record sessions.</div>' : ''}
        ${contributionForm}
        <div class="section-block">
          <div class="section-title">\u270F\uFE0F Log Manual Session</div>
          <div class="add-maint-form">
            <input class="maint-input" id="hist-area" placeholder="Area m\u00B2" type="number" min="0"/>
            <input class="maint-input maint-days" id="hist-water" placeholder="Water ml" type="number" min="0"/>
            <input class="maint-input maint-days" id="hist-duration" placeholder="Duration (e.g. 45m)" type="text"/>
            <button class="maint-add-btn" id="hist-log-btn">\u2795 Log</button>
          </div>
        </div>
      </div>`;
  }

  _getSessionsFromStorage(device) {
    const key = (device && (device.vacuum_entity || device.name)) || 'default';
    const sessions = ((this._serverState.settings || {}).sessions || {})[key];
    const rawAutomatic = this._serverState?.tank_states?.[device?.vacuum_entity]?.automatic_sessions;
    const automatic = Array.isArray(rawAutomatic) ? rawAutomatic : [];
    return [...(Array.isArray(sessions) ? sessions : []), ...automatic]
      .filter(s => s && typeof s === 'object' && Number.isFinite(s.ts)).sort((a,b) => b.ts-a.ts);
  }

  _measurementReadiness(session) {
    if (!session || typeof session !== 'object') return 'No recorded cycle available.';
    const missing = [];
    const ctx = session.context;
    if (!ctx || typeof ctx !== 'object') missing.push('historical context');
    else {
      for (const key of ['model_id','sku','dock_variant','firmware','integration_id','integration_version','reservoir','action']) {
        if (!ctx[key] || ['unknown','unavailable'].includes(ctx[key])) missing.push(key);
      }
      for (const key of ['mop_mode','water_level','route','passes','wash_mode','wash_frequency','wash_temperature','adaptive_mode','detergent_mode','cleaning_mode','task_scope','suction_level','carpet_policy']) {
        if (!ctx.settings?.[key] || ['unknown','unavailable'].includes(ctx.settings[key])) missing.push(key);
      }
    }
    if (!session.exposure_complete || session.segments !== 1) missing.push('complete single-context cycle');
    if (!(Number.isFinite(session.area) && session.area > 0)) missing.push('measured area');
    return missing.length ? `Not ready for fitting: ${missing.join(', ')}. Current settings cannot fill historical gaps.`
      : 'Historical context and complete area are recorded. Confirm the physical measurement boundaries below.';
  }

  async _saveLocalMeasurement(device) {
    const sr = this.shadowRoot;
    const status = sr.getElementById('cal-local-status');
    const button = sr.getElementById('cal-save');
    const rawVolume = sr.getElementById('cal-observed')?.value;
    const rawResolution = sr.getElementById('cal-resolution')?.value;
    const volume = Number(rawVolume), resolution = Number(rawResolution);
    if (!rawVolume || !rawResolution || !Number.isFinite(volume) || !Number.isFinite(resolution) ||
        volume <= 0 || resolution <= 0 || resolution >= volume ||
        !sr.getElementById('cal-boundaries')?.checked || !sr.getElementById('cal-uninterrupted')?.checked) {
      if (status) status.textContent = 'Enter measured ml and resolution, then confirm both measurement boundaries.';
      return false;
    }
    if (button?.disabled) return false;
    if (button) button.disabled = true;
    const generation = this._localMeasurementGeneration || 0;
    const request = {type:'ha_vacuum_water_monitor/save_measurement', vacuum_entity:device.vacuum_entity,
      session_index:Number(sr.getElementById('cal-cycle')?.value),
      session_ts:Number(sr.getElementById('cal-cycle')?.selectedOptions[0]?.dataset.cycleTs),
      measurement:{observed_ml:volume,resolution_ml:resolution,
        instrument:sr.getElementById('cal-instrument')?.value,
        purpose:sr.getElementById('cal-purpose')?.value,boundaries_confirmed:true,uninterrupted:true}};
    try {
      const result = await this._hass.callWS(request);
      if (result?.saved !== true || !Number.isInteger(result.sample_count) || result.sample_count < 1) throw new Error('Invalid measurement acknowledgement');
      if (sr.getElementById('cal-local-status') !== status || generation !== (this._localMeasurementGeneration || 0)) return true;
      if (status) status.textContent = result.calibration
        ? `Saved privately. ${result.sample_count} sample(s); device calibration available within its measured area range. Independent accuracy remains separate.`
        : `Saved privately. ${result.sample_count} sample(s) for these settings; at least three distinct training cycles are needed.`;
      return true;
    } catch (_) {
      if (sr.getElementById('cal-local-status') === status && status) status.textContent = 'Could not save. Check complete historical context, measurement boundaries, duplicate cycle and connection.';
      return false;
    } finally {
      if (sr.getElementById('cal-save') === button && button) button.disabled = false;
    }
  }

  async _previewCalibration(device) {
    const sr = this.shadowRoot;
    const status = sr.getElementById('cal-export-status');
    const preview = sr.getElementById('cal-export-preview');
    const download = sr.getElementById('cal-download');
    const observed = sr.getElementById('cal-observed')?.value || '';
    const resolution = sr.getElementById('cal-resolution')?.value || '';
    const request = { type: 'ha_vacuum_water_monitor/calibration_preview',
      vacuum_entity: device.vacuum_entity,
      session_index: Number(sr.getElementById('cal-cycle')?.value || 0),
      session_ts: Number(sr.getElementById('cal-cycle')?.selectedOptions[0]?.dataset.cycleTs) };
    if (observed !== '' || resolution !== '') {
      if (observed === '' || resolution === '' || !Number.isFinite(Number(observed)) ||
          !Number.isFinite(Number(resolution)) || Number(observed) < 0 || Number(resolution) <= 0) {
        if (status) status.textContent = 'Enter both measured refill and a positive resolution in ml.';
        if (download) download.disabled = true;
        return false;
      }
      request.observed_ml = Number(observed);
      request.resolution_ml = Number(resolution);
    }
    if (download) download.disabled = true;
    if (preview) { preview.value = ''; preview.hidden = true; }
    const generation = this._calibrationPreviewGeneration = (this._calibrationPreviewGeneration || 0) + 1;
    if (status) status.textContent = 'Preparing preview…';
    try {
      const draft = await this._hass.callWS(request);
      if (generation !== this._calibrationPreviewGeneration || sr.getElementById('cal-export-preview') !== preview) return false;
      const content = JSON.stringify(draft, null, 2);
      if (preview) { preview.value = content; preview.hidden = false; }
      if (status) status.textContent = 'Review every field. Missing context must be completed before submission. Nothing has been uploaded.';
      if (download) {
        download.disabled = false;
        download.onclick = () => {
          const url = URL.createObjectURL(new Blob([content + '\n'], {type: 'application/json'}));
          const link = document.createElement('a');
          link.href = url; link.download = 'vacuum-consumption-draft.json'; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        };
      }
      return true;
    } catch (_) {
      if (generation === this._calibrationPreviewGeneration && status) status.textContent = 'Could not prepare the draft. Check the connection and recorded cycle, then retry.';
      return false;
    }
  }

  _saveSession(device, session) {
    const key = (device && (device.vacuum_entity || device.name)) || 'default';
    const all = { ...(((this._serverState.settings || {}).sessions) || {}) };
    const sessions = this._getSessionsFromStorage(device).filter(item => item.type !== 'automatic');
    sessions.unshift({ ...session, ts: Date.now() });
    all[key] = sessions.slice(0, 50);
    this._serverState.settings = { ...(this._serverState.settings || {}), sessions: all };
    this._saveServerSettings({ sessions: all });
  }

  // ── TAB: STATS ─────────────────────────────────────────────────────────────

  _buildStatsTab(devices) {
    // Summary across all devices
    const rows = devices.map(device => {
      const data = this._calcDeviceData(device);
      const status = this._getStatus(data, this._config);
      const pct = data.percentRemaining !== null ? Math.round(data.percentRemaining) : null;
      return `<div class="stats-row">
        <span class="stats-device">${_esc(this._sanitize(device.icon || '\uD83E\uDDA4'))} ${_esc(this._sanitize(device.name || 'Vacuum'))}</span>
        <span class="stats-status" style="color:${status.color}">${status.icon} ${status.label}</span>
        <span class="stats-pct" style="color:${status.color}">${pct !== null ? pct + '%' : '--'}</span>
      </div>`;
    }).join('');

    return `
      <div class="tab-content">
        ${devices.length > 1 ? `<div class="section-block"><div class="section-title">\uD83D\uDCCA All Devices</div>${rows}</div>` : ''}
        ${devices.length > 0 ? this._buildWeeklyStats(devices) : ''}
        ${devices.length === 0 ? `<div class="empty-state">${this._t.noDevices}<br>${this._t.addVacuum}</div>` : ''}
      </div>`;
  }

  _buildWeeklyStats(devices) {
    // Weekly summary from local storage sessions
    const allSessions = [];
    devices.forEach(d => {
      const sessions = this._getSessionsFromStorage(d);
      sessions.forEach(s => allSessions.push({ ...s, device: d.name }));
    });

    const weekAgo = Date.now() - 7 * 86400000;
    const thisWeek = allSessions.filter(s => s.ts > weekAgo);
    const totalArea = thisWeek.reduce((sum, s) => sum + (parseFloat(s.area) || 0), 0);
    const knownWater = thisWeek.filter(s => typeof s.water === 'number' && Number.isFinite(s.water));
    const totalWater = knownWater.reduce((sum, s) => sum + s.water, 0);
    const totalSessions = thisWeek.length;

    return `<div class="section-block">
      <div class="section-title">\uD83D\uDCC5 This Week (logged)</div>
      <div class="stats-grid">
        <div class="stat-box"><div class="stat-num">${totalSessions}</div><div class="stat-label">sessions</div></div>
        <div class="stat-box"><div class="stat-num">${(totalArea || 0).toFixed(0)}</div><div class="stat-label">m\u00B2 cleaned</div></div>
        <div class="stat-box"><div class="stat-num">${knownWater.length ? (totalWater / 1000).toFixed(1) : '—'}</div><div class="stat-label">L water (${knownWater.length}/${thisWeek.length} known)</div></div>
      </div>
    </div>`;
  }


  // ── TAB: DATABASE ─────────────────────────────────────────────────────────


  async _reprofileDevice() {
    const device = this._getDevices()[this._activeDeviceIdx] || {};
    const status = this.shadowRoot?.getElementById('vwm-reprofile-status');
    if (!device.vacuum_entity || !this._hass?.callWS) return false;
    try {
      const result = await this._hass.callWS({type: `${VWM_DOMAIN}/reprofile`, vacuum_entity: device.vacuum_entity});
      this._serverState = {...this._serverState, settings: result.settings};
      this._discoveredVacuums = result.vacuums || [];
      this._render();
      const current = this.shadowRoot?.getElementById('vwm-reprofile-status');
      if (current) current.textContent = 'Profile refreshed. Your calibration and history are preserved.';
      return true;
    } catch (error) {
      if (status) status.textContent = 'Could not refresh the profile. Please try again.';
      return false;
    }
  }

  async _saveCustomCalibration() {
    const shadow = this.shadowRoot;
    const status = shadow.getElementById('vwm-custom-status');
    const saveButton = shadow.getElementById('vwm-custom-save');
    const tank = shadow.getElementById('vwm-custom-tank')?.value;
    const robotTank = shadow.getElementById('vwm-custom-robot-tank')?.value;
    const wash = shadow.getElementById('vwm-custom-wash')?.value;
    const area = shadow.getElementById('vwm-custom-area')?.value;
    const lowWaterRemaining = shadow.getElementById('vwm-custom-low-water')?.value;
    const estimatedSpeed = shadow.getElementById('vwm-custom-speed')?.value;
    const minuteRate = shadow.getElementById('vwm-custom-minute-rate')?.value;
    const modeNames = shadow.querySelectorAll('.vwm-mode-name');
    const modeVals = shadow.querySelectorAll('.vwm-mode-val');
    const modes = {};
    const custom = {};
    const measurementScope = shadow.getElementById('vwm-custom-scope')?.value || 'whole_cycle';
    const addPositiveInteger = (raw, key, label) => {
      if (raw === '' || raw == null) return;
      const value = Number(raw);
      if (!Number.isFinite(value) || value <= 0) throw new Error(`${label} must be greater than zero`);
      custom[key] = Math.round(value);
    };
    try {
      if (minuteRate !== '' && minuteRate != null) {
        const rate = Number(minuteRate);
        if (!Number.isFinite(rate) || rate <= 0) throw new Error('Measured ml/min must be positive');
        custom.usage_ml_per_active_minute = {default: rate};
      }
      addPositiveInteger(tank, 'tracked_capacity_ml', 'Tracked reservoir');
      addPositiveInteger(robotTank, 'robot_tank_ml', 'Robot tank');
      addPositiveInteger(wash, 'wash_volume_ml', 'Mop wash');
      addPositiveInteger(area, 'avg_area_per_charge', 'Coverage');
      if (lowWaterRemaining !== '' && lowWaterRemaining != null) {
        const value = Number(lowWaterRemaining);
        if (!Number.isFinite(value) || value < 0 || value > 50) {
          throw new Error('Low-water remaining percentage must be between 0 and 50');
        }
        custom.low_water_anchor_remaining_percent = Math.round(value);
      }
      if (estimatedSpeed !== '' && estimatedSpeed != null) {
        const value = Number(estimatedSpeed);
        if (!Number.isFinite(value) || value <= 0 || value > 5) {
          throw new Error('Estimated cleaning speed must be greater than zero and at most 5 m\u00B2/min');
        }
        custom.estimated_m2_per_active_minute = value;
      }
      modeNames.forEach((nameInput, i) => {
        const name = nameInput.value?.trim();
        const raw = modeVals[i]?.value?.trim();
        if (!name && !raw) return;
        const value = Number(raw);
        if (!name || !Number.isFinite(value) || value <= 0) {
          throw new Error('Each mopping mode needs a name and a value greater than zero');
        }
        modes[name] = value;
      });
    } catch (err) {
      if (status) { status.textContent = `Could not save: ${err.message}`; status.style.color = '#ef4444'; }
      return false;
    }
    if (Object.keys(modes).length > 0) {
      custom.usage_ml_per_m2 = modes;
    }
    if (Object.keys(custom).length === 0) {
      if (status) { status.textContent = 'Enter at least one calibration value.'; status.style.color = '#ef4444'; }
      return false;
    }
    const activeDevice = this._getDevices()[this._activeDeviceIdx] || null;
    // The scope describes a measured rate; a capacity or wash dose alone must not change it.
    if (custom.usage_ml_per_m2 || custom.usage_ml_per_active_minute) custom.calibration_scope = measurementScope;
    // The capacity field is labelled with the tracked reservoir; keep that pairing.
    if (custom.tracked_capacity_ml && activeDevice && activeDevice.tracked_reservoir) custom.tracked_reservoir = activeDevice.tracked_reservoir;
    const key = this._customCalibrationKey(activeDevice);
    const all = { ...(((this._serverState.settings || {}).custom_calibration) || {}) };
    const existing = this._normaliseCalibrationLayer(all[key]);
    // Preserve fields the current form does not edit (and every other device)
    // while applying this device's calibration changes.
    all[key] = {
      ...existing,
      ...custom,
      ...(custom.usage_ml_per_m2 ? {
        usage_ml_per_m2: { ...(existing.usage_ml_per_m2 || {}), ...custom.usage_ml_per_m2 },
      } : {}),
    };
    if (saveButton) { saveButton.disabled = true; saveButton.textContent = 'Saving…'; }
    if (status) { status.textContent = 'Saving to Home Assistant…'; status.style.color = 'var(--bento-text-secondary)'; }
    const result = await this._saveServerSettings({ custom_calibration: all });
    const currentSaveButton = shadow.getElementById('vwm-custom-save');
    const currentStatus = shadow.getElementById('vwm-custom-status');
    if (currentSaveButton) { currentSaveButton.disabled = false; currentSaveButton.textContent = '\uD83D\uDCBE Save'; }
    if (!result.ok) {
      if (currentStatus) { currentStatus.textContent = 'Could not save calibration. Please try again.'; currentStatus.style.color = '#ef4444'; }
      return false;
    }
    this._customCalib = custom;
    if (currentStatus) { currentStatus.textContent = '\u2705 Saved in Home Assistant for this device.'; currentStatus.style.color = '#22c55e'; }
    return true;
  }

  async _clearCustomCalibration() {
    const status = this.shadowRoot.getElementById('vwm-custom-status');
    const activeDevice = this._getDevices()[this._activeDeviceIdx] || null;
    const key = this._customCalibrationKey(activeDevice);
    const all = { ...(((this._serverState.settings || {}).custom_calibration) || {}) };
    delete all[key];
    const result = await this._saveServerSettings({ custom_calibration: all });
    const currentStatus = this.shadowRoot.getElementById('vwm-custom-status') || status;
    if (!result.ok) {
      if (currentStatus) { currentStatus.textContent = 'Could not clear calibration. Please try again.'; currentStatus.style.color = '#ef4444'; }
      return false;
    }
    this._customCalib = null;
    this._lastHtml = '';
    this._render({ preserveDraft: false });
    const refreshedBody = this.shadowRoot.getElementById('vwm-custom-calibration-body');
    const refreshedStatus = this.shadowRoot.getElementById('vwm-custom-status');
    if (refreshedBody) refreshedBody.style.display = 'block';
    if (refreshedStatus) { refreshedStatus.textContent = '\u2705 Custom calibration cleared.'; refreshedStatus.style.color = '#22c55e'; }
    return true;
  }

  _loadCustomCalibration() {
    this._applyServerSettings();
  }

  _addCustomMode() {
    const container = this.shadowRoot.getElementById('vwm-custom-modes');
    if (!container) return;
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:4px;align-items:center';
    div.innerHTML = '<input type="text" placeholder="tryb" style="flex:1;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name" aria-label="Mopping mode name"><input type="number" placeholder="ml/m\u00B2" style="width:60px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val" aria-label="Measured ml per square metre"><span onclick="this.parentElement.remove()" style="cursor:pointer;color:var(--bento-text-muted);font-size:14px">\u00D7</span>';
    container.appendChild(div);
  }
  _buildDatabaseTab() {
    const models = Object.entries(CALIBRATION_DATA);
    const activeDevice = this._getDevices()[this._activeDeviceIdx] || null;
    const configuredProfile = this._normaliseModelKey(this._config.brand_profile);
    const configuredCanonical = MODEL_ALIASES[configuredProfile] || configuredProfile;
    const activeProfileKey = this._resolveProfileKey(activeDevice)
      || (CALIBRATION_DATA[configuredCanonical] ? configuredCanonical : null);
    const cellSt = 'padding:6px 8px;font-size:11px;border-bottom:1px solid var(--vwm-border,#e5e7eb);vertical-align:top';
    const headSt = cellSt + ';font-weight:700;color:var(--vwm-text-secondary,#6b7280);background:var(--vwm-surface,#f3f4f6);position:sticky;top:0;z-index:1';
    const numSt = 'text-align:center;font-weight:600';
    const tagSt = 'display:inline-block;padding:2px 7px;border-radius:6px;font-size:10px;font-weight:600;margin:1px 2px';

    const levelColor = (val) => {
      if (val <= 6) return 'background:rgba(34,197,94,0.15);color:#16a34a';
      if (val <= 12) return 'background:rgba(59,130,246,0.12);color:#3b82f6';
      if (val <= 18) return 'background:rgba(245,158,11,0.12);color:#d97706';
      return 'background:rgba(239,68,68,0.12);color:#ef4444';
    };

    const rows = models.map(([key, m]) => {
      const levels = Object.entries(m.water_per_m2 || {});
      const publishedFacts = _calibrationFacts(m);
      const levelTags = levels.map(([mode, val]) => {
        const estArea = m.tank_ml ? Math.round(m.tank_ml / val) : '?';
        return `<span style="${tagSt};${levelColor(val)}" title="${mode}: ${val} ml/m\u00B2 \u2192 ~${estArea} m\u00B2/tank">${mode}: ${val}</span>`;
      }).join(' ');

      // Area estimates per mode
      const areaEstimates = levels.map(([mode, val]) => {
        if (!m.tank_ml) return '';
        const area = Math.round(m.tank_ml / val);
        return `<span style="${tagSt};background:var(--vwm-overlay-light,rgba(0,0,0,0.04));color:var(--vwm-text-secondary,#6b7280)">${mode}: ~${area} m\u00B2</span>`;
      }).join(' ');

      const isActive = activeProfileKey === key;
      const rowBg = isActive ? 'background:rgba(59,130,246,0.06)' : '';

      return `<tr style="${rowBg}">
        <td style="${cellSt}">
          <div style="font-weight:600;font-size:12px">${m.label}${isActive ? ' <span style="color:#3b82f6;font-size:10px">\u2705 active</span>' : ''}</div>
          <div style="font-size:10px;color:var(--vwm-text-muted,#9ca3af);margin-top:2px">${_esc(m.mop_type || (m.mop_system && m.mop_system !== 'unknown' ? String(m.mop_system).replace(/_/g, ' ') : 'mop system unknown'))}</div>
        </td>
        <td style="${cellSt};${numSt}">${m.tank_ml ? `${Number(m.tank_ml).toLocaleString('en-US')} ml` : 'unknown'}</td>
        <td style="${cellSt}">${levelTags ? `${levelTags}${m.estimate_basis ? `<div style="font-size:10px;color:var(--vwm-text-muted,#9ca3af);margin-top:2px">${_esc(VWM_BASIS_LABEL[m.estimate_basis] || '')}${m.uncertainty_percent ? ` \u00B7 \u00B1${m.uncertainty_percent}%` : ''}</div>` : ''}` : '<span style="color:var(--vwm-text-muted,#9ca3af)">no estimate</span>'}</td>
        <td style="${cellSt}">${areaEstimates || '—'}</td>
        <td style="${cellSt};${numSt}">${m.avg_area_per_charge ? m.avg_area_per_charge + ' m\u00B2' : '—'}</td>
        <td style="${cellSt};font-size:10px;color:var(--vwm-text-secondary,#6b7280);max-width:220px">
          ${publishedFacts.length ? `<div style="display:flex;flex-wrap:wrap;gap:2px;margin-bottom:4px">${publishedFacts.map(fact => `<span style="${tagSt};background:rgba(59,130,246,0.08);color:var(--vwm-text-secondary,#6b7280)">${_esc(fact)}</span>`).join('')}</div>` : ''}
          ${m.notes || ''}${m.mop_wash_ml ? ' | Estimated wash: ' + m.mop_wash_ml + 'ml/cycle' : ''}
        </td>
      </tr>`;
    }).join('');

    // Summary card for active profile
    let activeCard = '';
    const active = activeProfileKey ? CALIBRATION_DATA[activeProfileKey] : null;
    if (active) {
      const levels = Object.entries(active.water_per_m2 || {});
      const publishedFacts = _calibrationFacts(active);
      const sourceLinks = (active.source_urls || []).map((url, index) => `<a href="${_esc(url)}" target="_blank" rel="noopener noreferrer" style="color:#3b82f6">manufacturer source${active.source_urls.length > 1 ? ' ' + (index + 1) : ''}</a>`).join(' · ');
      activeCard = `
        <div style="margin-bottom:14px;padding:14px;background:rgba(59,130,246,0.06);border:1.5px solid rgba(59,130,246,0.2);border-radius:12px">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px">\uD83E\uDDA4 ${active.label} <span style="font-size:11px;color:#3b82f6;font-weight:500">(active profile)</span></div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:10px">
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${active.tank_ml ? Number(active.tank_ml).toLocaleString('en-US') : '\u2014'}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">${active.tank_ml ? 'ml clean-water capacity' : 'clean-water capacity unknown'}</div>
            </div>
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${active.tested_max_area_per_fill_m2 || active.avg_area_per_charge || '—'}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">${active.tested_max_area_per_fill_m2 ? 'm\u00B2 / fill (tested max)' : 'm\u00B2 / charge'}</div>
            </div>
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${levels.length}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">estimated mop modes</div>
            </div>
          </div>
          ${publishedFacts.length ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${publishedFacts.map(fact => `<span style="${tagSt};background:rgba(59,130,246,0.08);color:var(--vwm-text-secondary,#6b7280)">${_esc(fact)}</span>`).join('')}</div>` : ''}
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">Estimated water usage by mode${active.uncertainty_percent ? ` (\u00B1${active.uncertainty_percent}%, ${_esc(VWM_BASIS_LABEL[active.estimate_basis] || 'labelled estimate')})` : ''}:</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px">
            ${levels.length ? levels.map(([mode, val]) => {
              const area = active.tank_ml ? Math.round(active.tank_ml / val) : null;
              const pct = Math.round((val / Math.max(...levels.map(l => l[1]))) * 100);
              return `<div style="padding:8px;background:var(--vwm-bg,#fff);border-radius:8px;border:1px solid var(--vwm-border,#e5e7eb)">
                <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:var(--bento-text-secondary);margin-bottom:4px">${mode}</div>
                <div style="font-size:16px;font-weight:700;color:var(--bento-text)">${val} <span style="font-size:10px;font-weight:400">ml/m\u00B2</span></div>
                <div style="margin:4px 0;height:4px;background:rgba(59,130,246,0.12);border-radius:2px;overflow:hidden"><div style="height:100%;width:${pct}%;border-radius:2px;background:${val <= 8 ? '#22c55e' : val <= 14 ? '#3b82f6' : val <= 18 ? '#f59e0b' : '#ef4444'}"></div></div>
                <div style="font-size:10px;color:var(--bento-text-muted)">${area ? `\u2248 ${area} m\u00B2 / tank (floor only)` : 'capacity unknown'}</div>
              </div>`;
            }).join('') : '<div style="font-size:11px;color:var(--bento-text-secondary)">No estimate for this model yet.</div>'}
          </div>
          ${active.mop_type ? `<div style="margin-top:8px;font-size:11px;color:var(--bento-text-secondary)">\uD83E\uDDF9 ${active.mop_type}</div>` : ''}
          ${active.notes ? `<div style="margin-top:4px;font-size:11px;color:var(--bento-text-muted);font-style:italic">\uD83D\uDCA1 ${active.notes}</div>` : ''}
          ${active.mop_wash_ml ? `<div style="margin-top:4px;font-size:11px;color:var(--bento-text-secondary)">\uD83D\uDEBF Mop wash in dock: ${active.mop_wash_ml}ml/cycle${active.mop_wash_modes ? ' (' + Object.entries(active.mop_wash_modes).map(([k,v]) => k + ': ' + v + 'ml').join(', ') + ')' : ''}</div>` : ''}
          ${sourceLinks ? `<div style="margin-top:6px;font-size:10px">Sources: ${sourceLinks} · ${_esc(active.data_quality || 'manufacturer data')}</div>` : ''}
        </div>`;
    }

    return `
      <div class="tab-content">
        ${activeCard}
        <div class="section-block">
          <div class="section-title">\uD83D\uDCDA Robot configuration database</div>
          <div style="overflow-x:auto;margin-top:8px;border:1px solid var(--vwm-border,#e5e7eb);border-radius:10px">
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>
                <tr>
                  <th style="${headSt};text-align:left;min-width:140px">Model</th>
                  <th style="${headSt};${numSt};min-width:60px">Tank</th>
                  <th style="${headSt};text-align:left;min-width:160px">Water usage (ml/m\u00B2)</th>
                  <th style="${headSt};text-align:left;min-width:160px">Coverage / tank</th>
                  <th style="${headSt};${numSt};min-width:70px">Coverage / charge</th>
                  <th style="${headSt};text-align:left;min-width:120px">Notes</th>
                </tr>
              </thead>
              <tbody>
                ${rows}
              </tbody>
            </table>
          </div>
        </div>

        <div class="section-block">
          <div class="section-title">\u2139\uFE0F Mode Legend</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:6px;margin-top:8px;font-size:11px">
            <div style="display:flex;align-items:center;gap:6px"><span style="${tagSt};${levelColor(5)}">low</span> Gentle \u2014 wood, panels</div>
            <div style="display:flex;align-items:center;gap:6px"><span style="${tagSt};${levelColor(10)}">medium</span> Standard \u2014 tiles</div>
            <div style="display:flex;align-items:center;gap:6px"><span style="${tagSt};${levelColor(16)}">high</span> Intensive \u2014 porcelain</div>
            <div style="display:flex;align-items:center;gap:6px"><span style="${tagSt};${levelColor(22)}">max/deep</span> Deep cleaning</div>
          </div>
          <div style="margin-top:10px;font-size:11px;color:var(--bento-text-secondary);line-height:1.5">
            <strong>Tank</strong> — tracked clean-water capacity: dock tank for auto-refill models, otherwise the robot's built-in tank. Published robot and dirty-water capacities are shown separately in the model facts.<br>
            <strong>Coverage / tank</strong> — estimated area the robot cleans on one full tank in given mode.<br>
            <strong>Coverage / charge</strong> — max area on one battery charge (regardless of water).
          </div>
        </div>
      </div>`;
  }

  _estimateUncertainty(basis, logFactors) {
    return _vwmUncertainty(basis, logFactors);
  }

  _storedCalibrationWindow(tankState) {
    return _vwmStoredWindow(tankState);
  }

  _calibrationSharingEnabled() {
    const sharing = this._serverState?.settings?.calibration_sharing;
    return Boolean(sharing && sharing.enabled === true);
  }

  // Builds the only data that can ever leave Home Assistant through this card.
  // It is shown in full before sharing and contains no entity ids, names,
  // device/account identifiers, timestamps, areas, rooms, maps or firmware.
  _buildCalibrationSharePayload(device, data) {
    const round = (value, step) => (Number.isFinite(Number(value)) ? Math.round(Number(value) / step) * step : null);
    const tanks = (data?.calibrationHistory || []).slice(0, 12).map(t => ({
      predicted_ml: round(t.predicted_ml, 10),
      target_ml: round(t.target_ml, 10),
      error_percent: round(t.error_percent, 0.1) === null ? null : Number(round(t.error_percent, 0.1).toFixed(1)),
      accepted: t.accepted === true,
    }));
    return {
      schema: VWM_SHARE_SCHEMA,
      integration_version: VWM_VERSION,
      profile_key: data?.profileKey || null,
      mop_system: data?.mopSystem || null,
      integration_adapter: data?.integrationAdapter || null,
      estimate_basis: data?.estimateBasis || null,
      tracked_reservoir: data?.trackedReservoir || null,
      tracked_capacity_ml: round(data?.totalMl, 10),
      calibration_factor: Number.isFinite(Number(data?.calibrationFactor)) ? Number(Number(data.calibrationFactor).toFixed(3)) : null,
      calibrated_tanks: Number(data?.calibrationSamples) || 0,
      tanks,
    };
  }

  _buildCalibrationSharingSection(device, data) {
    if (!device || !data) return '';
    const enabled = this._calibrationSharingEnabled();
    const payload = this._buildCalibrationSharePayload(device, data);
    const ready = enabled && payload.calibrated_tanks > 0 && payload.profile_key;
    const json = JSON.stringify(payload, null, 2);
    return `
        <div style="background:var(--vwm-overlay-light,rgba(0,0,0,0.03));border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:14px;padding:16px;margin-bottom:16px">
          <div style="font-size:14px;font-weight:700;color:var(--bento-text);margin-bottom:4px">\uD83E\uDD1D Help improve estimates (optional, beta)</div>
          <div style="font-size:12px;color:var(--bento-text-secondary);line-height:1.5;margin-bottom:10px">
            Share this robot model's calibration summary so estimates for everyone with the same model start closer to reality.
            Nothing is sent automatically: you review the exact data below and submit it yourself.
            It contains only the model, mop system, integration, tank capacity and per-tank calibration results.
            It never contains entity or device names, identifiers, account data, timestamps, rooms, maps, areas or firmware.
            Submitting opens a GitHub issue, so your GitHub username is visible on it.
          </div>
          <label style="display:flex;gap:8px;align-items:center;font-size:12px;color:var(--bento-text)">
            <input type="checkbox" id="vwm-share-optin" ${enabled ? 'checked' : ''}> I want to share anonymous calibration summaries
          </label>
          ${enabled ? `
          <pre id="vwm-share-payload" style="margin:10px 0;padding:10px;max-height:220px;overflow:auto;background:var(--bento-card,#fff);color:var(--bento-text,#1e293b);border:1px solid var(--vwm-border,#e5e7eb);border-radius:8px;font-size:11px;white-space:pre-wrap">${_esc(json)}</pre>
          ${ready ? `<div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn-primary" id="vwm-share-copy" style="padding:6px 12px">Copy summary</button>
            <a class="btn-primary" id="vwm-share-submit" target="_blank" rel="noopener noreferrer" href="${_esc(this._calibrationShareUrl(payload))}" style="padding:6px 12px;text-decoration:none">Submit on GitHub</a>
          </div>` : '<div style="font-size:11px;color:var(--bento-text-secondary)">Nothing to share yet: the summary becomes available after the first calibrated empty tank.</div>'}` : ''}
        </div>`;
  }

  _calibrationShareUrl(payload) {
    const summary = JSON.stringify(payload);
    // GitHub reads issue forms only from the default branch. Until the form is
    // there, the same summary lands in a plain issue body with consent unticked.
    const params = new URLSearchParams({
      template: 'calibration_share.yml',
      title: `[calibration] ${payload.profile_key || 'unknown model'}`,
      summary,
      body: `Calibration summary (JSON):\n\n\`\`\`json\n${summary}\n\`\`\`\n\n- [ ] I reviewed the summary and agree to publish it under CC BY 4.0 in the vacuum consumption dataset.\n`,
    });
    return `${VWM_SHARE_ISSUE_URL}?${params.toString()}`;
  }

  async _setCalibrationSharing(enabled) {
    const patch = { calibration_sharing: { enabled: Boolean(enabled), schema: VWM_SHARE_SCHEMA, changed_at: new Date().toISOString() } };
    const result = await this._saveServerSettings(patch);
    this._lastHtml = '';
    this._render();
    return result;
  }

  _buildSettingsTab(device, data) {
    const devices = this._getDevices();

    // --- Device discovery section ---
    const discovered = this._autoDiscoverVacuums();
    const configuredIds = devices.map(d => d.vacuum_entity).filter(Boolean);
    const undiscovered = discovered.filter(v => !configuredIds.includes(v.entity_id));

    const fullTankTip = (undiscovered.length > 0 || devices.length === 0) ? `<div style="margin:10px 0;padding:10px 14px;background:rgba(59,130,246,0.1);border:1.5px solid rgba(59,130,246,0.25);border-radius:10px;font-size:12px;line-height:1.5;color:var(--vwm-text,#1e293b)">\uD83D\uDCA1 <strong>Tip:</strong> Add vacuum when its tank is <strong>full</strong> — this way water level tracking will be accurate from the start.</div>` : '';

    const discoveredHtml = undiscovered.length > 0 ? `
      <div class="section-block">
        <div class="section-title">\uD83D\uDD0E Discovered vacuums (not configured)</div>
        ${undiscovered.map(v => `<div class="disc-row" style="cursor:pointer" data-entity="${_esc(v.entity_id)}">
          <span class="disc-name">\uD83E\uDDA4 ${_esc(this._sanitize(v.name))}</span>
          <span class="disc-id">${_esc(v.entity_id)}</span>
          <span class="disc-state" style="color:${v.state === 'cleaning' ? '#22c55e' : '#6b7280'}">${_esc(this._sanitize(v.state))}</span>
          ${v.battery ? `<span class="disc-bat">\uD83D\uDD0B ${_esc(v.battery)}%</span>` : ''}
          <button class="maint-add-btn disc-add-btn" data-entity="${_esc(v.entity_id)}" style="padding:3px 10px;font-size:11px">+ Add</button>
        </div>`).join('')}
      </div>` : '';

    const userDevsHtml = (this._userDevices || []).length > 0 ? `<div class="section-block"><div class="section-title">\u2795 Manually added</div>${this._userDevices.map(ud => `<div class="disc-row"><span class="disc-name">${_esc(this._sanitize(ud.icon || '\uD83E\uDDA4'))} ${_esc(this._sanitize(ud.name))}</span><span class="disc-id">${_esc(ud.vacuum_entity)}</span><button class="maint-del-btn user-dev-remove" data-entity="${_esc(ud.vacuum_entity)}" title="Remove">\uD83D\uDDD1\uFE0F</button></div>`).join('')}</div>` : '';

    return `
      <div class="tab-content">
        <div style="margin-bottom:16px">
          <div style="font-size:15px;font-weight:700;color:var(--bento-text);margin-bottom:4px">\u2699\uFE0F Settings</div>
          <div style="font-size:12px;color:var(--bento-text-secondary)">Device management, tank reset methods and automations.</div>
        </div>

        <!-- Device management -->
        <div style="background:var(--vwm-overlay-light,rgba(0,0,0,0.03));border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:14px;padding:16px;margin-bottom:16px">
          <div style="font-size:14px;font-weight:700;color:var(--bento-text);margin-bottom:4px;display:flex;align-items:center;gap:8px">
            \uD83E\uDDA4 Devices
          </div>
          <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:12px;line-height:1.5">
            Add, remove, or discover vacuum cleaners in Home Assistant.
          </div>
          ${userDevsHtml}
          ${fullTankTip}
          ${discoveredHtml}
          <div class="section-block" style="margin-top:12px">
            <div class="section-title">Manual vacuum addition</div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px">
              <input type="text" id="manual-vacuum-entity" placeholder="vacuum.roborock_s7" style="flex:1;min-width:200px;padding:8px 12px;border:1.5px solid var(--bento-border,#e2e8f0);border-radius:8px;font-size:13px;background:var(--bento-card,#fff);color:var(--bento-text,#1e293b)">
              <button class="btn-primary" id="btn-add-manual-vacuum" style="padding:8px 16px;white-space:nowrap">+ Add</button>
            </div>
            <p style="margin:6px 0 0;font-size:11px;color:var(--bento-text-secondary,#64748B)">Enter vacuum entity_id if auto-discovery didn't find it</p>
          </div>
        </div>

        <!-- Signal mapping -->
        ${this._buildSignalMappingSection(device)}

        <!-- Anonymous calibration sharing (opt-in) -->
        ${this._buildCalibrationSharingSection(device, data)}

        <!-- Refill methods -->
        <div style="background:var(--vwm-overlay-light,rgba(0,0,0,0.03));border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:14px;padding:16px">
          <div style="font-size:14px;font-weight:700;color:var(--bento-text);margin-bottom:4px;display:flex;align-items:center;gap:8px">
            \uD83D\uDD04 Tank reset methods
          </div>
          <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:12px;line-height:1.5">
            Choose how Home Assistant learns that you refilled the tank. Every option marks the tank full, and you can combine them.
          </div>

          ${this._buildRefillMethodCard(device, data)}
        </div>
      </div>`;
  }

  _refillChoices(device) {
    const vacuum = (device && device.vacuum_entity) || '';
    const stored = this._serverState && this._serverState.settings && this._serverState.settings.refill_settings;
    if (stored && typeof stored === 'object' && stored[vacuum] && typeof stored[vacuum] === 'object') return { ...stored[vacuum] };
    const legacy = this._refillConfig[vacuum.replace('vacuum.', '')] || {};
    const choices = {};
    if (typeof legacy.buttonEntity === 'string') choices.button_entity = legacy.buttonEntity;
    if (typeof legacy.sensorEntity === 'string') choices.lid_entity = legacy.sensorEntity;
    return choices;
  }

  _buildRefillMethodCard(device, data = {}) {
    const vacuum = (device && device.vacuum_entity) || '';
    const choices = this._refillChoices(device);
    const legacy = this._refillConfig[vacuum.replace('vacuum.', '')] || {};
    const buttons = this._getInputButtons();
    const sensors = this._getDoorSensors();
    const selectedButton = choices.button_entity || '';
    const selectedLid = choices.lid_entity || (typeof device?.reset_door_sensor === 'string' ? device.reset_door_sensor : '');
    const withSelected = (list, id) => (id && !list.some(item => item.id === id) ? [{ id, name: id, state: this._getStateValue(id) || 'unavailable' }, ...list] : list);
    const buttonOpts = withSelected(buttons, selectedButton).map(b =>
      `<option value="${_esc(b.id)}" ${selectedButton === b.id ? 'selected' : ''}>${_esc(this._sanitize(b.name))}</option>`).join('');
    const sensorOpts = withSelected(sensors, selectedLid).map(item =>
      `<option value="${_esc(item.id)}" ${selectedLid === item.id ? 'selected' : ''}>${_esc(this._sanitize(item.name))} (${_esc(this._sanitize(item.state))})</option>`).join('');
    const autoAvailable = Boolean(device && (device.dock_error_sensor || device.dock_clean_water_sensor || device.water_error_sensor));
    const autoDefault = Boolean(device && (device.refill_on_clear || device.refill_on_clear_inferred));
    const autoChecked = typeof choices.auto_refill === 'boolean' ? choices.auto_refill : autoDefault;

    const statusOn = '<span style="color:#22c55e;font-size:11px;font-weight:600">✅ On</span>';
    const statusOff = '<span style="color:var(--vwm-text-muted,#9ca3af);font-size:11px">— Off</span>';
    const cardSt = 'margin-bottom:10px;padding:14px;background:var(--vwm-bg,#fff);border-radius:12px;border:1.5px solid var(--vwm-border,#e5e7eb)';
    const labelSt = 'font-weight:700;font-size:13px;margin-bottom:6px;display:flex;align-items:center;gap:6px;flex-wrap:wrap';
    const descSt = 'font-size:12px;color:var(--vwm-text-secondary,#6b7280);line-height:1.5;margin-bottom:10px';
    const selectSt = 'width:100%;max-width:100%;min-width:0;padding:8px 12px;border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:8px;font-size:12px;background:var(--vwm-bg,#fff);color:var(--vwm-text,#1e293b);font-family:Inter,sans-serif';
    const btnSt = 'padding:7px 16px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;font-family:Inter,sans-serif';
    const btnSuccess = btnSt + ';background:rgba(34,197,94,0.12);color:#16a34a;border:1px solid rgba(34,197,94,0.3)';
    const legacyIds = [legacy.buttonAutoId, legacy.sensorAutoId].filter(id => typeof id === 'string' && id);
    const legacyNotice = legacyIds.length ? `
      <div style="${cardSt};border-color:rgba(245,158,11,0.4)">
        <div style="${descSt};margin-bottom:8px">An earlier version created ${legacyIds.map(id => `<code>automation.${_esc(id)}</code>`).join(' and ')}. The options above now reset the tank directly. That automation also sets <code>input_number.${_esc(vacuum.replace('vacuum.', ''))}_water_used_ml</code> to 0 if such a helper exists: keep it if that helper is your own counter.</div>
        <button id="vwm-refill-legacy-remove" style="${btnSt};background:rgba(239,68,68,0.08);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">Remove old automation</button>
      </div>` : '';
    const refills = (data.refillHistory || []).slice(0, 5);
    const history = refills.length ? `<div style="font-size:11px;color:var(--vwm-text-secondary,#6b7280);margin-top:8px">Recent refills: ${refills.map(r => `${_esc(this._formatReset(r.ts))} (${_esc(VWM_REFILL_SOURCE_LABEL[r.source] || r.source)})`).join(', ')}</div>` : '';

    return `
      <div style="${cardSt}">
        <div style="${labelSt}">① Refilled button in this card ${statusOn}</div>
        <div style="${descSt};margin-bottom:0">Press <strong>💧 Refilled</strong> in the Water tab after filling the tank. It always works, also together with the options below.</div>
      </div>

      <div style="${cardSt}">
        <div style="${labelSt}">② Automatic from the dock ${autoAvailable ? (autoChecked ? statusOn : statusOff) : '<span style="color:var(--vwm-text-muted,#9ca3af);font-size:11px">not available for this robot</span>'}</div>
        <div style="${descSt}">When the dock's clean-water-empty error clears, the tank counts as refilled. Turn this off if that error sometimes clears without a refill, for example after re-seating the tank.</div>
        <label style="display:flex;gap:8px;align-items:center;font-size:12px">
          <input type="checkbox" id="vwm-refill-auto" ${autoChecked ? 'checked' : ''} ${autoAvailable ? '' : 'disabled'}>
          Refill automatically when the dock's empty-tank error clears
        </label>
      </div>

      <div style="${cardSt}">
        <div style="${labelSt}">③ Dashboard or physical button ${selectedButton ? statusOn : statusOff}</div>
        <div style="${descSt}">Pick an <code>input_button</code> or <code>button</code> entity. Pressing it marks the tank refilled: add it as a dashboard tile or link a Zigbee/Z-Wave button to it.</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <select id="vwm-refill-button" style="${selectSt};flex:1;min-width:180px">
            <option value="">— Not used —</option>
            ${buttonOpts}
          </select>
          <button id="refill-btn-create" style="${btnSuccess}">+ Create input_button</button>
        </div>
      </div>

      <div style="${cardSt}">
        <div style="${labelSt}">④ Tank lid or door sensor ${selectedLid ? statusOn : statusOff}</div>
        <div style="${descSt}">A contact sensor on the tank or dock lid. Closing it counts as a full refill.</div>
        <select id="vwm-refill-lid" style="${selectSt}">
          <option value="">— Not used —</option>
          ${sensorOpts}
        </select>
      </div>

      <div style="${cardSt}">
        <div style="${labelSt}">⑤ Automation, script or NFC tag</div>
        <div style="${descSt};margin-bottom:6px">Call this action from anything in Home Assistant:</div>
        <pre style="margin:0;padding:8px 10px;border-radius:8px;background:var(--vwm-overlay-light,rgba(0,0,0,0.04));color:var(--vwm-text,#1e293b);font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere;user-select:all">action: ha_vacuum_water_monitor.mark_refilled
target:
  entity_id: ${_esc(vacuum)}</pre>
      </div>

      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn-primary" id="vwm-refill-save" style="padding:8px 16px">Save refill options</button>
        <span id="vwm-refill-status" role="status" aria-live="polite" style="font-size:12px"></span>
      </div>
      ${history}
      ${legacyNotice}`;
  }

  async _saveRefillChoices(device) {
    const sr = this.shadowRoot;
    const status = sr.getElementById('vwm-refill-status');
    const auto = sr.getElementById('vwm-refill-auto');
    const button = sr.getElementById('vwm-refill-button')?.value || null;
    const lid = sr.getElementById('vwm-refill-lid')?.value || null;
    if (!this._hass || !device?.vacuum_entity) return false;
    const shortId = device.vacuum_entity.replace('vacuum.', '');
    const legacyBefore = { ...(this._refillConfig[shortId] || {}) };
    const lidBefore = ((this._userDevices || []).find(d => d && d.vacuum_entity === device.vacuum_entity) || {}).reset_door_sensor;
    try {
      const result = await this._hass.callWS({
        type: `${VWM_DOMAIN}/set_refill_settings`,
        vacuum_entity: device.vacuum_entity,
        auto_refill: auto && !auto.disabled ? auto.checked : null,
        button_entity: button,
        lid_entity: lid,
      });
      if (result && result.settings) {
        this._serverState.settings = result.settings;
        this._applyServerSettings();
      }
      // Bindings made by the pre-5.7 card: the legacy button/lid config and a lid in
      // the user device must not keep a removed choice active.
      if (legacyBefore.buttonEntity || legacyBefore.sensorEntity) {
        const next = { ...(this._refillConfig[shortId] || legacyBefore) };
        delete next.buttonEntity;
        delete next.sensorEntity;
        this._refillConfig[shortId] = next;
        this._saveRefillConfig();
      }
      const userDevice = (this._userDevices || []).find(d => d && d.vacuum_entity === device.vacuum_entity);
      if (userDevice && lidBefore && lidBefore !== lid) {
        this._upsertUserDevicePatch(device, { reset_door_sensor: null });
      }
      if (status) { status.textContent = '✅ Saved. Refill options apply right away.'; status.style.color = '#22c55e'; }
      return true;
    } catch (err) {
      if (status) { status.textContent = `Could not save: ${(err && err.message) || err}`; status.style.color = '#ef4444'; }
      return false;
    }
  }

  async _removeLegacyRefillAutomations(device) {
    const shortId = ((device && device.vacuum_entity) || '').replace('vacuum.', '');
    const legacy = this._refillConfig[shortId] || {};
    for (const key of ['buttonAutoId', 'sensorAutoId']) {
      const id = legacy[key];
      if (typeof id !== 'string' || !id) continue;
      try {
        await this._hass.callApi('DELETE', `config/automation/config/${encodeURIComponent(id)}`);
      } catch (err) {
        // Already removed by hand, or automations.yaml is not UI-managed.
        console.warn('[ha-vacuum-water-monitor] old refill automation not removed:', id, err);
      }
      delete legacy[key];
    }
    this._refillConfig[shortId] = legacy;
    this._saveRefillConfig();
    this._render();
  }

  // ── SIGNAL MAPPING ─────────────────────────────────────────────────────────

  // Roles offered for manual assignment, in the order they are rendered.
  _signalRoleCatalog() {
    return [
      ['status_sensor', 'Vacuum status'],
      ['area_sensor', 'Cleaned area'],
      ['duration_sensor', 'Cleaning time'],
      ['mop_mode_entity', 'Mop mode'],
      ['mop_intensity_entity', 'Water output level'],
      ['cleaning_mode_entity', 'Cleaning mode'],
      ['mop_attached_sensor', 'Mop attached'],
      ['water_box_attached_sensor', 'Water tank attached'],
      ['water_shortage_sensor', 'Water shortage'],
      ['dock_clean_water_sensor', 'Dock clean water'],
      ['dock_dirty_water_sensor', 'Dock dirty water'],
    ];
  }

  // Roles the backend accepts as an override — mirrors _DIRECT_SIGNAL_FIELDS so
  // the card never binds a stored override the tick would ignore, and never
  // writes a non-signal device field from stored settings.
  _overridableSignalRoles() {
    return new Set([
      'status_sensor', 'cleaning_active_sensor', 'area_sensor', 'duration_sensor',
      'mop_mode_entity', 'mop_intensity_entity', 'cleaning_mode_entity',
      'mop_attached_sensor', 'water_box_attached_sensor', 'water_box_detached_sensor',
      'water_shortage_sensor', 'dock_clean_water_sensor', 'dock_dirty_water_sensor',
      'dock_error_sensor', 'dock_status_sensor', 'water_error_sensor',
      'tank_level_sensor', 'dock_tank_level_sensor',
    ]);
  }

  _signalOverridesFor(vacuumEntity) {
    const all = this._serverState?.settings?.signal_overrides;
    if (!all || typeof all !== 'object') return {};
    const entry = all[String(vacuumEntity || '')];
    return entry && typeof entry === 'object' ? entry : {};
  }

  _buildSignalMappingSection(device) {
    const sectionSt = 'background:var(--vwm-overlay-light,rgba(0,0,0,0.03));border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:14px;padding:16px;margin-bottom:16px';
    const header = `
      <div style="font-size:14px;font-weight:700;color:var(--bento-text);margin-bottom:4px;display:flex;align-items:center;gap:8px">
        \uD83D\uDD17 Signal mapping
      </div>
      <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:12px;line-height:1.5">
        The card detects your robot's entities automatically. If the vacuum is not fully recognised, correct or complete the assignment here \u2014 an entity you pick wins over automatic detection, and <strong>Automatic</strong> gives detection back.
      </div>`;

    const vacId = String(device?.vacuum_entity || '');
    if (!vacId) {
      return `
        <div style="${sectionSt}">
          ${header}
          <div style="font-size:12px;color:var(--bento-text-secondary);line-height:1.5">Add a vacuum first \u2014 entity assignment is stored per device.</div>
        </div>`;
    }

    const signals = device?.signals && typeof device.signals === 'object' ? device.signals : {};
    const overrides = this._signalOverridesFor(vacId);
    const ambiguous = new Set((Array.isArray(device?.ambiguous_roles) ? device.ambiguous_roles : []).map(role => String(role)));
    const siblings = (Array.isArray(device?.sibling_entities) ? device.sibling_entities : [])
      .filter(entry => entry && typeof entry === 'object' && entry.entity_id);

    const optionLabel = (entry) => {
      const entityId = String(entry.entity_id);
      const name = this._sanitize(String(entry.name || entityId));
      const extras = [entry.device_class, entry.unit_of_measurement]
        .filter(value => value != null && String(value) !== '')
        .map(value => this._sanitize(String(value)));
      return `${name} \u2014 ${entityId}${extras.length ? ' \u00B7 ' + extras.join(' \u00B7 ') : ''}`;
    };

    const rowSt = 'padding:10px 12px;margin-bottom:8px;background:var(--vwm-bg,#fff);border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:10px';
    const rowWarnSt = 'padding:10px 12px;margin-bottom:8px;background:rgba(245,158,11,0.08);border:1.5px solid rgba(245,158,11,0.45);border-radius:10px';
    const selectSt = 'width:100%;margin-top:6px;padding:7px 10px;border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:8px;font-size:12px;background:var(--vwm-bg,#fff);color:var(--vwm-text,#1e293b);font-family:Inter,sans-serif';
    const labelSt = 'font-size:12px;font-weight:700;color:var(--bento-text)';

    const rows = this._signalRoleCatalog().map(([role, label]) => {
      const current = String(overrides[role] ?? signals[role] ?? '');
      const listed = siblings.some(entry => String(entry.entity_id) === current);
      const options = ['<option value="">Automatic</option>'];
      if (current && !listed) {
        options.push(`<option value="${_esc(current)}" selected>${_esc(current)} (currently bound)</option>`);
      }
      for (const entry of siblings) {
        const entityId = String(entry.entity_id);
        options.push(`<option value="${_esc(entityId)}"${entityId === current ? ' selected' : ''}>${_esc(optionLabel(entry))}</option>`);
      }
      // Once the user has assigned this role by hand, the backend's ambiguity
      // is settled — keeping the warning would make a resolved row look broken.
      const isAmbiguous = ambiguous.has(role) && !overrides[role];
      return `
        <div style="${isAmbiguous ? rowWarnSt : rowSt}">
          <div style="${labelSt}">
            ${_esc(label)}
            ${isAmbiguous ? '<span style="margin-left:6px;font-size:11px;font-weight:600;color:#b45309">\u26A0\uFE0F several candidates found \u2014 please confirm</span>' : ''}
          </div>
          <select class="vwm-signal-select" id="vwm-signal-${_esc(role)}" data-role="${_esc(role)}" style="${selectSt}">
            ${options.join('')}
          </select>
        </div>`;
    }).join('');

    const noSiblings = siblings.length === 0 ? `
      <div style="margin-bottom:10px;padding:10px 14px;background:rgba(245,158,11,0.1);border:1.5px solid rgba(245,158,11,0.25);border-radius:10px;font-size:12px;line-height:1.5;color:var(--vwm-text,#1e293b)">
        \u26A0\uFE0F Home Assistant reports no assignable entities for <strong>${_esc(vacId)}</strong>. The robot's sensors have to belong to the same HA device before they can be mapped here.
      </div>` : '';

    return `
      <div style="${sectionSt}">
        ${header}
        ${noSiblings}
        ${rows}
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px">
          <button id="vwm-signal-save" style="padding:8px 16px;border:none;border-radius:8px;background:#3b82f6;color:#fff;font-weight:600;font-size:12px;cursor:pointer;font-family:Inter,sans-serif">\uD83D\uDCBE Save signal mapping</button>
          <span id="vwm-signal-status" role="status" aria-live="polite" style="font-size:11px;color:var(--bento-text-secondary)"></span>
        </div>
      </div>`;
  }

  // ── MULTI-DEVICE TABS ──────────────────────────────────────────────────────

  _buildDeviceTabs(devices) {
    if (devices.length <= 1) return '';
    return `<div class="device-tabs">
      ${devices.map((d, i) => `<button class="dtab ${i === this._activeDeviceIdx ? 'dtab-active' : ''}" data-didx="${i}">${_esc(this._sanitize(d.icon || '\uD83E\uDDA4'))} ${_esc(this._sanitize(d.name || 'Device ' + (i+1)))}</button>`).join('')}
    </div>`;
  }

  // ── MAIN RENDER ───────────────────────────────────────────────────────────

  _render({ preserveDraft = false } = {}) {
    const draft = preserveDraft ? this._captureDraftState() : null;
    if (!this._hass) return;
   try {
    const devices = this._getDevices();
    const device = devices[this._activeDeviceIdx] || devices[0] || {};
    const data = Object.keys(device).length ? this._calcDeviceData(device) : {};

    const cfg = this._config;
    const status = data.vacState !== undefined ? this._getStatus(data, cfg) : { label: '--', color: '#6b7280', icon: '' };

    // Tabs definition
    const tabs = [
      { id: 'water', icon: '\uD83D\uDCA7', label: 'Water' },
      { id: 'maintenance', icon: '\uD83D\uDD27', label: 'Maint.' },
      { id: 'history', icon: '\uD83D\uDDD3\uFE0F', label: 'History' },
      { id: 'stats', icon: '\uD83D\uDCCA', label: 'Stats' },
      { id: 'database', icon: '\uD83D\uDCDA', label: 'Database' },
      { id: 'settings', icon: '\u2699\uFE0F', label: 'Settings' },
    ];

    const tabNav = `<div class="tab-nav">
      ${tabs.map(t => `<button class="tab-btn ${this._activeTab === t.id ? 'tab-active' : ''}" data-tab="${t.id}">${t.icon} ${t.label}</button>`).join('')}
    </div>`;

    const deviceHeader = devices.length > 0 ? `
      <div class="device-header">
        <div class="device-name">${_esc(this._sanitize(device.icon || '\uD83E\uDDA4'))} ${_esc(this._sanitize(device.name || 'Vacuum'))}</div>
        ${data.vacState !== undefined ? `<div class="status-badge" style="background:${status.color}20;color:${status.color};border:1px solid ${status.color}40">${status.icon} ${status.label}</div>` : ''}
      </div>` : '';

    let tabContent = '';
    if (this._activeTab === 'water') tabContent = this._buildWaterTab(device, data);
    else if (this._activeTab === 'maintenance') tabContent = this._buildMaintenanceTab(device, data);
    else if (this._activeTab === 'history') tabContent = this._buildHistoryTab(device, data);
    else if (this._activeTab === 'stats') tabContent = this._buildStatsTab(devices);
    else if (this._activeTab === 'database') tabContent = this._buildDatabaseTab();
    else if (this._activeTab === 'settings') tabContent = this._buildSettingsTab(device, data);

    const deviceTabsHtml = this._buildDeviceTabs(devices);

    const _newHtml = `
      <style>${HA_VACUUM_WATER_MONITOR_BENTO_CSS}
/* === HA Tools split — premium banners (donate / intro / prereq) === */

/* Donation footer — diamond top */
.donate-section {  margin: 24px 0 4px; padding: 20px 24px; position: relative; overflow: hidden;  background: linear-gradient(135deg, rgba(99,102,241,0.06), rgba(236,72,153,0.06));  border: 1px solid rgba(99,102,241,0.18); border-radius: var(--bento-radius-md, 18px);  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 18px;  font-family: 'Inter', -apple-system, sans-serif;}
.donate-section::before {  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;  background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899);}
.donate-section .donate-text { flex: 1; min-width: 240px; }
.donate-section h3 {  margin: 0 0 6px; font-size: 16px; font-weight: 700; letter-spacing: -0.02em;  background: linear-gradient(135deg, #6366f1, #ec4899);  -webkit-background-clip: text; background-clip: text; color: transparent;}
.donate-section p { margin: 0; font-size: 13px; line-height: 1.55; color: var(--bento-text-secondary, #57534e); letter-spacing: -0.005em; }
.donate-buttons { display: flex; gap: 10px; flex-wrap: wrap; }
.donate-btn {  display: inline-flex; align-items: center; gap: 6px; padding: 10px 18px;  border-radius: 12px; font-weight: 700; font-size: 13px; letter-spacing: -0.005em;  text-decoration: none; transition: transform 0.2s cubic-bezier(0.4,0,0.2,1), box-shadow 0.2s, filter 0.2s;  border: 1px solid transparent;}
.donate-btn:hover { transform: translateY(-2px); filter: brightness(1.05); }
.donate-btn.coffee {  background: linear-gradient(135deg, #FFDD00, #FFC700); color: #000;  box-shadow: 0 4px 14px -2px rgba(255, 221, 0, 0.4);}
.donate-btn.coffee:hover { box-shadow: 0 8px 24px -4px rgba(255, 221, 0, 0.55); }
.donate-btn.paypal {  background: linear-gradient(135deg, #0070ba, #005ea6); color: #fff;  box-shadow: 0 4px 14px -2px rgba(0, 112, 186, 0.45);}
.donate-btn.paypal:hover { box-shadow: 0 8px 24px -4px rgba(0, 112, 186, 0.6); }
:host(.bento-dark) .donate-section { background: linear-gradient(135deg, rgba(129,140,248,0.10), rgba(244,114,182,0.10)); border-color: rgba(129,140,248,0.25); }
:host(.bento-dark) .donate-section h3 { background: linear-gradient(135deg, #a5b4fc, #f9a8d4); -webkit-background-clip: text; background-clip: text; color: transparent; }
:host(.bento-dark) .donate-section p { color: #d6d3d1; }
@media (max-width: 600px) {  .donate-section { flex-direction: column; text-align: center; padding: 18px; }  .donate-buttons { justify-content: center; width: 100%; } }

/* Prereq banner — premium */
.prereq-banner {  display: flex; align-items: flex-start; gap: 14px; padding: 16px 20px;  border-radius: var(--bento-radius-sm, 12px); margin: 0 0 16px;  font-size: 13px; line-height: 1.55; border: 1px solid;  font-family: 'Inter', sans-serif; letter-spacing: -0.005em;  position: relative; overflow: hidden;}
.prereq-banner::before {  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;}
.prereq-banner.prereq-error { background: rgba(239,68,68,0.06); border-color: rgba(239,68,68,0.25); color: #991b1b; }
.prereq-banner.prereq-error::before { background: linear-gradient(180deg, #ef4444, #f87171); }
.prereq-banner.prereq-info  { background: rgba(99,102,241,0.06); border-color: rgba(99,102,241,0.25); color: #4338ca; }
.prereq-banner.prereq-info::before  { background: linear-gradient(180deg, #6366f1, #8b5cf6); }
.prereq-banner .prereq-icon { font-size: 22px; line-height: 1; padding-top: 2px; flex-shrink: 0; }
.prereq-banner .prereq-text { flex: 1; min-width: 0; }
.prereq-banner .prereq-text strong { font-weight: 700; letter-spacing: -0.01em; }
.prereq-banner code {  background: rgba(0,0,0,0.06); padding: 1px 7px; border-radius: 5px;  font-size: 12px; font-family: 'JetBrains Mono', ui-monospace, monospace;  border: 1px solid rgba(0,0,0,0.08);}
.prereq-banner .prereq-cta {  display: inline-flex; align-items: center; padding: 8px 16px; border-radius: 10px;  background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff !important;  text-decoration: none; font-weight: 700; font-size: 12.5px; flex-shrink: 0;  letter-spacing: -0.005em;  box-shadow: 0 4px 14px -2px rgba(99,102,241,0.45);  transition: all 0.2s cubic-bezier(0.4,0,0.2,1);}
.prereq-banner .prereq-cta:hover { transform: translateY(-1px); box-shadow: 0 8px 24px -4px rgba(99,102,241,0.6); }
:host(.bento-dark) .prereq-banner.prereq-error { background: rgba(248,113,113,0.10); border-color: rgba(248,113,113,0.30); color: #fca5a5; }
:host(.bento-dark) .prereq-banner.prereq-info { background: rgba(129,140,248,0.10); border-color: rgba(129,140,248,0.30); color: #c7d2fe; }
:host(.bento-dark) .prereq-banner code { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.10); }
@media (max-width: 600px) {  .prereq-banner { flex-direction: column; align-items: stretch; padding-left: 20px; }  .prereq-banner .prereq-cta { align-self: flex-start; } }

/* First-run intro banner — premium */
.intro-banner {  position: relative; padding: 18px 52px 18px 22px; margin: 0 0 18px;  background: linear-gradient(135deg, rgba(99,102,241,0.08), rgba(236,72,153,0.06));  border: 1px solid rgba(99,102,241,0.20);  border-radius: var(--bento-radius-sm, 12px);  font-size: 13px; line-height: 1.55; overflow: hidden;  font-family: 'Inter', sans-serif; letter-spacing: -0.005em;  animation: bentoSlideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);}
.intro-banner::before {  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;  background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899);}
.intro-banner .intro-headline {  font-weight: 700; font-size: 14.5px; margin-bottom: 10px; letter-spacing: -0.02em;  background: linear-gradient(135deg, #6366f1, #ec4899);  -webkit-background-clip: text; background-clip: text; color: transparent;  display: flex; align-items: center; gap: 8px;}
.intro-banner .intro-steps {  margin: 8px 0 0; padding: 0; list-style: none; counter-reset: introstep;}
.intro-banner .intro-steps li {  margin-bottom: 8px; line-height: 1.55; color: var(--bento-text, #0c0a09);  padding-left: 32px; position: relative; counter-increment: introstep;  font-size: 12.5px;}
.intro-banner .intro-steps li::before {  content: counter(introstep); position: absolute; left: 0; top: -1px;  width: 22px; height: 22px; border-radius: 50%;  background: var(--bento-card, #fff); border: 1px solid rgba(99,102,241,0.25);  display: flex; align-items: center; justify-content: center;  font-size: 11px; font-weight: 800; color: #6366f1;  font-family: 'JetBrains Mono', ui-monospace, monospace;  font-feature-settings: 'tnum' 1;}
.intro-banner .intro-dismiss {  position: absolute; top: 12px; right: 14px;  background: var(--bento-card, transparent); border: 1px solid var(--bento-border, transparent);  cursor: pointer; font-size: 14px; line-height: 1;  color: var(--bento-text-secondary, #64748B);  padding: 4px 8px; border-radius: 999px;  transition: all 0.15s ease;}
.intro-banner .intro-dismiss:hover {  background: var(--bento-bg-2, #e7e5e4); color: var(--bento-text, #0c0a09);  transform: rotate(90deg);}
:host(.bento-dark) .intro-banner { background: linear-gradient(135deg, rgba(129,140,248,0.14), rgba(244,114,182,0.10)); border-color: rgba(129,140,248,0.30); }
:host(.bento-dark) .intro-banner .intro-headline { background: linear-gradient(135deg, #a5b4fc, #f9a8d4); -webkit-background-clip: text; background-clip: text; color: transparent; }
:host(.bento-dark) .intro-banner .intro-steps li { color: #fafaf9; }
:host(.bento-dark) .intro-banner .intro-steps li::before { background: #16161f; border-color: rgba(129,140,248,0.35); color: #a5b4fc; }
:host(.bento-dark) .intro-banner .intro-dismiss { background: #16161f; border-color: #27272f; color: #d6d3d1; }
:host(.bento-dark) .intro-banner .intro-dismiss:hover { background: #27272f; color: #fafaf9; }


        * { box-sizing: border-box; }

        
/* ===== BENTO DESIGN SYSTEM (local fallback) ===== */

:host {
  --bento-primary: #3B82F6;
  --bento-primary-hover: #2563EB;
  --bento-primary-light: rgba(59, 130, 246, 0.08);
  --bento-success: #10B981;
  --bento-success-light: rgba(16, 185, 129, 0.08);
  --bento-error: #EF4444;
  --bento-error-light: rgba(239, 68, 68, 0.08);
  --bento-warning: #F59E0B;
  --bento-warning-light: rgba(245, 158, 11, 0.08);
  --bento-bg: var(--primary-background-color, #F8FAFC);
  --bento-card: var(--card-background-color, #FFFFFF);
  --bento-border: var(--divider-color, #E2E8F0);
  --bento-text: var(--primary-text-color, #1E293B);
  --bento-text-secondary: var(--secondary-text-color, #64748B);
  --bento-text-muted: var(--disabled-text-color, #94A3B8);
  --bento-radius-xs: 6px;
  --bento-radius-sm: 10px;
  --bento-radius-md: 16px;
  --bento-shadow-sm: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06);
  --bento-shadow-md: 0 4px 12px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.04);
  --bento-shadow-lg: 0 8px 25px rgba(0,0,0,0.06), 0 4px 10px rgba(0,0,0,0.04);
  --bento-transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

:host {
  display: block;
  font-family: Inter, sans-serif;
  --vwm-bg: var(--bento-card);
  --vwm-text: var(--bento-text);
  --vwm-text-secondary: var(--bento-text-secondary);
  --vwm-text-muted: var(--bento-text-muted);
  --vwm-border: var(--bento-border);
  --vwm-surface: var(--bento-bg);
  --vwm-overlay-light: var(--bento-primary-light);
  --vwm-overlay-medium: rgba(0,0,0,0.08);
}
        .card { background: var(--bento-card) !important; border-radius: 16px; padding: 16px; color: var(--bento-text); line-height:1.45;
  border: 1px solid var(--bento-border) !important;
  border-radius: var(--bento-radius-md) !important;
  box-shadow: var(--bento-shadow-sm);
}
        .card-title { font-size: 15px; font-weight: 700; color: var(--bento-text-secondary); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
        .device-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .device-name { font-weight: 600; font-size: 14px; }
        .status-badge { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.3px; }
        /* Device tabs */
        .device-tabs { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
        .dtab { background: var(--bento-primary-light); color: var(--bento-text-secondary); border: 1px solid var(--bento-border); border-radius: 20px; padding: 4px 12px; font-size: 12px; cursor: pointer; font-family: Inter, sans-serif; transition: all 0.2s; }
        .dtab-active { background: rgba(99,102,241,0.2); color: #818cf8; border-color: rgba(99,102,241,0.4); }
        /* Tab navigation */
        .tab-nav { display: flex; gap: 2px; margin-bottom: 14px; background: var(--bento-primary-light); border-radius: 10px; padding: 3px; border-bottom: none !important; }
        .tab-btn { flex: 1; background: transparent; color: var(--bento-text-muted); border: none; border-radius: 8px; padding: 7px 4px; font-size: 11px; font-weight: 600; cursor: pointer; font-family: Inter, sans-serif; transition: all 0.2s; }
        .tab-active { background: rgba(59,130,246,0.12); color: var(--bento-text); }
        /* Content */
        .tab-content { }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        .device-body { display: flex; align-items: center; gap: 16px; }
        .gauge-wrap { display: flex; flex-direction: column; align-items: center; gap: 6px; flex-shrink: 0; }
        .details { flex: 1; display: flex; flex-direction: column; gap: 6px; }
        .row { display: flex; justify-content: space-between; align-items: center; gap:12px; min-height:30px; padding:4px 0; font-size: 12px; }
        .row-label { color: var(--bento-text-secondary); min-width:0; line-height:1.4; }
        .row-val { font-weight: 600; color: var(--bento-text); }
        .accounting-guidance { display:grid; gap:4px; padding:12px 14px; margin-bottom:14px; border:1px solid; border-radius:10px; font-size:12px; line-height:1.55; color:var(--bento-text,#1a1a2e); }
        .accounting-guidance b { font-size:12px; }
        .diagnostics { margin-top:16px; color:var(--bento-text-secondary,#64748b); }
        .diagnostics summary { cursor:pointer; font-size:12px; font-weight:700; padding:8px 0; }
        .diagnostics-grid { display:grid; grid-template-columns:minmax(128px,auto) minmax(0,1fr); gap:9px 16px; margin-top:8px; padding:14px; border-radius:10px; background:var(--vwm-overlay-light,rgba(0,0,0,0.03)); font-size:12px; line-height:1.5; }
        .diagnostics-label { font-weight:650; color:var(--bento-text,#1a1a2e); }
        .diagnostics-value { min-width:0; overflow-wrap:anywhere; word-break:break-word; }
        @media (max-width: 480px) { .diagnostics-grid { grid-template-columns:1fr; gap:3px; } .diagnostics-value { margin-bottom:7px; } }
        .chip { font-size: 10px; padding: 2px 8px; border-radius: 12px; font-weight: 500; }
        .chip-active { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); animation: pulse 1.5s infinite; }
        .chip-idle { background: var(--bento-primary-light); color: var(--bento-text-muted); border: 1px solid var(--bento-border); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
        .refill-wrap { margin-top: 12px; text-align: right; }
        .refill-btn { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); border-radius: 8px; padding: 7px 16px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: Inter, sans-serif; }
        .refill-btn:hover { background: rgba(59,130,246,0.25); }
        .alert-banner { background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; border-radius: 8px; padding: 8px 12px; font-size: 12px; font-weight: 500; margin-bottom: 10px; }
        .alert-warn { background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.3); color: #fcd34d; }
        .no-water-note { color: var(--bento-text-muted); font-size: 12px; text-align: center; padding: 12px 0; }
        /* Sections */
        .section-block { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--bento-border); }
        .section-title { font-size: 12px; line-height:1.4; font-weight: 700; color: var(--bento-text-muted); text-transform: uppercase; letter-spacing: 0.7px; margin-bottom: 10px; }
        /* Dock */
        .dock-row { display: flex; justify-content: space-between; align-items: center; gap:12px; min-height:32px; font-size: 12px; padding: 5px 0; }
        .dock-val { font-weight: 600; font-size: 12px; }
        /* Consumables */
        .consumable-row { display: flex; align-items: center; gap: 10px; min-height:32px; padding: 5px 0; }
        .con-label { font-size: 12px; line-height:1.4; color: var(--bento-text-secondary); width: 112px; flex-shrink: 0; }
        .con-bar-wrap { flex: 1; }
        .con-bar { height: 6px; background: rgba(59,130,246,0.10); border-radius: 3px; overflow: hidden; }
        .con-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
        .con-val { font-size: 12px; font-weight: 600; width: 62px; text-align: right; flex-shrink: 0; }
        .con-val-wide { width: 80px; }
        /* Custom maintenance */
        .custom-maint-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
        .custom-maint-row .con-label { flex: 1; width: auto; }
        .maint-done-btn, .maint-del-btn { background: none; border: none; cursor: pointer; font-size: 14px; padding: 2px; }
        /* Add form */
        .add-maint-form { display: flex; gap: 6px; flex-wrap: wrap; }
        .contribution-form { display: grid; gap: 10px; font-size: 12px; line-height: 1.5; }
        .contribution-form p { margin: 0; }
        .contribution-form label { display: grid; gap: 4px; }
        .contribution-form .maint-input { width: 100%; box-sizing: border-box; }
        .contribution-form button { justify-self: start; max-width: 100%; white-space: normal; }
        .contribution-form button:disabled { opacity: 0.45; cursor: default; }
        .maint-input { background: var(--bento-primary-light); border: 1px solid var(--bento-border); border-radius: 6px; color: var(--bento-text); padding: 6px 10px; font-size: 12px; font-family: Inter, sans-serif; flex: 1; min-width: 80px; }
        .maint-days, .maint-icon { max-width: 100px; }
        .maint-input::placeholder { color: var(--bento-text-muted); }
        .maint-add-btn { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: Inter, sans-serif; white-space: nowrap; }
        #vwm-custom-form label { display:grid; gap:4px; font-size:12px !important; line-height:1.4; }
        #vwm-custom-form input { min-height:34px; font-size:12px !important; }
        @media (max-width: 520px) { #vwm-custom-form { grid-template-columns:1fr !important; } .device-body { align-items:flex-start; } }
        /* History */
        .current-session-card { background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); border-radius: 10px; padding: 10px 14px; margin-bottom: 10px; }
        .cs-title { font-size: 12px; font-weight: 700; color: #22c55e; margin-bottom: 6px; }
        .cs-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; color: var(--bento-text-secondary); }
        .session-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--bento-border); font-size: 12px; }
        .session-date { color: var(--bento-text-secondary); font-weight: 500; }
        .session-time { color: var(--bento-text-muted); font-size: 11px; }
        .session-stats { display: flex; gap: 8px; }
        .session-stat { background: var(--bento-primary-light); border-radius: 10px; padding: 2px 8px; font-size: 11px; color: var(--bento-text-secondary); }
        /* Stats */
        .stats-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; border-bottom: 1px solid var(--bento-border); }
        .stats-device { flex: 1; font-weight: 500; }
        .stats-status { font-size: 11px; }
        .stats-pct { font-weight: 700; font-size: 13px; width: 35px; text-align: right; }
        .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
        .stat-box { background: var(--bento-primary-light); border-radius: 10px; padding: 10px; text-align: center; }
        .stat-num { font-size: 20px; font-weight: 700; color: var(--bento-text); }
        .stat-label { font-size: 10px; color: var(--bento-text-muted); margin-top: 2px; }
        /* Discovered */
        .disc-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; border-bottom: 1px solid var(--bento-border); flex-wrap: wrap; }
        .disc-name { font-weight: 500; }
        .disc-id { color: var(--bento-text-muted); font-size: 10px; font-family: monospace; flex: 1; }
        .disc-state { font-size: 11px; font-weight: 600; }
        .disc-bat { font-size: 11px; color: var(--bento-text-secondary); }
        /* Battery */
        .battery-bar { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 2px 0; }
        .battery-icon { flex-shrink: 0; }
        .battery-track { flex: 1; height: 6px; background: rgba(59,130,246,0.12); border-radius: 3px; overflow: hidden; }
        .battery-fill { height: 100%; border-radius: 3px; transition: width 0.4s; }
        .battery-pct { font-weight: 700; font-size: 12px; width: 35px; text-align: right; }
        /* Empty */
        .empty-state { text-align: center; color: var(--bento-text-muted); padding: 20px; font-size: 13px; line-height: 1.5; }

/* Tips banner */
.tip-banner {
  background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(59,130,246,0.03));
  border: 1.5px solid rgba(59,130,246,0.2);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.6;
  position: relative;
}
.tip-banner-title { font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #3B82F6; }
.tip-banner ul { margin: 6px 0 0 16px; padding: 0; }
.tip-banner li { margin-bottom: 3px; }
.tip-banner .tip-dismiss {
  position: absolute; top: 8px; right: 10px;
  background: none; border: none; cursor: pointer;
  font-size: 16px; color: var(--secondary-text-color, #888); opacity: 0.6;
}
.tip-banner .tip-dismiss:hover { opacity: 1; }
.tip-banner.hidden { display: none; }

      

:host(.bento-dark) {
    --bento-bg: var(--primary-background-color, #1a1a2e);
    --bento-card: var(--card-background-color, #16213e);
    --bento-text: var(--primary-text-color, #e2e8f0);
    --bento-text-secondary: var(--secondary-text-color, #94a3b8);
    --bento-border: var(--divider-color, #334155);
    --bento-shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
    --bento-shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  }
/* === DARK MODE ADDED - old comment below === */


</style>
      <div class="card">
        <div class="card-title">${_esc(this._config.title)}</div>
        <div class="tip-banner" id="tip-banner">
          <button class="tip-dismiss" id="tip-dismiss" aria-label="Dismiss">\u2715</button>
          <div class="tip-banner-title">💡 Setup</div>
          <ul>
            <li><strong>Brand Profile</strong> - pick a profile (Roborock, Dreame, iRobot, Ecovacs) to auto-fill sensor names.</li>
            <li><strong>Required entities:</strong> vacuum.*. Water sensors and input_number are optional; without them the integration tracks the counter.</li>
            <li><strong>Multi-device</strong> - add multiple vacuums in config (the <code>devices</code> array).</li>
            <li><strong>Tabs:</strong> Water (water level), Consumables (brushes, filters), Stats (cleaning stats), History (session history).</li>
            <li><strong>Refill</strong> - resets the water-usage counter after you refill the tank.</li>
          </ul>
        </div>
        ${deviceTabsHtml}
        ${deviceHeader}
        ${tabNav}
        ${tabContent}

        ${ownDonateFooter()}

      
        </div>`;

    // Only update DOM if content actually changed
    if (_newHtml !== this._lastHtml) {
      this.shadowRoot.innerHTML = _newHtml;
      this._lastHtml = _newHtml;
      this._attachListeners(devices, device);
      this._restoreDraftState(draft);
    }
   } catch(err) {
    // Show error with tip banner
    const _newHtml = `
      <style>
        :host { display: block; }
        .err-container { max-width: 700px; margin: 30px auto; padding: 20px; }
        .err-card { background: var(--bento-error-light, rgba(239,68,68,0.05)); border: 1.5px solid rgba(239,68,68,0.2); border-radius: 12px; padding: 20px; margin-bottom: 20px; text-align: center; }
        .err-icon { font-size: 48px; margin-bottom: 10px; }
        .err-msg { font-size: 13px; color: var(--bento-text-muted, #888); margin-top: 8px; font-family: monospace; }
        .tip-banner { background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(59,130,246,0.03)); border: 1.5px solid rgba(59,130,246,0.2); border-radius: 12px; padding: 14px 16px; font-size: 13px; line-height: 1.6; }
        .tip-banner-title { font-weight: 700; font-size: 14px; margin-bottom: 6px; color: var(--bento-primary, #3B82F6); }
        .tip-banner ul { margin: 6px 0 0 16px; padding: 0; }
        .tip-banner li { margin-bottom: 3px; }
        </style>
      <div class="err-container">
        <div class="err-card">
          <div class="err-icon">\u26A0\uFE0F</div>
          <div><strong>Error:</strong> ${_esc(this._sanitize(err.message || 'Unknown error'))}</div>
          <div class="err-msg">Required entities or sensors are unavailable.</div>
        </div>
        <div class="tip-banner">
          <div class="tip-banner-title">💡 Setup</div>
          <ul>
            <li><strong>Brand Profile</strong> - pick a profile (Roborock, Dreame, iRobot, Ecovacs) to auto-fill sensor names.</li>
            <li><strong>Required entities:</strong> vacuum.*. Water sensors and input_number are optional; without them the integration tracks the counter.</li>
            <li><strong>Multi-device</strong> - add multiple vacuums in config (the <code>devices</code> array).</li>
            <li><strong>Tabs:</strong> Water (water level), Consumables (brushes, filters), Stats (cleaning stats), History (session history).</li>
            <li><strong>Refill</strong> - resets the water-usage counter after you refill the tank.</li>
          </ul>
        </div>
      </div>`;
    console.warn('[VacuumWaterMonitor] Render error:', err);
   }
  }

  _attachListeners(devices, device) {
    const sr = this.shadowRoot;
    // Tip banner dismiss
    const _tipB = this.shadowRoot.querySelector('#tip-banner');
    if (_tipB) {
      const _tipV = 'vacuum-water-monitor-tips-v3.0.0';
      if (localStorage.getItem(_tipV) === 'dismissed') {
        _tipB.classList.add('hidden');
      }
      const _tipDismiss = this.shadowRoot.querySelector('#tip-dismiss');
      if (_tipDismiss) {
        _tipDismiss.addEventListener('click', (e) => {
          e.stopPropagation();
          _tipB.classList.add('hidden');
          localStorage.setItem(_tipV, 'dismissed');
        });
      }
    }

    // Refill button — reset HA Store state for this vacuum.
    sr.querySelectorAll('.refill-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const vacuumId = btn.dataset.vacuum;
        const ok = () => {
          btn.textContent = '\u2705 Done!'; btn.style.color = '#22c55e';
          setTimeout(() => { btn.textContent = '\uD83D\uDCA7 Refilled'; btn.style.color = '#60a5fa'; }, 2000);
        };
        const fail = (err) => {
          console.error('[ha-vacuum-water-monitor] refill failed:', err);
          btn.textContent = '\u274C Error!'; btn.style.color = '#ef4444';
          setTimeout(() => { btn.textContent = '\uD83D\uDCA7 Refilled'; btn.style.color = '#60a5fa'; }, 3000);
        };
        if (vacuumId) {
          try {
            await this._resetWaterState({ vacuum_entity: vacuumId });
            ok();
            this._render();
          } catch (e) { fail(e); }
        } else {
          fail(new Error('No input and no vacuum id on button'));
        }
      });
    });

    // Tab navigation
    sr.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = btn.dataset.tab;
        history.replaceState(null, '', location.pathname + '#' + this._toolId + '/' + this._activeTab);
        try { localStorage.setItem('ha-tools-vacuum-water-monitor-settings', JSON.stringify({ _activeTab: this._activeTab, _activeDeviceIdx: this._activeDeviceIdx })); } catch(e) { console.debug('[ha-vacuum-water-monitor] caught:', e); }
        this._render();
      });
    });

    // Device tabs
    sr.querySelectorAll('.dtab').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeDeviceIdx = parseInt(btn.dataset.didx) || 0;
        try { localStorage.setItem('ha-tools-vacuum-water-monitor-settings', JSON.stringify({ _activeTab: this._activeTab, _activeDeviceIdx: this._activeDeviceIdx })); } catch(e) { console.debug('[ha-vacuum-water-monitor] caught:', e); }
        this._render();
      });
    });

    // Maintenance: add item
    const maintAddBtn = sr.querySelector('.maint-add-btn');
    if (maintAddBtn) {
      maintAddBtn.addEventListener('click', () => {
        const name = (sr.querySelector('#maint-name') || {}).value || '';
        const days = parseInt((sr.querySelector('#maint-days') || {}).value) || null;
        const icon = (sr.querySelector('#maint-icon') || {}).value || '\uD83D\uDD27';
        if (!name.trim()) return;
        this._maintenanceItems.push({ name: name.trim(), intervalDays: days, icon, lastDone: null });
        this._saveMaintenanceItems();
        this._render();
      });
    }

    // Maintenance: mark done
    sr.querySelectorAll('.maint-done-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx);
        if (this._maintenanceItems[idx]) {
          this._maintenanceItems[idx].lastDone = Date.now();
          this._saveMaintenanceItems();
          this._render();
        }
      });
    });

    // Maintenance: delete
    sr.querySelectorAll('.maint-del-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx);
        this._maintenanceItems.splice(idx, 1);
        this._saveMaintenanceItems();
        this._render();
      });
    });

    // History: log manual session
    const histLogBtn = sr.querySelector('#hist-log-btn');
    if (histLogBtn) {
      histLogBtn.addEventListener('click', () => {
        const area = (sr.querySelector('#hist-area') || {}).value || '';
        const water = (sr.querySelector('#hist-water') || {}).value || '';
        const duration = (sr.querySelector('#hist-duration') || {}).value || '';
        if (!area && !water && !duration) return;
        this._saveSession(device, { area, water, duration });
        this._render();
      });
    }

    // Refill methods toggle
    const calSave = sr.querySelector('#cal-save');
    if (calSave) calSave.addEventListener('click', () => this._saveLocalMeasurement(device));
    const shareOptIn = sr.querySelector('#vwm-share-optin');
    if (shareOptIn) shareOptIn.addEventListener('change', () => this._setCalibrationSharing(shareOptIn.checked));
    const shareCopy = sr.querySelector('#vwm-share-copy');
    if (shareCopy) shareCopy.addEventListener('click', async () => {
      const text = sr.querySelector('#vwm-share-payload')?.textContent || '';
      try { await navigator.clipboard.writeText(text); shareCopy.textContent = 'Copied'; } catch (e) { shareCopy.textContent = 'Select and copy the text above'; }
    });
    const calPreview = sr.querySelector('#cal-preview');
    if (calPreview) calPreview.addEventListener('click', () => this._previewCalibration(device));
    for (const id of ['cal-cycle', 'cal-observed', 'cal-resolution']) {
      sr.getElementById(id)?.addEventListener('input', () => {
        this._calibrationPreviewGeneration = (this._calibrationPreviewGeneration || 0) + 1;
        this._localMeasurementGeneration = (this._localMeasurementGeneration || 0) + 1;
        const localStatus = sr.getElementById('cal-local-status');
        if (localStatus) localStatus.textContent = '';
        if (id === 'cal-cycle') {
          const index = Number(sr.getElementById(id)?.value);
          const sessions = this._serverState?.tank_states?.[device?.vacuum_entity]?.automatic_sessions;
          const readiness = sr.getElementById('cal-readiness');
          if (readiness) readiness.textContent = this._measurementReadiness(Array.isArray(sessions) ? sessions[index] : null);
          for (const confirmId of ['cal-boundaries','cal-uninterrupted']) {
            const checkbox = sr.getElementById(confirmId); if (checkbox) checkbox.checked = false;
          }
        }
        const download = sr.getElementById('cal-download');
        if (download) download.disabled = true;
        const preview = sr.getElementById('cal-export-preview');
        if (preview) { preview.value = ''; preview.hidden = true; }
      });
    }

    const refillSave = sr.querySelector('#vwm-refill-save');
    if (refillSave) refillSave.addEventListener('click', () => this._saveRefillChoices(device));
    const refillLegacyRemove = sr.querySelector('#vwm-refill-legacy-remove');
    if (refillLegacyRemove) refillLegacyRemove.addEventListener('click', () => this._removeLegacyRefillAutomations(device));
    const btnCreate = sr.querySelector('#refill-btn-create');
    if (btnCreate) {
      btnCreate.addEventListener('click', async () => {
        btnCreate.textContent = '\u23F3 Creating...';
        const newId = await this._createRefillButton(device);
        if (newId) {
          btnCreate.textContent = '\u2705 Created';
          const select = sr.querySelector('#vwm-refill-button');
          if (select) {
            if (![...select.options].some(option => option.value === newId)) select.add(new Option(newId, newId));
            select.value = newId;
          }
          const status = sr.getElementById('vwm-refill-status');
          if (status) { status.textContent = 'Helper created. Press Save refill options to use it.'; status.style.color = 'var(--bento-text-secondary)'; }
        } else {
          btnCreate.textContent = '\u274C Error';
          setTimeout(() => { btnCreate.textContent = '+ Create input_button'; }, 2000);
        }
      });
    }

    // Signal mapping: manual entity assignment for roles auto-discovery could
    // not resolve (or resolved ambiguously). Stored per vacuum in the HA Store.
    const signalSave = sr.querySelector('#vwm-signal-save');
    if (signalSave) {
      signalSave.addEventListener('click', async () => {
        const status = sr.querySelector('#vwm-signal-status');
        const vacuumId = String(device?.vacuum_entity || '');
        if (!vacuumId) {
          if (status) status.innerHTML = '<span style="color:#ef4444">\u26A0\uFE0F No vacuum selected.</span>';
          return;
        }
        const all = { ...(this._serverState?.settings?.signal_overrides || {}) };
        const previous = all[vacuumId] && typeof all[vacuumId] === 'object' ? all[vacuumId] : {};
        const entry = { ...previous };
        // Compare against the raw backend descriptor, not `device.signals`:
        // the latter already has any stored override applied, so it would
        // always compare equal and no change could ever be saved.
        const descriptor = this._backendDescriptor(device);
        const autoSignals = descriptor?.signals && typeof descriptor.signals === 'object' ? descriptor.signals : {};
        const explicitKeys = this._explicitDeviceKeys(device);
        const ambiguousRoles = new Set((Array.isArray(device?.ambiguous_roles) ? device.ambiguous_roles : []).map(r => String(r)));
        sr.querySelectorAll('.vwm-signal-select').forEach(select => {
          const role = select.dataset.role;
          if (!role) return;
          const value = String(select.value || '').trim();
          // Baseline is what this role would resolve to with no override at
          // all: an authored YAML field where present, otherwise discovery.
          // Comparing against discovery alone would silently pin a YAML value
          // as an override and make later YAML edits stop taking effect.
          const baseline = explicitKeys.has(role)
            ? String(device?.[role] ?? '')
            : String(autoSignals[role] ?? '');
          // Only a genuine correction is stored, so confirming what discovery
          // already found does not pin the role and the device keeps
          // benefiting from future detection improvements. An ambiguous role
          // is the exception: there the confirmation is the point, and it also
          // clears the warning.
          if (value && (value !== baseline || ambiguousRoles.has(role))) entry[role] = value;
          else delete entry[role];
        });
        if (Object.keys(entry).length) all[vacuumId] = entry;
        else delete all[vacuumId];
        signalSave.disabled = true;
        signalSave.textContent = '\u23F3 Saving...';
        if (status) { status.textContent = 'Saving to Home Assistant\u2026'; status.style.color = 'var(--bento-text-secondary)'; }
        const result = await this._saveServerSettings({ signal_overrides: all });
        const currentSave = sr.querySelector('#vwm-signal-save');
        const currentStatus = sr.querySelector('#vwm-signal-status');
        if (currentSave) { currentSave.disabled = false; currentSave.textContent = '\uD83D\uDCBE Save signal mapping'; }
        if (!result.ok) {
          if (currentStatus) currentStatus.innerHTML = '<span style="color:#ef4444">\u274C Could not save signal mapping. Please try again.</span>';
          return;
        }
        if (currentStatus) currentStatus.innerHTML = '<span style="color:#22c55e">\u2705 Saved \u2014 signal mapping applied.</span>';
        setTimeout(() => this._render(), 1500);
      });
    }

    // Add manual vacuum
    const addManualBtn = sr.querySelector('#btn-add-manual-vacuum');
    if (addManualBtn) {
      addManualBtn.addEventListener('click', () => {
        const input = sr.querySelector('#manual-vacuum-entity');
        const entityId = (input && input.value || '').trim();
        if (!entityId) return;
        if (!entityId.startsWith('vacuum.')) {
          addManualBtn.textContent = '\u274C Musi zaczynac sie od vacuum.';
          addManualBtn.style.color = '#ef4444';
          setTimeout(() => { addManualBtn.textContent = '+ Dodaj'; addManualBtn.style.color = ''; }, 2000);
          return;
        }
        if (this._addUserDevice(entityId)) {
          addManualBtn.textContent = '\u2705 Dodano!';
          addManualBtn.style.color = '#22c55e';
          setTimeout(() => { addManualBtn.textContent = '+ Dodaj'; addManualBtn.style.color = ''; this._render(); }, 800);
        } else {
          addManualBtn.textContent = 'Juz dodany';
          setTimeout(() => { addManualBtn.textContent = '+ Dodaj'; addManualBtn.style.color = ''; }, 1500);
        }
      });
    }

    // Click discovered vacuum to add
    sr.querySelectorAll('.disc-add-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const entityId = btn.dataset.entity;
        if (this._addUserDevice(entityId)) {
          btn.textContent = '\u2705 Dodano!';
          btn.style.color = '#22c55e';
          setTimeout(() => this._render(), 800);
        }
      });
    });

    // Remove user-added device
    sr.querySelectorAll('.user-dev-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._removeUserDevice(btn.dataset.entity);
        this._render();
      });
    });

  }

  disconnectedCallback() {
    // Clear render scheduling flag to prevent orphaned setTimeout calls
    this._renderScheduled = false;
  }

  setActiveTab(tabId) {
    this._activeTab = tabId;
    this._render();
  }
}

if (!customElements.get('ha-vacuum-water-monitor')) customElements.define('ha-vacuum-water-monitor', HAVacuumWaterMonitor);
window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === 'ha-vacuum-water-monitor')) {
  window.customCards.push({
    type: 'ha-vacuum-water-monitor',
    name: 'Vacuum Water Monitor',
    description: 'Track water levels, maintenance schedule, cleaning history, and stats for robot vacuums. Multi-device, brand profiles, auto-discovery.',
    preview: true,
  });
}

class HaVacuumWaterMonitorEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
  }
  setConfig(config) {
    this._config = { ...config };
    // Load persisted UI state
    try {
      const _saved = localStorage.getItem('ha-tools-vacuum-water-monitor-settings');
      if (_saved) {
        const _s = JSON.parse(_saved);
        if (_s._activeTab) this._activeTab = _s._activeTab;
        if (_s._activeDeviceIdx !== undefined) this._activeDeviceIdx = _s._activeDeviceIdx;
      }
    } catch(e) { console.debug('[ha-vacuum-water-monitor] caught:', e); }
    this._render();
  }
  _dispatch() {
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config }, bubbles: true, composed: true }));
  }
  _render() {
    this.shadowRoot.innerHTML = `
      <style>
            :host { display:block; padding:16px; }
            h3 { margin:0 0 16px; font-size:15px; font-weight:600; color:var(--bento-text, var(--primary-text-color,#1e293b)); }
            input { outline:none; transition:border-color .2s; }
            input:focus { border-color:var(--bento-primary, var(--primary-color,#3b82f6)); }
        </style>
      <h3>Vacuum Water Monitor</h3>
            <div style="margin-bottom:12px;">
              <label style="display:block;font-weight:500;margin-bottom:4px;font-size:13px;">Title</label>
              <input type="text" id="cf_title" value="${_esc(this._config?.title || 'Vacuum Water Monitor')}"
                style="width:100%;padding:8px 12px;border:1px solid var(--divider-color,#e2e8f0);border-radius:8px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#1e293b);font-size:14px;box-sizing:border-box;">
            </div>
    `;
        const f_title = this.shadowRoot.querySelector('#cf_title');
        if (f_title) f_title.addEventListener('input', (e) => {
          this._config = { ...this._config, title: e.target.value };
          this._dispatch();
        });
  }
  connectedCallback() { this._render(); }
}
if (!customElements.get('ha-vacuum-water-monitor-editor')) { customElements.define('ha-vacuum-water-monitor-editor', HaVacuumWaterMonitorEditor); }

})();
