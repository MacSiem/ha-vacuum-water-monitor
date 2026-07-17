/* HA Vacuum Water Monitor v5.1.7 — HACS integration bundled card */
(function() {
'use strict';

// XSS protection helper (reuse global from panel, fallback for standalone)
const _esc = window._haToolsEsc || ((s) => typeof s === 'string' ? s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]) : (s ?? ''));

const VWM_DOMAIN = 'ha_vacuum_water_monitor';
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
    water_total_ml: 3000,
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
const DEFAULT_USAGE_PER_M2 = { fast: 4, standard: 6, deep: 9 };
// Default multiplier by mop_intensity (or mop_water_level)
const DEFAULT_INTENSITY_FACTOR = { low: 0.8, medium: 1.0, high: 1.2, max: 1.3, custom: 1.0, smart_mode: 1.0, custom_water_flow: 1.0 };
// Default volume (ml) consumed per wash event
const DEFAULT_WASH_VOLUME_ML = 150;
// Minimum area delta (m²) that triggers area-based dosing
const AREA_MIN_DELTA = 0.1;
// Minimum seconds between automatic resets (debounce)
const RESET_COOLDOWN_SEC = 60;

// Q1/Q2: Research-based calibration profiles per robot model
// Water usage (ml/m²) and cleaning efficiency data
const CALIBRATION_DATA = {
  'roborock_s8_maxv_ultra': {
    label: 'Roborock S8 MaxV Ultra',
    tank_ml: 3000,
    robot_tank_ml: 350,
    water_per_m2: { 'fast/low': 3.2, 'fast/med': 4.0, 'std/low': 4.8, 'std/med': 6.0, 'std/high': 7.2, 'deep/med': 9.0, 'deep/high': 10.8, 'deep/max': 11.7 },
    mop_wash_ml: 150,
    mop_wash_modes: { quick: 100, standard: 150, deep: 200 },
    mop_modes: { fast: 4, standard: 6, deep: 9 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2, max: 1.3 },
    avg_area_per_charge: 250,
    mop_type: 'VibraRise 3.0 dual spinning',
    notes: '3L dock, 350ml robot tank. Mop wash ~150ml/cycle. Auto-refill from dock. Data from HA sensors.',
  },
  'roborock_s8_pro_ultra': {
    label: 'Roborock S8 Pro Ultra',
    tank_ml: 3500,
    robot_tank_ml: 200,
    water_per_m2: { 'light/low': 3.0, 'light/med': 3.8, 'balanced/low': 4.5, 'balanced/med': 5.6, 'balanced/high': 6.7, 'deep/med': 8.4, 'deep/high': 10.1, 'deep/max': 10.9 },
    mop_wash_ml: 140,
    mop_wash_modes: { quick: 90, standard: 140, deep: 190 },
    mop_modes: { light: 3.8, balanced: 5.6, deep: 8.4 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2, max: 1.3 },
    avg_area_per_charge: 240,
    mop_type: 'VibraRise 2.0 sonic 3000rpm',
    notes: '3.5L/3L dock. 80°C wash. 200ml robot tank. Estimates based on S8 MaxV ratios.',
  },
  'roborock_s7_maxv_ultra': {
    label: 'Roborock S7 MaxV Ultra',
    tank_ml: 3000,
    robot_tank_ml: 200,    water_per_m2: { 'mild/low': 2.8, 'mild/med': 3.5, 'moderate/low': 4.2, 'moderate/med': 5.3, 'moderate/high': 6.3, 'intense/med': 7.9, 'intense/high': 9.5 },
    mop_wash_ml: 130,
    mop_wash_modes: { quick: 80, standard: 130, deep: 180 },
    mop_modes: { mild: 3.5, moderate: 5.3, intense: 7.9 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 200,
    mop_type: 'VibraRise sonic 3000rpm',
    notes: '3L/2.3L dock. Sonic mop vibration, 5mm mop lift.',
  },
  'roborock_s7_maxv': {
    label: 'Roborock S7 MaxV (bez stacji)',
    tank_ml: 200,
    robot_tank_ml: 200,
    water_per_m2: { 'mild': 3.5, 'moderate': 5.3, 'intense': 7.9 },
    mop_modes: { mild: 3.5, moderate: 5.3, intense: 7.9 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 200,
    mop_type: 'VibraRise sonic 3000rpm',
    notes: 'No dock - 200ml robot tank only. Manual refill.',
  },
  'roborock_s9_maxv': {
    label: 'Roborock S9 MaxV Ultra',
    tank_ml: 4000,
    robot_tank_ml: 100,
    water_per_m2: { 'fast/low': 3.2, 'fast/med': 4.0, 'std/low': 4.8, 'std/med': 6.0, 'std/high': 7.2, 'deep/med': 9.0, 'deep/high': 10.8, 'deep/max': 11.7 },
    mop_wash_ml: 160,
    mop_wash_modes: { quick: 100, standard: 160, deep: 220 },
    mop_modes: { fast: 4, standard: 6, deep: 9 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2, max: 1.3 },    avg_area_per_charge: 280,
    mop_type: 'VibraRise 4.0 sonic 4000rpm',
    notes: '4L dock. 4000/min vibration. 22000Pa suction. 18mm mop lift. Values extrapolated from S8 MaxV.',
  },
  'roborock_q_revo': {
    label: 'Roborock Q Revo',
    tank_ml: 5000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.0, 'medium': 7.0, 'high': 11.0 },
    mop_wash_ml: 160,
    mop_wash_modes: { quick: 110, standard: 160, deep: 220 },
    mop_modes: { low: 4.0, medium: 7.0, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 230,
    mop_type: 'Dual rotating 200rpm',
    notes: '5L/4.2L dock. 30 flow levels. 45°C drying. Rotating mops use more water.',
  },
  'roborock_q_revo_maxv': {
    label: 'Roborock Q Revo MaxV',
    tank_ml: 4000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.0, 'medium': 7.0, 'high': 11.0 },
    mop_wash_ml: 160,
    mop_wash_modes: { quick: 110, standard: 160, deep: 220 },
    mop_modes: { low: 4.0, medium: 7.0, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 240,
    mop_type: 'Dual rotating 200rpm',
    notes: '4L/3.5L dock. ReactiveAI 2.0. 30 levels. Rotating mops.',
  },  'roborock_q7_max': {
    label: 'Roborock Q7 Max / Q7 Max+',
    tank_ml: 350,
    robot_tank_ml: 350,
    water_per_m2: { 'low': 2.5, 'medium': 4.5, 'high': 7.0 },
    mop_modes: { low: 2.5, medium: 4.5, high: 7.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 180,
    mop_type: 'Gravity mop pad 300g',
    notes: '350ml tank, no water dock. 30 levels. Passive mop - less water.',
  },
  'roborock_q7': {
    label: 'Roborock Q7',
    tank_ml: 300,
    robot_tank_ml: 300,
    water_per_m2: { 'low': 2.5, 'medium': 4.5, 'high': 7.0 },
    mop_modes: { low: 2.5, medium: 4.5, high: 7.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 180,
    mop_type: 'Gravity mop pad',
    notes: '300ml tank. Passive mop, low water usage.',
  },
  'dreame_x40_ultra': {
    label: 'Dreame X40 Ultra',
    tank_ml: 4500,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.5, 'medium': 8.0, 'high': 12.0, 'deep': 16.0 },
    mop_wash_ml: 170,
    mop_wash_modes: { quick: 110, standard: 170, deep: 230 },    mop_modes: { low: 4.5, medium: 8.0, high: 12.0, deep: 16.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 280,
    mop_type: 'MopExtend rotating dual pads',
    notes: '4.5L/4L dock. 70°C wash. 32 humidity levels. Extending edge mop.',
  },
  'dreame_x30_ultra': {
    label: 'Dreame X30 Ultra',
    tank_ml: 4500,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.5, 'medium': 8.0, 'high': 12.0, 'deep': 16.0 },
    mop_wash_ml: 150,
    mop_wash_modes: { quick: 100, standard: 150, deep: 200 },
    mop_modes: { low: 4.5, medium: 8.0, high: 12.0, deep: 16.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 243,
    mop_type: 'MopExtend RoboSwing rotating dual pads',
    notes: '4.5L/4L dock. 60°C wash. 40mm mop. ~130ml/100sqft per Smart Home Hookup.',
  },
  'dreame_l20_ultra': {
    label: 'Dreame L20 Ultra',
    tank_ml: 4500,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.5, 'medium': 8.0, 'high': 12.0, 'deep': 16.0 },
    mop_wash_ml: 160,
    mop_wash_modes: { quick: 100, standard: 160, deep: 210 },
    mop_modes: { low: 4.5, medium: 8.0, high: 12.0, deep: 16.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },    avg_area_per_charge: 300,
    mop_type: 'MopExtend rotating dual pads',
    notes: '4.5L/4L dock. Hot-air drying. Extending mop. 300m²/charge.',
  },
  'dreame_l10s_ultra': {
    label: 'Dreame L10s Ultra',
    tank_ml: 2500,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.0, 'medium': 7.5, 'high': 11.0 },
    mop_wash_ml: 140,
    mop_wash_modes: { quick: 90, standard: 140, deep: 190 },
    mop_modes: { low: 4.0, medium: 7.5, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 210,
    mop_type: 'Dual rotating 180rpm',
    notes: '2.5L/2.4L dock. >250ml/100sqft per Smart Home Hookup. Rotating mops 180rpm.',
  },
  'dreame_l10s_pro_ultra': {
    label: 'Dreame L10s Pro Ultra',
    tank_ml: 4500,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.0, 'medium': 7.5, 'high': 11.0 },
    mop_wash_ml: 150,
    mop_wash_modes: { quick: 100, standard: 150, deep: 200 },
    mop_modes: { low: 4.0, medium: 7.5, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 230,
    mop_type: 'Dual rotating pads',
    notes: '4.5L/4L dock. 58°C wash. Improved L10s Ultra.',
  },  'dreame_d10_plus': {
    label: 'Dreame D10 Plus',
    tank_ml: 150,
    robot_tank_ml: 150,
    water_per_m2: { 'low': 2.0, 'medium': 4.0, 'high': 6.0 },
    mop_modes: { low: 2.0, medium: 4.0, high: 6.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 120,
    mop_type: 'Single rotating pad',
    notes: 'Budget. 150ml, no water dock. 3 levels. 6000Pa suction.',
  },
  'ecovacs_x2_omni': {
    label: 'Ecovacs Deebot X2 Omni',
    tank_ml: 4000,
    robot_tank_ml: 180,
    water_per_m2: { 'low': 4.5, 'medium': 8.0, 'high': 12.5 },
    mop_wash_ml: 170,
    mop_wash_modes: { quick: 110, standard: 170, deep: 230 },
    mop_modes: { low: 4.5, medium: 8.0, high: 12.5 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 260,
    mop_type: 'OZMO Turbo 2.0 rotating 180rpm',
    notes: '4L/3.5L dock. 55°C wash. Square design. 6N pressure. ~400ml/100sqft max per TSHHU.',
  },
  'ecovacs_t20_omni': {
    label: 'Ecovacs Deebot T20 Omni',
    tank_ml: 4000,
    robot_tank_ml: 180,
    water_per_m2: { 'low': 4.0, 'medium': 7.5, 'high': 11.5, 'deep': 15.0 },    mop_wash_ml: 160,
    mop_wash_modes: { quick: 100, standard: 160, deep: 210 },
    mop_modes: { low: 4.0, medium: 7.5, high: 11.5, deep: 15.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 240,
    mop_type: 'OZMO Turbo spinning 180rpm',
    notes: '4L/4L dock. 60°C wash. 4 modes.',
  },
  'ecovacs_t30_omni': {
    label: 'Ecovacs Deebot T30S Omni',
    tank_ml: 4000,
    robot_tank_ml: 55,
    water_per_m2: { 'low': 4.5, 'medium': 8.0, 'high': 12.5, 'deep': 16.0 },
    mop_wash_ml: 170,
    mop_wash_modes: { quick: 110, standard: 170, deep: 230 },
    mop_modes: { low: 4.5, medium: 8.0, high: 12.5, deep: 16.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 250,
    mop_type: 'Dual spin mops 180rpm',
    notes: '4L/4L dock. 70°C wash. 55ml robot continuous refill. Auto-detergent.',
  },
  'ecovacs_n20_plus': {
    label: 'Ecovacs Deebot N20 Plus',
    tank_ml: 220,
    robot_tank_ml: 220,
    water_per_m2: { 'low': 2.0, 'medium': 3.5, 'high': 5.5 },
    mop_modes: { low: 2.0, medium: 3.5, high: 5.5 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 120,    mop_type: 'OZMO fixed pad (no lift)',
    notes: 'Budget. 220ml, no mop wash. Manual removal for carpets.',
  },
  'irobot_combo_j9': {
    label: 'iRobot Roomba Combo j9+',
    tank_ml: 3000,
    robot_tank_ml: 210,
    water_per_m2: { 'low': 2.0, 'medium': 4.0, 'high': 7.0 },
    mop_modes: { low: 2.0, medium: 4.0, high: 7.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 150,
    mop_type: 'SmartScrub retractable microfiber',
    notes: '3L auto-refill dock. Mop lifts up. D.R.I. carpets. 3 levels.',
  },
  'irobot_combo_j7': {
    label: 'iRobot Roomba Combo j7+',
    tank_ml: 210,
    robot_tank_ml: 210,
    water_per_m2: { 'low': 2.0, 'medium': 4.0, 'high': 7.0 },
    mop_modes: { low: 2.0, medium: 4.0, high: 7.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 140,
    mop_type: 'Retractable microfiber pad',
    notes: '210ml tank. Mop lifts up. Electronic pump. Bona support.',
  },
  'irobot_combo_essential': {
    label: 'iRobot Roomba Combo Essential',
    tank_ml: 200,
    robot_tank_ml: 200,    water_per_m2: { 'low': 1.5, 'medium': 3.0, 'high': 5.0 },
    mop_modes: { low: 1.5, medium: 3.0, high: 5.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 46,
    mop_type: 'Fixed microfiber pad (drag)',
    notes: 'Budget. 200ml, no mop lift. ~46m²/tank. 3 levels.',
  },
  'narwal_freo_x_ultra': {
    label: 'Narwal Freo X Ultra',
    tank_ml: 5000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 5.0, 'medium': 9.0, 'high': 14.0 },
    mop_wash_ml: 210,
    mop_wash_modes: { quick: 140, standard: 210, deep: 280 },
    mop_modes: { low: 5.0, medium: 9.0, high: 14.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 250,
    mop_type: 'Dual rotating pads',
    notes: '5L/4.5L dock. ~210ml/mop wash per TSHHU. Highest water usage in class.',
  },
  'narwal_freo_x_plus': {
    label: 'Narwal Freo X Plus',
    tank_ml: 280,
    robot_tank_ml: 280,
    water_per_m2: { 'low': 4.0, 'medium': 7.0, 'high': 11.0 },
    mop_modes: { low: 4.0, medium: 7.0, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 200,    mop_type: 'Dual rotating pads',
    notes: 'Compact base, no dock wash. 280ml tank. 450m² range.',
  },
  'eufy_x10_pro_omni': {
    label: 'Eufy X10 Pro Omni',
    tank_ml: 3000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 3.5, 'medium': 6.5, 'high': 10.0 },
    mop_wash_ml: 140,
    mop_wash_modes: { quick: 90, standard: 140, deep: 190 },
    mop_modes: { low: 3.5, medium: 6.5, high: 10.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 180,
    mop_type: 'MopMaster 2.0 pentagon dual 180rpm',
    notes: '3L dock. 1kg pressure. 45°C drying. 188ml/100sqft max per TSHHU.',
  },
  'samsung_jet_bot_combo': {
    label: 'Samsung Jet Bot Combo AI',
    tank_ml: 4000,
    robot_tank_ml: 100,
    water_per_m2: { 'low': 4.0, 'medium': 7.0, 'high': 11.0 },
    mop_wash_ml: 160,
    mop_wash_modes: { quick: 100, standard: 160, deep: 210 },
    mop_modes: { low: 4.0, medium: 7.0, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 200,
    mop_type: 'Dual spin mops',
    notes: '4L/3.6L dock. Auto-steam 70°C+. Samsung AI.',
  },  'xiaomi_x20_max': {
    label: 'Xiaomi Robot Vacuum X20 Max',
    tank_ml: 4000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 4.0, 'medium': 7.0, 'high': 11.0 },
    mop_wash_ml: 150,
    mop_wash_modes: { quick: 100, standard: 150, deep: 200 },
    mop_modes: { low: 4.0, medium: 7.0, high: 11.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 200,
    mop_type: 'Rotating dual pads, hot wash',
    notes: '4L/3.8L dock. Hot water. 2 output levels. 200m².',
  },
  'xiaomi_x20_pro': {
    label: 'Xiaomi Robot Vacuum X20 Pro',
    tank_ml: 4000,
    robot_tank_ml: 80,
    water_per_m2: { 'low': 3.5, 'medium': 6.5, 'high': 10.0 },
    mop_wash_ml: 140,
    mop_wash_modes: { quick: 90, standard: 140, deep: 190 },
    mop_modes: { low: 3.5, medium: 6.5, high: 10.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 120,
    mop_type: 'Rotating dual pads, hot wash',
    notes: '4L dock. 3 humidity levels. 120m² mopping.',
  },
  'generic': {
    label: 'Generic / Nieznany model',
    tank_ml: 300,    robot_tank_ml: 300,
    water_per_m2: { 'low': 3.0, 'medium': 6.0, 'high': 10.0 },
    mop_modes: { low: 3.0, medium: 6.0, high: 10.0 },
    intensity_factors: { low: 0.8, medium: 1.0, high: 1.2 },
    avg_area_per_charge: 150,
    mop_type: 'Standard',
    notes: 'Default estimates - adjust for your model.',
  },
};


/* ===== HA Tools split — inline shared infrastructure ===== */
// Bento Design System CSS (inline copy — keeps tool standalone)
if (typeof window !== 'undefined' && !window.HAToolsBentoCSS) {
  window.HAToolsBentoCSS = `
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
  font-size: 12px; font-weight: 700; color: var(--bento-text-secondary);
  text-transform: uppercase; letter-spacing: 0.08em;
  margin: 16px 0 10px;
}
.section-header::before, .section-title::before {
  content: ""; width: 4px; height: 4px; border-radius: 50%; background: var(--bento-primary);
  margin-right: 8px; flex-shrink: 0;
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
}
// XSS escape singleton (idempotent)
if (typeof window !== 'undefined') {
  window._haToolsEsc = window._haToolsEsc || (function(){
    var MAP = {};
    MAP[String.fromCharCode(38)] = '&amp;';
    MAP[String.fromCharCode(60)] = '&lt;';
    MAP[String.fromCharCode(62)] = '&gt;';
    MAP[String.fromCharCode(34)] = '&quot;';
    MAP[String.fromCharCode(39)] = '&#39;';
    return function(s){ return typeof s === 'string' ? s.replace(/[&<>"']/g, function(c){ return MAP[c]; }) : (s == null ? '' : s); };
  })();
}
// Universal donate footer injector — guarantees the support box appears
// on every split-tool card regardless of internal render state.
if (typeof window !== 'undefined' && !window.__haToolsSplitDonateInjector) {
  window.__haToolsSplitDonateInjector = true;
  var SPLIT_TAGS = ['ha-purge-cache','ha-yaml-checker','ha-data-exporter','ha-baby-tracker','ha-chore-tracker','ha-energy-optimizer','ha-energy-insights','ha-energy-email','ha-log-email','ha-smart-reports','ha-network-map','ha-trace-viewer','ha-automation-analyzer','ha-storage-monitor','ha-backup-manager','ha-security-check','ha-device-health','ha-sentence-manager','ha-encoding-fixer','ha-entity-renamer','ha-frigate-privacy','ha-vacuum-water-monitor'];
  var DONATE_HTML = ''
    + '<div class="donate-section" data-source="ha-tools-split-injector">'
    + '  <div class="donate-text">'
    + '    <h3>❤️ Support HA Tools Development</h3>'
    + '    <p>If this tool makes your Home Assistant life easier, consider supporting the project. Every coffee motivates further development!</p>'
    + '  </div>'
    + '  <div class="donate-buttons">'
    + '    <a class="donate-btn coffee" href="https://buymeacoffee.com/macsiem" target="_blank" rel="noopener noreferrer">☕ Buy Me a Coffee</a>'
    + '    <a class="donate-btn paypal" href="https://www.paypal.com/donate/?hosted_button_id=Y967H4PLRBN8W" target="_blank" rel="noopener noreferrer">💳 PayPal</a>'
    + '  </div>'
    + '</div>';
  function deepFindAll(tag, root) {
    var out = [];
    (function walk(node){
      if (!node || !node.querySelectorAll) return;
      var children = node.querySelectorAll('*');
      for (var i = 0; i < children.length; i++) {
        var c = children[i];
        if (c.tagName && c.tagName.toLowerCase() === tag) out.push(c);
        if (c.shadowRoot) walk(c.shadowRoot);
      }
    })(root || document);
    return out;
  }
  // Per-tool prerequisite check + inline install banner
  var PREREQS = {
    'ha-energy-email': { service: 'ha_tools_email', repo: 'ha-tools-email-integration', label: 'HA Tools Email integration', kind: 'integration' },
    'ha-log-email':    { service: 'ha_tools_email', repo: 'ha-tools-email-integration', label: 'HA Tools Email integration', kind: 'integration' },
    'ha-encoding-fixer': { shellCommand: 'fix_encoding', label: 'shell_command.fix_encoding (optional advanced feature)', kind: 'shell_command_optional' }
  };
  // Per-tool first-run intro banner (one-line scope + 3 use cases)
  var INTROS = {
    'ha-yaml-checker': { headline: 'Validate Home Assistant YAML configuration on demand.', steps: ['Click \'Check HA Configuration\' to run homeassistant.check_config.', 'Switch to \'Encje\' tab to search entities by domain.', 'Use \'Template\' tab to preview Jinja2 templates.'] },
    'ha-data-exporter': { headline: 'Browse, filter, and export Home Assistant entity data.', steps: ['Filter by domain or search entities live.', 'Take a snapshot or export selection to CSV / JSON.', 'Privacy warning before downloading attributes with sensitive data.'] },
    'ha-chore-tracker': { headline: 'Household chore tracker with kanban + recurring schedules.', steps: ['Add a chore: name + assignee + frequency.', 'Drag from \'Todo\' to \'Done\' to mark complete.', 'Stats tab shows counts per assignee.'] },
    'ha-energy-optimizer': { headline: 'Tariff-aware energy usage with hourly heatmaps + tips.', steps: ['Today / Yesterday / 7-day / 30-day usage and cost.', 'Patterns tab — hourly heatmap of consumption.', 'Recommendations tab — auto-generated tips.'] },
    'ha-energy-insights': { headline: 'Daily / weekly / monthly energy charts + top consumers.', steps: ['Switch view tabs to see consumption over time.', 'Top devices ranked by kWh.', 'Tips tab with energy-saving suggestions.'] },
    'ha-energy-email': { headline: 'Energy reports delivered by email via ha_tools_email.', steps: ['Click \'Send Now\' to email the current snapshot.', 'Schedule daily / weekly / monthly delivery.', 'Configure SMTP in the Schedule tab (one-time).'] },
    'ha-log-email': { headline: 'Daily error / warning digests delivered by email.', steps: ['Click \'Send Now\' to email the current digest.', 'Schedule daily delivery + threshold (e.g. \u22653 errors).', 'Requires ha-tools-email-integration.'] },
    'ha-smart-reports': { headline: 'Aggregate weekly / monthly reports — energy + automations + state changes.', steps: ['Weekly summary card on Overview.', 'Drill down by Energy / Automations / System sub-tabs.', 'Privacy-safe view strips entity names before sharing.'] },
    'ha-network-map': { headline: 'Visualise the network around HA — devices, topology, MAC bindings.', steps: ['Devices tab — table of all known devices.', 'Topology tab — graph view of the network.', 'Click \'Rescan\' to ping the local subnet (user-initiated).'] },
    'ha-trace-viewer': { headline: 'Step through HA automation traces with a flow graph.', steps: ['Pick automation in sidebar to see latest 5 traces.', 'Click trace for full path through triggers / conditions / actions.', 'Export trace as JSON for offline debug.'] },
    'ha-automation-analyzer': { headline: 'Surface slow / failing / suspicious automations.', steps: ['Overview shows total + health score + top failing.', 'Performance tab ranks by avg runtime.', 'Optimization tab suggests improvements (loops, redundant triggers).'] },
    'ha-storage-monitor': { headline: 'Disk + recorder DB + add-on storage breakdown.', steps: ['Overview shows used / free + per-category breakdown.', 'Backups tab — count + size warning.', 'Cleanup tab — actionable suggestions.'] },
    'ha-backup-manager': { headline: 'Create + list + inspect HA backups.', steps: ['List existing backups (date / size / encryption).', 'Click \'Create backup now\' to invoke backup.create.', 'Restore selected backup.'] },
    'ha-security-check': { headline: 'Security audit + remediation tips.', steps: ['Overview shows score (X/100) + letter grade.', 'Click warning row for step-by-step remediation.', 'Tips tab — checklist of best practices.'] },
    'ha-device-health': { headline: 'Device battery / signal / last-seen health.', steps: ['List devices grouped by health (OK / Warning / Critical).', 'Filter by low battery (<20%) or weak signal.', 'Click device for model / manufacturer / last seen.'] },
    'ha-encoding-fixer': { headline: 'Detect + fix UTF-8 / mojibake issues across HA.', steps: ['Click \'Scan\' to walk entity registry + states.', 'Per-entity \'Fix\' button calls homeassistant.reload.', 'Optional: deep file scan via shell_command (see README).'] },
    'ha-entity-renamer': { headline: 'Bulk-rename HA entities + friendly names.', steps: ['Pick an entity, set new ID — entity_registry/update.', 'Bulk pattern: sensor.old_* \u2192 sensor.new_*.', 'Optional: rewrite Lovelace dashboard refs.'] },
    'ha-frigate-privacy': { headline: 'One-click Frigate privacy mode (pause detection / recording / snapshots).', steps: ['Click \'Pause 15 min\' for instant privacy.', 'Schedules tab — daily privacy window (e.g. 22:00\u201306:00).', 'Resume at any time to re-enable cameras.'] }
  };
  var PREREQ_HTML_CACHE = {};
  function buildPrereqBanner(tag, prereq, hass) {
    if (PREREQ_HTML_CACHE[tag]) return PREREQ_HTML_CACHE[tag];
    var html = '';
    if (prereq.kind === 'integration') {
      html = '<div class="prereq-banner prereq-error" data-prereq="' + tag + '">' +
        '<div class="prereq-icon">⚠️</div>' +
        '<div class="prereq-text">' +
          '<strong>This tool requires the ' + prereq.label + '</strong><br>' +
          'Install it from HACS: <code>https://github.com/MacSiem/' + prereq.repo + '</code> ' +
          '(Category: <strong>Integration</strong>) — then add <code>' + prereq.service + ':</code> to your <code>configuration.yaml</code> and restart HA.' +
        '</div>' +
        '<a class="prereq-cta" href="https://github.com/MacSiem/' + prereq.repo + '" target="_blank" rel="noopener noreferrer">Open install guide ↗</a>' +
      '</div>';
    } else if (prereq.kind === 'shell_command_optional') {
      html = '<div class="prereq-banner prereq-info" data-prereq="' + tag + '">' +
        '<div class="prereq-icon">💡</div>' +
        '<div class="prereq-text">' +
          '<strong>Optional advanced feature: deep file scan</strong><br>' +
          'To enable scanning of <code>configuration.yaml</code> files, install the bundled <code>encoding_scanner.py</code> + add <code>shell_command:</code> entries. See README.' +
        '</div>' +
      '</div>';
    }
    PREREQ_HTML_CACHE[tag] = html;
    return html;
  }
  function buildIntroBanner(tag, intro) {
    var stepsHtml = intro.steps.map(function(s){ return '<li>' + s + '</li>'; }).join('');
    return '<div class="intro-banner" data-intro="' + tag + '">' +
      '<button class="intro-dismiss" type="button" title="Dismiss" aria-label="Dismiss">✕</button>' +
      '<div class="intro-headline">💡 ' + intro.headline + '</div>' +
      '<ol class="intro-steps">' + stepsHtml + '</ol>' +
    '</div>';
  }
  function introDismissed(tag, el) {
    try {
      if (el && el._serverState && el._serverState.settings && el._serverState.settings.intro_dismissed) {
        return el._serverState.settings.intro_dismissed[tag] === true;
      }
      return localStorage.getItem('ha-intro-dismissed-' + tag) === '1';
    } catch(e) { return false; }
  }
  function dismissIntro(tag, el) {
    try { localStorage.setItem('ha-intro-dismissed-' + tag, '1'); } catch(e) {}
    try {
      if (el && el._hass) el._hass.callWS({ type: VWM_DOMAIN + '/dismiss_intro', tag: tag });
    } catch(e) {}
    var node = el.shadowRoot && el.shadowRoot.querySelector('.intro-banner[data-intro="' + tag + '"]');
    if (node) node.remove();
  }
  function injectAll() {
    SPLIT_TAGS.forEach(function(tag){
      deepFindAll(tag).forEach(function(el){
        // panel_custom auto-init: HA assigns hass/panel/narrow but does not always call setConfig.
        if (typeof el.setConfig === 'function' && !el.config && !el._config) {
          try { el.setConfig({ type: 'custom:' + tag, title: tag }); } catch(e) {}
        }
        if (!el.shadowRoot) return;
        // 0) First-run intro banner (skip if tool has its own native tip)
        var intro = INTROS[tag];
        if (intro && !introDismissed(tag, el)) {
          var hasOwnTip = el.shadowRoot.querySelector('#tip-banner, .tip-banner');
          var injectedIntro = el.shadowRoot.querySelector('.intro-banner[data-intro="' + tag + '"]');
          if (!hasOwnTip && !injectedIntro) {
            try {
              var _introTmp = document.createElement('div');
              _introTmp.innerHTML = buildIntroBanner(tag, intro);
              var _introNode = _introTmp.firstElementChild;
              if (_introNode) el.shadowRoot.insertBefore(_introNode, el.shadowRoot.firstChild);
              var btn = el.shadowRoot.querySelector('.intro-banner[data-intro="' + tag + '"] .intro-dismiss');
              if (btn) btn.addEventListener('click', function(ev){ ev.stopPropagation(); dismissIntro(tag, el); });
            } catch(e) {}
          }
        }
        // 1) Prereq banner — checked every poll so it disappears when prereq becomes available
        var prereq = PREREQS[tag];
        if (prereq && el._hass) {
          var hassReady = !!el._hass;
          var present = true;
          if (prereq.service) present = !!(el._hass.services && el._hass.services[prereq.service]);
          if (prereq.shellCommand) present = !!(el._hass.services && el._hass.services.shell_command && el._hass.services.shell_command[prereq.shellCommand]);
          var existing = el.shadowRoot.querySelector('.prereq-banner[data-prereq="' + tag + '"]');
          if (!present && hassReady) {
            if (!existing) {
              try {
                var _prereqTmp = document.createElement('div');
                _prereqTmp.innerHTML = buildPrereqBanner(tag, prereq, el._hass);
                var _prereqNode = _prereqTmp.firstElementChild;
                if (_prereqNode) el.shadowRoot.insertBefore(_prereqNode, el.shadowRoot.firstChild);
              } catch(e) {}
            }
          } else if (present && existing) {
            existing.remove();
          }
        }
        // 2) Donate footer
        if (el.shadowRoot.querySelector('.donate-section')) return;
        try {
          var _donateTmp = document.createElement('div');
          _donateTmp.innerHTML = DONATE_HTML;
          while (_donateTmp.firstChild) el.shadowRoot.appendChild(_donateTmp.firstChild);
        } catch(e) {}
      });
    });
  }
  // Run immediately, then aggressive MutationObserver for late mounts + view switches.
  injectAll();
  setTimeout(injectAll, 250);
  setTimeout(injectAll, 1000);
  setTimeout(injectAll, 3000);
  // MutationObserver catches every new node anywhere in the DOM, including shadow root attachments
  // that are deferred until the user navigates to a view.
  try {
    var obs = new MutationObserver(function(muts){
      // Debounce: schedule a microtask injection
      if (window.__haToolsDonateScheduled) return;
      window.__haToolsDonateScheduled = true;
      setTimeout(function(){ window.__haToolsDonateScheduled = false; injectAll(); }, 100);
    });
    obs.observe(document.body, { childList: true, subtree: true });
  } catch(e) {}
  // Also re-inject on hash/path change (Lovelace view switches)
  window.addEventListener('hashchange', function(){ setTimeout(injectAll, 200); });
  window.addEventListener('popstate', function(){ setTimeout(injectAll, 200); });
  // Backup interval (every 3s for first 5min — handles cases where MutationObserver missed events)
  var pollCount = 0;
  var pollInterval = setInterval(function(){
    injectAll();
    if (++pollCount >= 100) clearInterval(pollInterval);
  }, 3000);
}
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
          this._render();
          this._lastRenderTime = Date.now();
        }, 10000 - (now - this._lastRenderTime));
      }
      return;
    }
    this._firstRender = false;
    this._lastHassSig = sig;
    this._render();
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

    // Apply brand profile if specified
    let profile = {};
    if (config.brand_profile && BRAND_PROFILES[config.brand_profile]) {
      profile = { ...BRAND_PROFILES[config.brand_profile] };
      // Profile defaults must never invent an entity id — only the user's
      // explicit config or live discovery may name a vacuum_entity. A leaked
      // profile default used to create a ghost "Vacuum" device (issue #1).
      delete profile.vacuum_entity;
    }

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
      // Merge profile + explicit config (explicit wins)
      ...profile,
      ...config,
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
        this._render();
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
        this._serverState.tank_states = {
          ...(this._serverState.tank_states || {}),
          ...data.tank_states,
        };
      }
      this._lastHtml = '';
      this._render();
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
    this._customCalib = custom[this._config?.brand_profile || 'default'] || null;
    if (settings.warning_threshold && this._config.warning_threshold == null) this._config.warning_threshold = settings.warning_threshold;
    if (settings.critical_threshold && this._config.critical_threshold == null) this._config.critical_threshold = settings.critical_threshold;
  }

  async _saveServerSettings(patch) {
    if (!this._hass) return;
    try {
      const result = await this._hass.callWS({ type: `${VWM_DOMAIN}/set_settings`, patch });
      if (result && result.settings) {
        this._serverState.settings = result.settings;
        this._applyServerSettings();
      }
    } catch (err) {
      console.error('[ha-vacuum-water-monitor] settings save failed:', err);
    }
  }

  _sanitize(s) { try { return decodeURIComponent(escape(s)); } catch(e) { return s; } }

  _configuredDevicesFromConfig() {
    if (!this._config) return [];
    if (this._config.devices && Array.isArray(this._config.devices)) {
      return this._config.devices.map(d => {
        if (d.brand_profile && BRAND_PROFILES[d.brand_profile]) {
          return { ...BRAND_PROFILES[d.brand_profile], ...d };
        }
        return d;
      });
    }
    const single = {};
    const keys = [
      'device_name','water_sensor','water_used_sensor','water_used_input','water_total_ml',
      'vacuum_entity','dock_error_sensor','filter_sensor','last_session_sensor',
      'last_reset_entity','main_brush_sensor','side_brush_sensor','filter_time_sensor',
      'sensor_dirty_sensor','dock_brush_sensor','dock_strainer_sensor',
      'dock_clean_water_sensor','dock_dirty_water_sensor','water_shortage_sensor',
      'mop_attached_sensor','mop_drying_sensor','area_sensor','duration_sensor',
      'last_clean_start','last_clean_end','charge_sensor','status_sensor',
      'reset_door_sensor','mop_mode_entity','mop_intensity_entity','usage_ml_per_m2',
      'intensity_factor','wash_volume_ml','icon',
    ];
    keys.forEach(k => { if (this._config[k] != null) single[k] = this._config[k]; });
    if (!Object.keys(single).length || !single.vacuum_entity) return [];
    single.name = single.device_name || this._config.device_name || 'Vacuum';
    return [single];
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
    // Try to match a brand profile. v5.0.4: fuzzy match by model suffix so
    // renamed entities (e.g. `vacuum.s8_maxv_ultra`, `vacuum.salon_q_revo`)
    // still pick up the right defaults. We override `vacuum_entity` after the
    // spread so the merged profile reflects the user's actual entity_id.
    let profile = {};
    for (const [key, bp] of Object.entries(BRAND_PROFILES)) {
      if (!bp.vacuum_entity) continue;
      if (entityId === bp.vacuum_entity) { profile = { ...bp, brand_profile: key }; break; }
      const modelSuffix = bp.vacuum_entity.replace(/^vacuum\./, '');
      if (modelSuffix && (entityId.endsWith('_' + modelSuffix) || entityId.endsWith('.' + modelSuffix))) {
        profile = { ...bp, brand_profile: key };
        break;
      }
    }
    this._userDevices.push({
      vacuum_entity: entityId,
      name: profile.label || name,
      icon: profile.icon || '\uD83E\uDD16',
      ...profile,
      vacuum_entity: entityId, // ensure user's actual entity_id wins over profile default
    });
    this._saveUserDevices();
    return true;
  }

  _removeUserDevice(entityId) {
    this._userDevices = this._userDevices.filter(d => d.vacuum_entity !== entityId);
    this._saveUserDevices();
  }

  _upsertUserDevicePatch(device, patch) {
    const entityId = device && device.vacuum_entity;
    if (!entityId) return;
    const idx = this._userDevices.findIndex(d => d.vacuum_entity === entityId);
    if (idx >= 0) {
      this._userDevices[idx] = { ...this._userDevices[idx], ...patch };
    } else {
      this._userDevices.push({
        vacuum_entity: entityId,
        name: device.name || entityId,
        icon: device.icon || '\uD83E\uDD16',
        brand_profile: device.brand_profile || null,
        ...patch,
      });
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
    return { used_ml: 0, last_reset_iso: null, last_status: null, last_area: null, last_dock_err: null, last_door: null, last_reset_ts: 0 };
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
    return state.last_reset_iso;
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
      .filter(s => s.entity_id.startsWith('input_button.'))
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

  // Create automation via HA API
  async _createRefillAutomation(device, method, triggerEntity) {
    const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
    const inputNum = device.water_used_input || `input_number.${shortId}_water_used_ml`;
    const inputDt = device.last_reset_entity || `input_datetime.${shortId}_last_water_reset`;
    const autoId = `vwm_refill_${shortId}_${method}`;

    let trigger, conditions = [];
    if (method === 'button') {
      trigger = [{ platform: 'state', entity_id: triggerEntity }];
    } else {
      trigger = [{ platform: 'state', entity_id: triggerEntity, from: 'on', to: 'off' }];
      if (device.vacuum_entity) {
        conditions = [{ condition: 'state', entity_id: device.vacuum_entity, state: 'docked' }];
      }
    }

    const actions = [];
    if (method === 'sensor') actions.push({ delay: '00:00:05' });

    // Reset water counter
    const hasInputNum = this._hass.states[inputNum];
    if (hasInputNum) {
      actions.push({ service: 'input_number.set_value', target: { entity_id: inputNum }, data: { value: 0 } });
    }
    const hasInputDt = this._hass.states[inputDt];
    if (hasInputDt) {
      actions.push({ service: 'input_datetime.set_datetime', target: { entity_id: inputDt }, data: { datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}" } });
    }
    actions.push({
      service: 'persistent_notification.create',
      data: { title: '\uD83D\uDCA7 Water tank', message: `${shortId}: Water counter reset (${method}).` }
    });

    try {
      await this._hass.callApi('POST', `config/automation/config/${autoId}`, {
        alias: `VWM: Water reset ${shortId} (${method === 'button' ? 'button' : 'sensor'})`,
        description: `Auto-generated by Vacuum Water Monitor`,
        trigger: trigger,
        condition: conditions,
        action: actions,
        mode: 'single',
      });
      return autoId;
    } catch (e) {
      console.error('[VWM] Create automation failed:', e);
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

  _resolveProfileKey(device) {
    // Auto-resolve the model profile from brand_profile or the vacuum entity id,
    // so a known model (e.g. vacuum.roborock_s8_maxv_ultra) gets its real tank
    // capacity OOTB without the user manually picking a Brand Profile.
    if (!device) return null;
    const bp = device.brand_profile;
    if (bp && CALIBRATION_DATA[bp]) return bp;
    const ent = String(device.vacuum_entity || '').toLowerCase();
    if (ent.startsWith('vacuum.')) {
      const cand = ent.slice(7);
      if (CALIBRATION_DATA[cand]) return cand;
    }
    if (typeof BRAND_PROFILES !== 'undefined') {
      for (const k in BRAND_PROFILES) {
        if (BRAND_PROFILES[k].vacuum_entity && BRAND_PROFILES[k].vacuum_entity === device.vacuum_entity) return k;
      }
    }
    return null;
  }

  _getDevices() {
    if (this._config.devices && Array.isArray(this._config.devices)) {
      return this._config.devices.map(d => {
        // Apply brand profile if each device specifies one
        if (d.brand_profile && BRAND_PROFILES[d.brand_profile]) {
          return { ...BRAND_PROFILES[d.brand_profile], ...d };
        }
        return d;
      });
    }
    // Single device mode
    const single = {};
    const keys = [
      'device_name','water_sensor','water_used_sensor','water_used_input','water_total_ml',
      'vacuum_entity','dock_error_sensor','filter_sensor','last_session_sensor',
      'last_reset_entity','main_brush_sensor','side_brush_sensor','filter_time_sensor',
      'sensor_dirty_sensor','dock_brush_sensor','dock_strainer_sensor',
      'dock_clean_water_sensor','dock_dirty_water_sensor','water_shortage_sensor',
      'mop_attached_sensor','mop_drying_sensor','area_sensor','duration_sensor',
      'last_clean_start','last_clean_end','charge_sensor','icon',
    ];
    keys.forEach(k => { if (this._config[k] != null) single[k] = this._config[k]; });
    if (Object.keys(single).length === 0) {
      const serverDevices = (this._userDevices && this._userDevices.length)
        ? this._userDevices
        : (this._discoveredVacuums || []).map(v => ({
            vacuum_entity: v.entity_id,
            name: v.name || v.entity_id,
            icon: '\uD83E\uDD16',
          }));
      return serverDevices.map(d => {
        if (d.brand_profile && BRAND_PROFILES[d.brand_profile]) {
          return { ...BRAND_PROFILES[d.brand_profile], ...d };
        }
        return d;
      });
    }
    single.name = single.device_name || this._config.device_name || 'Vacuum';
    // Merge config single device + user-added devices
    const userDevs = (this._userDevices || []).filter(ud => ud.vacuum_entity !== single.vacuum_entity).map(d => {
      if (d.brand_profile && BRAND_PROFILES[d.brand_profile]) {
        return { ...BRAND_PROFILES[d.brand_profile], ...d };
      }
      return d;
    });
    return [single, ...userDevs];
  }

  // Auto-discover vacuum entities from HA states. See plugin commit 6f6444a
  // (Matter dedup) for the heuristic — when one robot is exposed via both the
  // native vendor integration and a Matter bridge, prefer the native entity.
  _autoDiscoverVacuums() {
    if (this._discoveredVacuums && this._discoveredVacuums.length) return this._discoveredVacuums;
    if (!this._hass) return [];
    const all = Object.values(this._hass.states)
      .filter(s => s.entity_id.startsWith('vacuum.'));
    const entityReg = this._hass.entities || {};
    const deviceReg = this._hass.devices || {};
    const meta = all.map(s => {
      const ent = entityReg[s.entity_id];
      const dev = ent?.device_id ? deviceReg[ent.device_id] : null;
      return {
        entity_id: s.entity_id,
        platform: ent?.platform || null,
        manufacturer: dev?.manufacturer || null,
      };
    });
    const isDuplicate = (m) => {
      if (m.platform !== 'matter' || !m.manufacturer) return false;
      return meta.some(other =>
        other.entity_id !== m.entity_id &&
        other.manufacturer === m.manufacturer &&
        other.platform &&
        other.platform !== 'matter'
      );
    };
    return all
      .filter(s => !isDuplicate(meta.find(m => m.entity_id === s.entity_id)))
      .map(s => ({
        entity_id: s.entity_id,
        name: (s.attributes && s.attributes.friendly_name) || s.entity_id,
        state: s.state,
        battery: s.attributes && s.attributes.battery_level,
      }));
  }

  _calcDeviceData(device) {
    // Derive total water capacity: explicit config > calibration data > 0
    const profileKey = this._resolveProfileKey(device);
    const calib = profileKey ? (CALIBRATION_DATA[profileKey] || null) : null;
    const totalMl = device.water_total_ml || (calib ? calib.tank_ml : 0);
    let remainingL = null, percentRemaining = null, usedMl = null;

    // The integration state machine populates usedMl when no live water sensor exists.
    const configMissing = false; // standalone mode works out of the box — never flag as misconfigured

    if (totalMl > 0) {
      const waterSensorRaw = this._getStateValue(device.water_sensor);
      if (waterSensorRaw !== null && waterSensorRaw !== 'unavailable' && waterSensorRaw !== 'unknown') {
        remainingL = parseFloat(waterSensorRaw);
        usedMl = totalMl - (remainingL * 1000);
        percentRemaining = Math.max(0, Math.min(100, (remainingL * 1000 / totalMl) * 100));
      } else {
        const jsUsed = this._getEffectiveUsedMl(device);
        if (jsUsed !== null && jsUsed !== undefined) {
          usedMl = jsUsed;
          remainingL = (totalMl - usedMl) / 1000;
          percentRemaining = Math.max(0, Math.min(100, (totalMl - usedMl) / totalMl * 100));
        }
      }
    }

    const dockErr = this._getStateValue(device.dock_error_sensor);
    const waterEmpty = dockErr === 'water_empty';
    const vacState = this._getStateValue(device.vacuum_entity);
    const isCleaning = vacState === 'cleaning';
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
    const areaCleaned = this._getStateValue(device.area_sensor);
    const durationSec = this._getStateValue(device.duration_sensor);
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

    const dockCleanWaterFull = this._getStateValue(device.dock_clean_water_sensor) === 'on';
    const dockDirtyWaterFull = this._getStateValue(device.dock_dirty_water_sensor) === 'on';
    const waterShortage = this._getStateValue(device.water_shortage_sensor) === 'on';
    const mopAttached = this._getStateValue(device.mop_attached_sensor) === 'on';
    const mopDrying = this._getStateValue(device.mop_drying_sensor) === 'on';

    return {
      totalMl, remainingL, percentRemaining, usedMl,
      waterEmpty, isCleaning, filterDays, sessionMl, lastReset, vacState, charge,
      mainBrushH, sideBrushH, filterH, sensorH, dockBrushH, dockStrainerH,
      dockCleanWaterFull, dockDirtyWaterFull, waterShortage, mopAttached, mopDrying,
      areaCleaned, durationSec, lastCleanStart, lastCleanEnd,
      configMissing,
    };
  }

  _getStatus(data, cfg) {
    if (data.totalMl === 0) return { label: 'No Water', color: '#6b7280', icon: '\uD83D\uDCA7' };
    if (data.waterEmpty || data.waterShortage) return { label: 'EMPTY', color: '#ef4444', icon: '\u26A0\uFE0F' };
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
      extraRows += `<div class="row"><span class="row-label">\uD83D\uDD04 Last refill</span><span class="row-val">${this._formatReset(data.lastReset)}</span></div>`;
    }
    if (data.charge !== null && data.charge !== undefined) {
      extraRows += this._buildBatteryBar(data.charge);
    }

    // Refill button resets the integration's HA Store state.
    const refillBtn = (cfg.show_refill_button !== false)
      ? `<button class="refill-btn" data-vacuum="${device.vacuum_entity || ''}">\uD83D\uDCA7 Refilled</button>` : '';

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

    const dockHtml = (cfg.show_dock_status !== false) ? this._buildDockSection(device, data) : '';
    // Q1/Q2: Calibration info based on brand profile
    let calibHtml = '';
    // Prefer per-device brand_profile (auto-detected) over card-level YAML config.
    // Mirror of the v4 plugin fix — see ha-vacuum-water-monitor.js commit
    // 6f6444a for rationale.
    const profileKey = (device && this._resolveProfileKey(device)) || cfg.brand_profile || 'generic';
    const calib = typeof CALIBRATION_DATA !== 'undefined' ? CALIBRATION_DATA[profileKey] || CALIBRATION_DATA['generic'] : null;
    if (calib) {
      const levels = Object.entries(calib.water_per_m2).map(([k,v]) => `<span style="display:inline-block;padding:3px 10px;background:var(--bento-bg,#f0f4f8);border-radius:6px;margin:2px 4px;font-size:12px;"><b>${k}:</b> ${v} ml/m²</span>`).join('');
      const estArea = data.totalMl > 0 ? Math.round(data.totalMl / (calib.water_per_m2.medium || 10)) : calib.avg_area_per_charge;
      calibHtml = `
        <div style="margin-top:16px;padding:16px;background:var(--bento-bg,#f8fafc);border:1.5px solid var(--bento-border,#e2e8f0);border-radius:12px;">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px;">📐 Calibration: ${calib.label}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
            <div>🪣 Tank: <b>${calib.tank_ml} ml</b></div>
            <div>🧹 Mop: <b>${calib.mop_type}</b></div>
            <div>📏 Est. area/charge: <b>~${calib.avg_area_per_charge} m²</b></div>
            <div>📏 Est. area/tank: <b>~${estArea} m²</b> (medium)</div>
          </div>
          <div style="margin-top:10px;font-size:12px;"><b>Water usage per m²:</b> ${levels}</div>
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
        ${calibHtml}
      </div>`;
  }


  // ── REFILL METHODS SECTION ──────────────────────────────────────────────

  _buildRefillMethodsSection(device) {
    const vacId = device.vacuum_entity || '';
    const shortId = vacId.replace('vacuum.', '') || 'robot';
    const rc = this._refillConfig[shortId] || {};

    // Get available entities
    const buttons = this._getInputButtons();
    const sensors = this._getDoorSensors();

    const buttonOpts = buttons.map(b =>
      `<option value="${b.id}" ${rc.buttonEntity === b.id ? 'selected' : ''}>${b.name}</option>`
    ).join('');

    const sensorOpts = sensors.map(s =>
      `<option value="${s.id}" ${rc.sensorEntity === s.id ? 'selected' : ''}>${s.name} (${s.state})</option>`
    ).join('');

    const methodStyle = 'margin-bottom:10px;padding:12px;background:var(--vwm-overlay-light,rgba(0,0,0,0.04));border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)';
    const labelStyle = 'font-weight:700;font-size:13px;margin-bottom:6px;display:flex;align-items:center;gap:6px';
    const descStyle = 'font-size:12px;color:var(--vwm-text-secondary,#6b7280);line-height:1.4;margin-bottom:8px';
    const selectStyle = 'width:100%;padding:7px 10px;border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:8px;font-size:12px;background:var(--vwm-bg,#fff);color:var(--vwm-text,#1e293b);font-family:Inter,sans-serif';
    const btnStyle = 'padding:6px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;font-family:Inter,sans-serif;margin-top:6px';
    const btnPrimary = btnStyle + ';background:rgba(59,130,246,0.12);color:#3b82f6;border:1px solid rgba(59,130,246,0.3)';
    const btnSuccess = btnStyle + ';background:rgba(34,197,94,0.12);color:#16a34a;border:1px solid rgba(34,197,94,0.3)';
    const statusOk = '<span style="color:#22c55e;font-size:11px;font-weight:600">\u2705 Configured</span>';
    const statusNone = '<span style="color:var(--vwm-text-muted,#9ca3af);font-size:11px">\u2014 Not configured</span>';

    return `
      <div class="section-block">
        <div class="section-title" style="cursor:pointer;display:flex;align-items:center;gap:6px" id="refill-methods-toggle">
          \uD83D\uDD04 Tank reset methods <span id="refill-methods-arrow" style="font-size:10px;transition:transform 0.2s">\u25B6</span>
        </div>
        <div id="refill-methods-body" style="display:none">

          <div style="margin:8px 0;padding:10px 14px;background:rgba(245,158,11,0.1);border:1.5px solid rgba(245,158,11,0.25);border-radius:10px;font-size:12px;line-height:1.5;color:var(--vwm-text,#1e293b)">
            \u26A0\uFE0F Most robots don't report tank removal/insertion. Choose a reset method that works for you.
          </div>

          <!-- Method 1: Card button -->
          <div style="${methodStyle}">
            <div style="${labelStyle}">\u2460 Button in this card</div>
            <div style="${descStyle}">
              Use the <strong>\uD83D\uDCA7 Refilled</strong> button above. Simplest option - click when you refill water.
            </div>
          </div>

          <!-- Method 2: Dashboard button / physical -->
          <div style="${methodStyle}">
            <div style="${labelStyle}">\u2461 Dashboard / physical button ${rc.buttonEntity ? statusOk : statusNone}</div>
            <div style="${descStyle}">
              Create an <code>input_button</code> entity - you can add it as a tile in your dashboard or link it to a Zigbee/Z-Wave button.
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
              <select id="refill-btn-select" style="${selectStyle};flex:1;min-width:180px">
                <option value="">-- Select input_button --</option>
                ${buttonOpts}
              </select>
              <button id="refill-btn-create" style="${btnSuccess}">+ Create new</button>
            </div>
            ${rc.buttonEntity ? '' : '<div style="margin-top:6px">'}
            <button id="refill-btn-save" style="${btnPrimary};margin-top:6px">\uD83D\uDD17 Save and create automation</button>
            ${rc.buttonEntity ? '<button id="refill-btn-remove" style="' + btnStyle + ';background:rgba(239,68,68,0.08);color:#ef4444;border:1px solid rgba(239,68,68,0.2);margin-left:6px">\uD83D\uDDD1\uFE0F Remove</button>' : ''}
            <span id="refill-btn-status" style="font-size:11px;margin-left:8px"></span>
          </div>

          <!-- Method 3: Door sensor -->
          <div style="${methodStyle}">
            <div style="${labelStyle}">\u2462 Door sensor / contact ${rc.sensorEntity ? statusOk : statusNone}</div>
            <div style="${descStyle}">
              Attach a door sensor (e.g. Aqara Door Sensor) to the tank or station flap. Closing = tank in place = auto-reset.
            </div>
            <select id="refill-sensor-select" style="${selectStyle}">
              <option value="">-- Select binary_sensor (door/window) --</option>
              ${sensorOpts}
            </select>
            <div style="display:flex;gap:6px;align-items:center;margin-top:6px">
              <button id="refill-sensor-save" style="${btnPrimary}">\uD83D\uDD17 Save and create automation</button>
              ${rc.sensorEntity ? '<button id="refill-sensor-remove" style="' + btnStyle + ';background:rgba(239,68,68,0.08);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">\uD83D\uDDD1\uFE0F Remove</button>' : ''}
              <span id="refill-sensor-status" style="font-size:11px"></span>
            </div>
          </div>

        </div>
      </div>`;
  }

  _buildDockSection(device, data) {
    const items = [];
    if (device.dock_clean_water_sensor) {
      items.push({ label: '\uD83D\uDCA7 Clean Water Box', value: data.dockCleanWaterFull ? 'Full' : 'OK', color: data.dockCleanWaterFull ? '#ef4444' : '#22c55e', icon: data.dockCleanWaterFull ? '\u26A0\uFE0F' : '\u2705' });
    }
    if (device.dock_dirty_water_sensor) {
      items.push({ label: '\uD83E\uDEA3 Dirty Water Box', value: data.dockDirtyWaterFull ? 'Full - Empty!' : 'OK', color: data.dockDirtyWaterFull ? '#ef4444' : '#22c55e', icon: data.dockDirtyWaterFull ? '\uD83D\uDEA8' : '\u2705' });
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
        <span class="con-label">${item.icon || '\uD83D\uDD27'} ${_esc(this._sanitize(item.name))}</span>
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
          <div class="section-title" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
            \u2699\uFE0F Custom calibration values <span style="font-size:10px;color:var(--bento-text-muted);font-weight:400">(click to expand)</span>
          </div>
          <div style="display:none;margin-top:8px">
            <div style="font-size:11px;color:var(--bento-text-secondary);margin-bottom:10px;line-height:1.5">
              If your robot is not on the list or you want to correct values — enter your own data. They will be saved in browser memory.
            </div>
            <div id="vwm-custom-form" style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Dock tank (ml)
                <input type="number" id="vwm-custom-tank" placeholder="e.g. 3000" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Robot tank (ml)
                <input type="number" id="vwm-custom-robot-tank" placeholder="e.g. 350" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Mop washing (ml/cycle)
                <input type="number" id="vwm-custom-wash" placeholder="e.g. 150" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
              <label style="font-size:11px;color:var(--bento-text-secondary)">
                Coverage / charge (m\u00B2)                <input type="number" id="vwm-custom-area" placeholder="e.g. 250" style="width:100%;padding:6px 8px;border:1px solid var(--bento-border);border-radius:6px;background:var(--bento-bg);color:var(--bento-text);font-size:12px;margin-top:2px">
              </label>
            </div>
            <div style="margin-top:10px">
              <div style="font-size:11px;color:var(--bento-text-secondary);margin-bottom:6px">Mopping modes — mode name and ml/m\u00B2 usage:</div>
              <div id="vwm-custom-modes" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px">
                <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;min-width:0">
                  <input type="text" placeholder="np. low" style="flex:1;min-width:80px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name">
                  <input type="number" placeholder="ml/m\u00B2" style="width:70px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val">
                </div>
                <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;min-width:0">
                  <input type="text" placeholder="np. medium" style="flex:1;min-width:80px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name">
                  <input type="number" placeholder="ml/m\u00B2" style="width:70px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val">
                </div>
                <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;min-width:0">
                  <input type="text" placeholder="np. high" style="flex:1;min-width:80px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name">
                  <input type="number" placeholder="ml/m\u00B2" style="width:70px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val">
                </div>
              </div>
              <div style="margin-top:6px;text-align:right">
                <button onclick="this.getRootNode().host._addCustomMode()" style="padding:4px 10px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-card);color:var(--bento-text-secondary);font-size:10px;cursor:pointer">+ Add mode</button>
              </div>
            </div>
            <div style="margin-top:12px;display:flex;gap:8px">
              <button onclick="this.getRootNode().host._saveCustomCalibration()" style="flex:1;padding:8px 16px;border:none;border-radius:8px;background:#3b82f6;color:white;font-weight:600;font-size:12px;cursor:pointer">\uD83D\uDCBE Save</button>
              <button onclick="this.getRootNode().host._clearCustomCalibration()" style="padding:8px 16px;border:1px solid var(--bento-border);border-radius:8px;background:var(--bento-card);color:var(--bento-text-secondary);font-size:12px;cursor:pointer">\uD83D\uDDD1 Clear</button>
            </div>
          </div>
        </div>
        <div class="section-block" style="text-align:center;padding:16px">
          <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:8px">
            Missing your robot or have more accurate data?
          </div>
          <a href="https://github.com/madmax/ha-tools/issues/new?title=Calibration+data+for+[MODEL]&body=Model:%0ATank+ml:%0AWater+per+m2:%0AMop+wash+ml:%0ASource:%0A" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:6px;padding:8px 20px;border-radius:8px;background:#24292e;color:white;font-size:12px;font-weight:600;text-decoration:none;cursor:pointer">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            Report data or correction on GitHub
          </a>
          <div style="margin-top:6px;font-size:10px;color:var(--bento-text-muted)">
            Calibration data: manufacturer specs + Smart Home Hookup / Vacuum Wars tests + user measurements.
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
          ${s.water ? `<span class="session-stat">\uD83D\uDCA7 ${s.water} ml</span>` : ''}
          ${s.duration ? `<span class="session-stat">\u23F1\uFE0F ${s.duration}</span>` : ''}
        </div>
      </div>`;
    }).join('');

    const noHistory = !lastSessionHtml && !manualRows && !data.isCleaning;

    return `
      <div class="tab-content">
        ${currentSession}
        ${lastSessionHtml ? `<div class="section-block"><div class="section-title">\uD83D\uDDD3\uFE0F Last Session (HA)</div>${lastSessionHtml}</div>` : ''}
        ${manualRows ? `<div class="section-block"><div class="section-title">\uD83D\uDCCA Logged Sessions</div>${manualRows}</div>` : ''}
        ${noHistory ? '<div class="empty-state">No session history available.<br>Start a cleaning to record sessions.</div>' : ''}
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
    return Array.isArray(sessions) ? sessions : [];
  }

  _saveSession(device, session) {
    const key = (device && (device.vacuum_entity || device.name)) || 'default';
    const all = { ...(((this._serverState.settings || {}).sessions) || {}) };
    const sessions = this._getSessionsFromStorage(device);
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
        <span class="stats-device">${device.icon || '\uD83E\uDDA4'} ${_esc(this._sanitize(device.name || 'Vacuum'))}</span>
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
    const totalWater = thisWeek.reduce((sum, s) => sum + (parseFloat(s.water) || 0), 0);
    const totalSessions = thisWeek.length;

    return `<div class="section-block">
      <div class="section-title">\uD83D\uDCC5 This Week (logged)</div>
      <div class="stats-grid">
        <div class="stat-box"><div class="stat-num">${totalSessions}</div><div class="stat-label">sessions</div></div>
        <div class="stat-box"><div class="stat-num">${(totalArea || 0).toFixed(0)}</div><div class="stat-label">m\u00B2 cleaned</div></div>
        <div class="stat-box"><div class="stat-num">${((totalWater || 0) / 1000).toFixed(1)}</div><div class="stat-label">L water</div></div>
      </div>
    </div>`;
  }


  // ── TAB: DATABASE ─────────────────────────────────────────────────────────


  _saveCustomCalibration() {
    const shadow = this.shadowRoot;
    const tank = shadow.getElementById('vwm-custom-tank')?.value;
    const robotTank = shadow.getElementById('vwm-custom-robot-tank')?.value;    const wash = shadow.getElementById('vwm-custom-wash')?.value;
    const area = shadow.getElementById('vwm-custom-area')?.value;
    const modeNames = shadow.querySelectorAll('.vwm-mode-name');
    const modeVals = shadow.querySelectorAll('.vwm-mode-val');
    const modes = {};
    modeNames.forEach((n, i) => {
      const name = n.value?.trim();
      const val = parseFloat(modeVals[i]?.value);
      if (name && !isNaN(val)) modes[name] = val;
    });
    const custom = {};
    if (tank) custom.tank_ml = parseInt(tank);
    if (robotTank) custom.robot_tank_ml = parseInt(robotTank);
    if (wash) custom.mop_wash_ml = parseInt(wash);
    if (area) custom.avg_area_per_charge = parseInt(area);
    if (Object.keys(modes).length > 0) {
      custom.water_per_m2 = modes;
      custom.mop_modes = modes;
    }
    if (Object.keys(custom).length === 0) return;
    const key = this._config?.brand_profile || 'default';
    const all = { ...(((this._serverState.settings || {}).custom_calibration) || {}) };
    all[key] = custom;
    this._customCalib = custom;
    this._serverState.settings = { ...(this._serverState.settings || {}), custom_calibration: all };
    this._saveServerSettings({ custom_calibration: all });
    this._lastHtml = '';
    this._updateContent();
    const btn = shadow.querySelector('[onclick*="saveCustom"]');
    if (btn) { const orig = btn.textContent; btn.textContent = '\u2705 Zapisano!'; setTimeout(() => btn.textContent = orig, 2000); }
  }

  _clearCustomCalibration() {    const key = this._config?.brand_profile || 'default';
    const all = { ...(((this._serverState.settings || {}).custom_calibration) || {}) };
    delete all[key];
    this._customCalib = null;
    this._serverState.settings = { ...(this._serverState.settings || {}), custom_calibration: all };
    this._saveServerSettings({ custom_calibration: all });
    this._lastHtml = '';
    this._updateContent();
  }

  _loadCustomCalibration() {
    this._applyServerSettings();
  }

  _addCustomMode() {
    const container = this.shadowRoot.getElementById('vwm-custom-modes');
    if (!container) return;
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:4px;align-items:center';
    div.innerHTML = '<input type="text" placeholder="tryb" style="flex:1;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-name"><input type="number" placeholder="ml/m\u00B2" style="width:60px;padding:4px 6px;border:1px solid var(--bento-border);border-radius:4px;background:var(--bento-bg);color:var(--bento-text);font-size:11px" class="vwm-mode-val"><span onclick="this.parentElement.remove()" style="cursor:pointer;color:var(--bento-text-muted);font-size:14px">\u00D7</span>';
    container.appendChild(div);
  }
  _buildDatabaseTab() {
    const models = Object.entries(CALIBRATION_DATA);
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
      const levels = Object.entries(m.water_per_m2);
      const levelTags = levels.map(([mode, val]) => {
        const estArea = Math.round(m.tank_ml / val);
        return `<span style="${tagSt};${levelColor(val)}" title="${mode}: ${val} ml/m\u00B2 \u2192 ~${estArea} m\u00B2/tank">${mode}: ${val}</span>`;
      }).join(' ');

      // Area estimates per mode
      const areaEstimates = levels.map(([mode, val]) => {
        const area = Math.round(m.tank_ml / val);
        return `<span style="${tagSt};background:var(--vwm-overlay-light,rgba(0,0,0,0.04));color:var(--vwm-text-secondary,#6b7280)">${mode}: ~${area} m\u00B2</span>`;
      }).join(' ');

      const isActive = this._config.brand_profile === key;
      const rowBg = isActive ? 'background:rgba(59,130,246,0.06)' : '';

      return `<tr style="${rowBg}">
        <td style="${cellSt}">
          <div style="font-weight:600;font-size:12px">${m.label}${isActive ? ' <span style="color:#3b82f6;font-size:10px">\u2705 aktywny</span>' : ''}</div>
          <div style="font-size:10px;color:var(--vwm-text-muted,#9ca3af);margin-top:2px">${m.mop_type}</div>
        </td>
        <td style="${cellSt};${numSt}">${m.tank_ml} ml</td>
        <td style="${cellSt}">${levelTags}</td>
        <td style="${cellSt}">${areaEstimates}</td>
        <td style="${cellSt};${numSt}">${m.avg_area_per_charge} m\u00B2</td>
        <td style="${cellSt};font-size:10px;color:var(--vwm-text-secondary,#6b7280);max-width:140px">${m.notes || ''}${m.mop_wash_ml ? ' | Wash: ' + m.mop_wash_ml + 'ml/cycle' : ''}</td>
      </tr>`;
    }).join('');

    // Summary card for active profile
    let activeCard = '';
    const profileKey = this._config.brand_profile;
    const active = profileKey ? CALIBRATION_DATA[profileKey] : null;
    if (active) {
      const levels = Object.entries(active.water_per_m2);
      activeCard = `
        <div style="margin-bottom:14px;padding:14px;background:rgba(59,130,246,0.06);border:1.5px solid rgba(59,130,246,0.2);border-radius:12px">
          <div style="font-weight:700;font-size:14px;margin-bottom:8px">\uD83E\uDDA4 ${active.label} <span style="font-size:11px;color:#3b82f6;font-weight:500">(aktywny profil)</span></div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:10px">
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${active.tank_ml}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">ml zbiornik</div>
            </div>
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${active.avg_area_per_charge}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">m\u00B2 / charge</div>
            </div>
            <div style="text-align:center;padding:10px;background:var(--vwm-bg,#fff);border-radius:10px;border:1px solid var(--vwm-border,#e5e7eb)">
              <div style="font-size:20px;font-weight:700;color:var(--bento-text)">${levels.length}</div>
              <div style="font-size:10px;color:var(--bento-text-muted)">tryb\u00F3w mopu</div>
            </div>
          </div>
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">Zu\u017Cycie wody wg trybu:</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px">
            ${levels.map(([mode, val]) => {
              const area = Math.round(active.tank_ml / val);
              const pct = Math.round((val / Math.max(...levels.map(l => l[1]))) * 100);
              return `<div style="padding:8px;background:var(--vwm-bg,#fff);border-radius:8px;border:1px solid var(--vwm-border,#e5e7eb)">
                <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:var(--bento-text-secondary);margin-bottom:4px">${mode}</div>
                <div style="font-size:16px;font-weight:700;color:var(--bento-text)">${val} <span style="font-size:10px;font-weight:400">ml/m\u00B2</span></div>
                <div style="margin:4px 0;height:4px;background:rgba(59,130,246,0.12);border-radius:2px;overflow:hidden"><div style="height:100%;width:${pct}%;border-radius:2px;background:${val <= 8 ? '#22c55e' : val <= 14 ? '#3b82f6' : val <= 18 ? '#f59e0b' : '#ef4444'}"></div></div>
                <div style="font-size:10px;color:var(--bento-text-muted)">\u2248 ${area} m\u00B2 / zbiornik</div>
              </div>`;
            }).join('')}
          </div>
          ${active.mop_type ? `<div style="margin-top:8px;font-size:11px;color:var(--bento-text-secondary)">\uD83E\uDDF9 ${active.mop_type}</div>` : ''}
          ${active.notes ? `<div style="margin-top:4px;font-size:11px;color:var(--bento-text-muted);font-style:italic">\uD83D\uDCA1 ${active.notes}</div>` : ''}
          ${active.mop_wash_ml ? `<div style="margin-top:4px;font-size:11px;color:var(--bento-text-secondary)">\uD83D\uDEBF Mop wash in dock: ${active.mop_wash_ml}ml/cycle${active.mop_wash_modes ? ' (' + Object.entries(active.mop_wash_modes).map(([k,v]) => k + ': ' + v + 'ml').join(', ') + ')' : ''}</div>` : ''}
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
            <strong>Tank</strong> — capacity of robot's built-in tank (not dock). Robots with auto-refill (Dreame, Ecovacs) have small tanks (~80 ml) because they refill automatically from dock (3–4L).<br>
            <strong>Coverage / tank</strong> — estimated area the robot cleans on one full tank in given mode.<br>
            <strong>Coverage / charge</strong> — max area on one battery charge (regardless of water).
          </div>
        </div>
      </div>`;
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
        ${undiscovered.map(v => `<div class="disc-row" style="cursor:pointer" data-entity="${v.entity_id}">
          <span class="disc-name">\uD83E\uDDA4 ${_esc(this._sanitize(v.name))}</span>
          <span class="disc-id">${v.entity_id}</span>
          <span class="disc-state" style="color:${v.state === 'cleaning' ? '#22c55e' : '#6b7280'}">${v.state}</span>
          ${v.battery ? `<span class="disc-bat">\uD83D\uDD0B ${v.battery}%</span>` : ''}
          <button class="maint-add-btn disc-add-btn" data-entity="${v.entity_id}" style="padding:3px 10px;font-size:11px">+ Add</button>
        </div>`).join('')}
      </div>` : '';

    const userDevsHtml = (this._userDevices || []).length > 0 ? `<div class="section-block"><div class="section-title">\u2795 Manually added</div>${this._userDevices.map(ud => `<div class="disc-row"><span class="disc-name">${ud.icon || '\uD83E\uDDA4'} ${_esc(this._sanitize(ud.name))}</span><span class="disc-id">${_esc(ud.vacuum_entity)}</span><button class="maint-del-btn user-dev-remove" data-entity="${_esc(ud.vacuum_entity)}" title="Remove">\uD83D\uDDD1\uFE0F</button></div>`).join('')}</div>` : '';

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

        <!-- Refill methods -->
        <div style="background:var(--vwm-overlay-light,rgba(0,0,0,0.03));border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:14px;padding:16px">
          <div style="font-size:14px;font-weight:700;color:var(--bento-text);margin-bottom:4px;display:flex;align-items:center;gap:8px">
            \uD83D\uDD04 Tank reset methods
          </div>
          <div style="font-size:12px;color:var(--bento-text-secondary);margin-bottom:12px;line-height:1.5">
            Choose how to reset the water counter after refilling the tank. You can use one or multiple methods simultaneously.
          </div>

          <div style="margin:8px 0 12px;padding:10px 14px;background:rgba(245,158,11,0.1);border:1.5px solid rgba(245,158,11,0.25);border-radius:10px;font-size:12px;line-height:1.5;color:var(--vwm-text,#1e293b)">
            \u26A0\uFE0F Most robots don't report tank removal/insertion. Choose a reset method that works for you.
          </div>

          ${this._buildRefillMethodCard(device)}
        </div>
      </div>`;
  }

  _buildRefillMethodCard(device) {
    const vacId = device.vacuum_entity || '';
    const shortId = vacId.replace('vacuum.', '') || 'robot';
    const rc = this._refillConfig[shortId] || {};
    const buttons = this._getInputButtons();
    const sensors = this._getDoorSensors();

    const buttonOpts = buttons.map(b =>
      `<option value="${b.id}" ${rc.buttonEntity === b.id ? 'selected' : ''}>${b.name}</option>`
    ).join('');
    const sensorOpts = sensors.map(s =>
      `<option value="${s.id}" ${rc.sensorEntity === s.id ? 'selected' : ''}>${s.name} (${s.state})</option>`
    ).join('');

    const statusOk = '<span style="color:#22c55e;font-size:11px;font-weight:600">\u2705 Configured</span>';
    const statusNone = '<span style="color:var(--vwm-text-muted,#9ca3af);font-size:11px">\u2014 Not configured</span>';

    const cardSt = 'margin-bottom:10px;padding:14px;background:var(--vwm-bg,#fff);border-radius:12px;border:1.5px solid var(--vwm-border,#e5e7eb)';
    const labelSt = 'font-weight:700;font-size:13px;margin-bottom:6px;display:flex;align-items:center;gap:6px';
    const descSt = 'font-size:12px;color:var(--vwm-text-secondary,#6b7280);line-height:1.5;margin-bottom:10px';
    const selectSt = 'width:100%;padding:8px 12px;border:1.5px solid var(--vwm-border,#e5e7eb);border-radius:8px;font-size:12px;background:var(--vwm-bg,#fff);color:var(--vwm-text,#1e293b);font-family:Inter,sans-serif';
    const btnSt = 'padding:7px 16px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;font-family:Inter,sans-serif;margin-top:8px';
    const btnPrimary = btnSt + ';background:rgba(59,130,246,0.12);color:#3b82f6;border:1px solid rgba(59,130,246,0.3)';
    const btnSuccess = btnSt + ';background:rgba(34,197,94,0.12);color:#16a34a;border:1px solid rgba(34,197,94,0.3)';

    return `
      <!-- Method 1: Card button -->
      <div style="${cardSt}">
        <div style="${labelSt}">\u2460 Button in this card</div>
        <div style="${descSt}">
          Use the <strong>\uD83D\uDCA7 Refilled</strong> button in the Water tab. Simplest option - click when you refill water.
        </div>
      </div>

      <!-- Method 2: Dashboard button -->
      <div style="${cardSt}">
        <div style="${labelSt}">\u2461 Dashboard / physical button ${rc.buttonEntity ? statusOk : statusNone}</div>
        <div style="${descSt}">
          Create an <code>input_button</code> entity - you can add it as a tile or link it to a Zigbee/Z-Wave button.
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <select id="refill-btn-select" style="${selectSt};flex:1;min-width:180px">
            <option value="">-- Select input_button --</option>
            ${buttonOpts}
          </select>
          <button id="refill-btn-create" style="${btnSuccess}">+ Create new</button>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
          <button id="refill-btn-save" style="${btnPrimary}">\uD83D\uDD17 Save and create automation</button>
          ${rc.buttonEntity ? '<button id="refill-btn-remove" style="' + btnSt + ';background:rgba(239,68,68,0.08);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">\uD83D\uDDD1\uFE0F Remove</button>' : ''}
          <span id="refill-btn-status" style="font-size:11px;margin-left:4px"></span>
        </div>
      </div>

      <!-- Method 3: Door sensor -->
      <div style="${cardSt}">
        <div style="${labelSt}">\u2462 Door sensor / contact ${rc.sensorEntity ? statusOk : statusNone}</div>
        <div style="${descSt}">
          Attach a door sensor (e.g. Aqara Door Sensor) to the tank or station flap. Closing = auto-reset.
        </div>
        <select id="refill-sensor-select" style="${selectSt}">
          <option value="">-- Select binary_sensor (door/window) --</option>
          ${sensorOpts}
        </select>
        <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
          <button id="refill-sensor-save" style="${btnPrimary}">\uD83D\uDD17 Save and create automation</button>
          ${rc.sensorEntity ? '<button id="refill-sensor-remove" style="' + btnSt + ';background:rgba(239,68,68,0.08);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">\uD83D\uDDD1\uFE0F Remove</button>' : ''}
          <span id="refill-sensor-status" style="font-size:11px"></span>
        </div>
      </div>`;
  }

  // ── MULTI-DEVICE TABS ──────────────────────────────────────────────────────

  _buildDeviceTabs(devices) {
    if (devices.length <= 1) return '';
    return `<div class="device-tabs">
      ${devices.map((d, i) => `<button class="dtab ${i === this._activeDeviceIdx ? 'dtab-active' : ''}" data-didx="${i}">${d.icon || '\uD83E\uDDA4'} ${_esc(this._sanitize(d.name || 'Device ' + (i+1)))}</button>`).join('')}
    </div>`;
  }

  // ── MAIN RENDER ───────────────────────────────────────────────────────────

  _render() {
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
        <div class="device-name">${device.icon || '\uD83E\uDDA4'} ${_esc(this._sanitize(device.name || 'Vacuum'))}</div>
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
      <style>${window.HAToolsBentoCSS || ""}
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
        .card { background: var(--bento-card) !important; border-radius: 16px; padding: 16px; color: var(--bento-text); ;
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
        .row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
        .row-label { color: var(--bento-text-secondary); }
        .row-val { font-weight: 600; color: var(--bento-text); }
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
        .section-title { font-size: 11px; font-weight: 700; color: var(--bento-text-muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
        /* Dock */
        .dock-row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; padding: 3px 0; }
        .dock-val { font-weight: 600; font-size: 12px; }
        /* Consumables */
        .consumable-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
        .con-label { font-size: 11px; color: var(--bento-text-secondary); width: 100px; flex-shrink: 0; }
        .con-bar-wrap { flex: 1; }
        .con-bar { height: 6px; background: rgba(59,130,246,0.10); border-radius: 3px; overflow: hidden; }
        .con-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
        .con-val { font-size: 11px; font-weight: 600; width: 55px; text-align: right; flex-shrink: 0; }
        .con-val-wide { width: 80px; }
        /* Custom maintenance */
        .custom-maint-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
        .custom-maint-row .con-label { flex: 1; width: auto; }
        .maint-done-btn, .maint-del-btn { background: none; border: none; cursor: pointer; font-size: 14px; padding: 2px; }
        /* Add form */
        .add-maint-form { display: flex; gap: 6px; flex-wrap: wrap; }
        .maint-input { background: var(--bento-primary-light); border: 1px solid var(--bento-border); border-radius: 6px; color: var(--bento-text); padding: 6px 10px; font-size: 12px; font-family: Inter, sans-serif; flex: 1; min-width: 80px; }
        .maint-days, .maint-icon { max-width: 100px; }
        .maint-input::placeholder { color: var(--bento-text-muted); }
        .maint-add-btn { background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: Inter, sans-serif; white-space: nowrap; }
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

      
        </div>`;

    // Only update DOM if content actually changed
    if (_newHtml !== this._lastHtml) {
      this.shadowRoot.innerHTML = _newHtml;
      this._lastHtml = _newHtml;
      this._attachListeners(devices, device);
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
          <div><strong>Error:</strong> ${err.message}</div>
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
    const refillToggle = sr.querySelector('#refill-methods-toggle');
    if (refillToggle) {
      const body = sr.querySelector('#refill-methods-body');
      const arrow = sr.querySelector('#refill-methods-arrow');
      const wasOpen = localStorage.getItem('ha-tools-vwm-refill-expanded') === 'open';
      if (wasOpen && body) { body.style.display = 'block'; if (arrow) arrow.style.transform = 'rotate(90deg)'; }
      refillToggle.addEventListener('click', () => {
        const isOpen = body.style.display !== 'none';
        body.style.display = isOpen ? 'none' : 'block';
        arrow.style.transform = isOpen ? '' : 'rotate(90deg)';
        localStorage.setItem('ha-tools-vwm-refill-expanded', isOpen ? 'closed' : 'open');
      });
    }

    // Method 2: Button - Create new input_button
    const btnCreate = sr.querySelector('#refill-btn-create');
    if (btnCreate) {
      btnCreate.addEventListener('click', async () => {
        btnCreate.textContent = '\u23F3 Creating...';
        const newId = await this._createRefillButton(device);
        if (newId) {
          btnCreate.textContent = '\u2705 Utworzono!';
          setTimeout(() => this._render(), 1500);
        } else {
          btnCreate.textContent = '\u274C Error';
          setTimeout(() => { btnCreate.textContent = '+ Utw\u00F3rz nowy'; }, 2000);
        }
      });
    }

    // Method 2: Button - Save & create automation
    const btnSave = sr.querySelector('#refill-btn-save');
    if (btnSave) {
      btnSave.addEventListener('click', async () => {
        const select = sr.querySelector('#refill-btn-select');
        const entityId = select && select.value;
        const status = sr.querySelector('#refill-btn-status');
        if (!entityId) { if (status) status.textContent = '\u26A0\uFE0F Select entity'; return; }
        btnSave.textContent = '\u23F3 Creating automation...';
        const autoId = await this._createRefillAutomation(device, 'button', entityId);
        const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
        if (autoId) {
          this._refillConfig[shortId] = { ...this._refillConfig[shortId], buttonEntity: entityId, buttonAutoId: autoId };
          this._saveRefillConfig();
          if (status) status.innerHTML = '<span style="color:#22c55e">\u2705 Saved and created automation!</span>';
          setTimeout(() => this._render(), 1500);
        } else {
          btnSave.textContent = '\uD83D\uDD17 Save and create automation';
          if (status) status.innerHTML = '<span style="color:#ef4444">\u274C Error creating automation</span>';
        }
      });
    }

    // Method 2: Button - Remove
    const btnRemove = sr.querySelector('#refill-btn-remove');
    if (btnRemove) {
      btnRemove.addEventListener('click', () => {
        const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
        const rc = this._refillConfig[shortId] || {};
        delete rc.buttonEntity; delete rc.buttonAutoId;
        this._refillConfig[shortId] = rc;
        this._saveRefillConfig();
        this._render();
      });
    }

    // Method 3: Sensor - Save & create automation
    const sensorSave = sr.querySelector('#refill-sensor-save');
    if (sensorSave) {
      sensorSave.addEventListener('click', async () => {
        const select = sr.querySelector('#refill-sensor-select');
        const entityId = select && select.value;
        const status = sr.querySelector('#refill-sensor-status');
        if (!entityId) { if (status) status.textContent = '\u26A0\uFE0F Select sensor'; return; }
        sensorSave.textContent = '\u23F3 Creating automation...';
        const autoId = await this._createRefillAutomation(device, 'sensor', entityId);
        const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
        if (autoId) {
          this._refillConfig[shortId] = { ...this._refillConfig[shortId], sensorEntity: entityId, sensorAutoId: autoId };
          this._upsertUserDevicePatch(device, { reset_door_sensor: entityId });
          this._saveRefillConfig();
          if (status) status.innerHTML = '<span style="color:#22c55e">\u2705 Saved and created automation!</span>';
          setTimeout(() => this._render(), 1500);
        } else {
          sensorSave.textContent = '\uD83D\uDD17 Save and create automation';
          if (status) status.innerHTML = '<span style="color:#ef4444">\u274C Error creating automation</span>';
        }
      });
    }

    // Method 3: Sensor - Remove
    const sensorRemove = sr.querySelector('#refill-sensor-remove');
    if (sensorRemove) {
      sensorRemove.addEventListener('click', () => {
        const shortId = (device.vacuum_entity || 'robot').replace('vacuum.', '');
        const rc = this._refillConfig[shortId] || {};
        delete rc.sensorEntity; delete rc.sensorAutoId;
        this._refillConfig[shortId] = rc;
        this._upsertUserDevicePatch(device, { reset_door_sensor: null });
        this._saveRefillConfig();
        this._render();
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

    // Discovery injection
    this._injectDiscovery();
  }

  _injectDiscovery() {
    // Discovery banner removed in the standalone integration build.
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
