// Runtime render smoke (jsdom) — instantiates this repo's card(s) with a mock hass
// and fails if a card throws or renders nothing. Catches runtime errors that
// `node --check` cannot (e.g. a render() calling an undefined method).
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');
const ROOT = process.cwd();

function listCardFiles() {
  const out = [];
  for (const f of fs.readdirSync(ROOT)) {
    if (f.endsWith('.js') && !/editor|\.min\./.test(f)) out.push(path.join(ROOT, f));
  }
  const cc = path.join(ROOT, 'custom_components');
  if (fs.existsSync(cc)) for (const d of fs.readdirSync(cc)) {
    const www = path.join(cc, d, 'www');
    if (fs.existsSync(www)) for (const f of fs.readdirSync(www)) {
      if (f.endsWith('.js') && !/editor|\.min\./.test(f)) out.push(path.join(www, f));
    }
  }
  return out;
}
function tagsIn(code) {
  return [...code.matchAll(/customElements\.define\(\s*['"]([a-z0-9-]+)['"]/g)]
    .map(m => m[1]).filter(t => !/editor$/.test(t));
}
function mockHass(overrides = {}) {
  return {
    states: {}, themes: { darkMode: false, themes: {} }, language: 'en',
    locale: { language: 'en', number_format: 'language', time_format: '24' },
    user: { id: 'u', name: 'Demo', is_admin: true, is_owner: true },
    config: { unit_system: { temperature: 'C' }, version: '2025.6.0' },
    callApi: () => Promise.resolve({}), callService: () => Promise.resolve({}),
    callWS: () => Promise.resolve([]), sendWS: () => Promise.resolve([]),
    formatEntityState: (s) => (s && s.state != null) ? String(s.state) : '',
    formatEntityAttributeValue: () => '',
    connection: {
      subscribeEvents: () => Promise.resolve(() => {}),
      subscribeMessage: () => Promise.resolve(() => {}),
      sendMessagePromise: () => Promise.resolve([]), socket: { readyState: 1 }
    },
    ...overrides
  };
}
function stub(window) {
  try { Object.defineProperty(window.navigator, 'language', { configurable: true, get: () => 'en-US' }); } catch (e) {}
  window.requestAnimationFrame = (cb) => setTimeout(() => { try { cb(Date.now()); } catch (e) {} }, 0);
  window.cancelAnimationFrame = () => {};
  window.matchMedia = window.matchMedia || (() => ({ matches: false, media: '', onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return false; } }));
  class RO { observe() {} unobserve() {} disconnect() {} }
  window.ResizeObserver = window.ResizeObserver || RO;
  window.IntersectionObserver = window.IntersectionObserver || RO;
  const store = () => { let m = {}; return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: k => { delete m[k]; }, clear: () => { m = {}; }, key: () => null, get length() { return Object.keys(m).length; } }; };
  try { Object.defineProperty(window, 'localStorage', { configurable: true, value: store() }); } catch (e) {}
  try { Object.defineProperty(window, 'sessionStorage', { configurable: true, value: store() }); } catch (e) {}
}
const delay = (ms) => new Promise(r => setTimeout(r, ms));

function assertNoHostileMarkup(shadowRoot, payload, context) {
  if (shadowRoot.querySelector('[data-vwm-xss]')) {
    throw new Error(`${context}: hostile icon created an HTML element`);
  }
  if (!shadowRoot.textContent.includes(payload)) {
    throw new Error(`${context}: hostile icon was not rendered as text`);
  }
}

async function smokeHostileIcons(target) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
  });
  const { window } = dom;
  const payload = '<img data-vwm-xss="icon">';
  try {
    stub(window);
    window.eval(fs.readFileSync(target.file, 'utf8'));
    const el = window.document.createElement(target.tag);
    el.setConfig({
      type: 'custom:' + target.tag,
      devices: [
        { vacuum_entity: 'vacuum.primary', device_name: 'Primary', icon: payload },
        { vacuum_entity: 'vacuum.secondary', device_name: 'Secondary', icon: payload }
      ]
    });
    el.hass = mockHass({
      states: {
        'input_button.hostile': {
          entity_id: 'input_button.hostile', state: 'unknown',
          attributes: { friendly_name: payload }
        },
        'binary_sensor.hostile': {
          entity_id: 'binary_sensor.hostile', state: payload,
          attributes: { friendly_name: payload, device_class: 'door' }
        }
      }
    });
    window.document.body.appendChild(el);
    el._maintenanceItems = [{ name: 'Persisted task', icon: payload, intervalDays: 7 }];
    el._userDevices = [{ vacuum_entity: 'vacuum.persisted', name: 'Persisted device', icon: payload }];

    el._activeTab = 'water';
    el._lastHtml = '';
    el._render();
    assertNoHostileMarkup(el.shadowRoot, payload, `${path.basename(target.file)} water/config`);

    el._activeTab = 'maintenance';
    el._lastHtml = '';
    el._render();
    assertNoHostileMarkup(el.shadowRoot, payload, `${path.basename(target.file)} maintenance/persisted`);

    el._activeTab = 'settings';
    el._lastHtml = '';
    el._render();
    assertNoHostileMarkup(el.shadowRoot, payload, `${path.basename(target.file)} settings/persisted`);
  } finally {
    window.close();
  }
}

async function smokeDraftAndCalibration(target) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
  });
  const { window } = dom;
  let eventHandler = null;
  let rejectSettingsSave = false;
  let settings = {
    user_devices: [{ vacuum_entity: 'vacuum.a170', name: 'Qrevo 5AE' }],
    custom_calibration: {}
  };
  const calls = [];
  try {
    stub(window);
    window.eval(fs.readFileSync(target.file, 'utf8'));
    const el = window.document.createElement(target.tag);
    const hass = mockHass({
      states: {
        'vacuum.a170': {
          entity_id: 'vacuum.a170', state: 'docked',
          attributes: { friendly_name: 'Qrevo 5AE' }
        }
      },
      callWS: async (message) => {
        calls.push(message);
        if (message.type.endsWith('/get_state')) return { settings, tank_states: {} };
        if (message.type.endsWith('/list_vacuums')) {
          return { vacuums: [{ entity_id: 'vacuum.a170', name: 'Qrevo 5AE' }] };
        }
        if (message.type.endsWith('/set_settings')) {
          if (rejectSettingsSave) throw new Error('simulated Store failure');
          settings = { ...settings, ...(message.patch || {}) };
          if (eventHandler) eventHandler({ data: { settings } });
          return { settings };
        }
        return {};
      },
      connection: {
        subscribeEvents: (handler) => {
          eventHandler = handler;
          return Promise.resolve(() => {});
        },
        subscribeMessage: () => Promise.resolve(() => {}),
        sendMessagePromise: () => Promise.resolve([]), socket: { readyState: 1 }
      }
    });
    el.setConfig({ type: 'custom:' + target.tag });
    window.document.body.appendChild(el);
    el.hass = hass;
    await el._ensureServerState();
    await delay(0);

    const modelCases = [
      [{ vacuum_entity: 'vacuum.a170' }, 4000],
      [{ vacuum_entity: 'vacuum.living_room', brand_profile: 'roborock.vacuum.a170' }, 4000],
      [{ vacuum_entity: 'vacuum.a245' }, 4000],
      [{ vacuum_entity: 'vacuum.xiaomi_h50' }, 4000],
      [{ vacuum_entity: 'vacuum.xiaomi_robot_vacuum_h50_pro' }, 4000],
      [{ vacuum_entity: 'vacuum.tapo_rv50_pro_omni' }, 5000]
    ];
    for (const [device, expected] of modelCases) {
      const actual = el._calcDeviceData(device).totalMl;
      if (actual !== expected) throw new Error(`model alias ${JSON.stringify(device)} resolved ${actual}, expected ${expected}`);
    }

    el._config.brand_profile = undefined;
    const aliasDatabase = el._buildDatabaseTab();
    if (!/Qrevo 5AE[\s\S]*aktywny/.test(aliasDatabase)) {
      throw new Error('Database did not activate the auto-detected a170 profile');
    }

    el._config.brand_profile = 'xiaomi_h50_pro';
    const h50Database = el._buildDatabaseTab();
    for (const expected of ['4,000 ml clean dock', '4,000 ml dirty dock', 'up to 240 m²/fill', '180 ml pre-task', '120 ml mid-task', '5 / 8 / 10 m²']) {
      if (!h50Database.includes(expected)) throw new Error(`H50 Pro database profile is missing: ${expected}`);
    }
    el._config.brand_profile = 'tapo_rv50_pro_omni';
    const tapoDatabase = el._buildDatabaseTab();
    for (const expected of ['5,000 ml clean dock', '4,000 ml dirty dock', '95 ml robot', '60°C wash', '3 water levels']) {
      if (!tapoDatabase.includes(expected)) throw new Error(`Tapo database profile is missing: ${expected}`);
    }
    el._config.brand_profile = 'roborock_qrevo_5ae';
    const qrevoDatabase = el._buildDatabaseTab();
    for (const expected of ['80 ml robot', '200 rpm', '10 mm lift', '30 water levels']) {
      if (!qrevoDatabase.includes(expected)) throw new Error(`Qrevo 5AE database profile is missing: ${expected}`);
    }
    el._config.brand_profile = 'roborock_qrevo_curv_2_flow';
    const flowDatabase = el._buildDatabaseTab();
    for (const expected of ['100 ml robot dirty', '220 rpm', '15 N', '15 mm lift']) {
      if (!flowDatabase.includes(expected)) throw new Error(`Qrevo Curv 2 Flow database profile is missing: ${expected}`);
    }
    el._config.brand_profile = undefined;

    el._activeTab = 'maintenance';
    el._lastHtml = '';
    el._render();
    const body = el.shadowRoot.getElementById('vwm-custom-calibration-body');
    if (!body) throw new Error('custom calibration body is missing');
    body.style.display = 'block';
    const input = el.shadowRoot.getElementById('vwm-custom-tank');
    input.value = '4123';
    el.shadowRoot.getElementById('vwm-custom-wash').value = '175';
    el.shadowRoot.querySelector('.vwm-mode-name').value = 'standard';
    el.shadowRoot.querySelector('.vwm-mode-val').value = '5.5';
    const textInput = el.shadowRoot.getElementById('maint-name');
    textInput.value = 'Water filter';
    textInput.focus();
    textInput.setSelectionRange(5, 5);

    if (!eventHandler) throw new Error('Store event subscription was not established');
    eventHandler({ data: { tank_states: { 'vacuum.a170': { used_ml: 10 } } } });

    const restored = el.shadowRoot.getElementById('vwm-custom-tank');
    if (restored.value !== '4123') throw new Error('Store refresh discarded typed calibration');
    if (el.shadowRoot.getElementById('vwm-custom-wash').value !== '175') {
      throw new Error('Store refresh discarded typed mop-wash calibration');
    }
    if (el.shadowRoot.querySelector('.vwm-mode-name').value !== 'standard'
        || el.shadowRoot.querySelector('.vwm-mode-val').value !== '5.5') {
      throw new Error('Store refresh discarded typed mopping-mode calibration');
    }
    const restoredText = el.shadowRoot.getElementById('maint-name');
    if (restoredText.value !== 'Water filter') throw new Error('Store refresh discarded typed text');
    if (el.shadowRoot.activeElement !== restoredText) throw new Error('Store refresh discarded input focus');
    if (restoredText.selectionStart !== 5 || restoredText.selectionEnd !== 5) {
      throw new Error('Store refresh discarded input caret');
    }
    if (el.shadowRoot.getElementById('vwm-custom-calibration-body').style.display !== 'block') {
      throw new Error('Store refresh collapsed the calibration form');
    }

    const saved = await el._saveCustomCalibration();
    if (saved !== true) throw new Error('successful calibration save did not return true');
    const saveCall = calls.find(call => call.type.endsWith('/set_settings') && call.patch?.custom_calibration);
    if (!saveCall) throw new Error('calibration was not sent to HA Store');
    const scoped = saveCall.patch.custom_calibration['entity:vacuum.a170'];
    if (!scoped || scoped.tracked_capacity_ml !== 4123) throw new Error('calibration was not scoped to the active device');
    if (scoped.wash_volume_ml !== 175 || scoped.usage_ml_per_m2?.standard !== 5.5) {
      throw new Error('usage calibration was not saved for water accounting');
    }
    const calculated = el._calcDeviceData({ vacuum_entity: 'vacuum.a170' });
    if (calculated.totalMl !== 4123) throw new Error('saved calibration is not used by card calculations');
    const successStatus = el.shadowRoot.getElementById('vwm-custom-status');
    if (!successStatus || !/saved/i.test(successStatus.textContent)) {
      throw new Error('successful save has no visible status');
    }

    el._lastHtml = '';
    el._render();
    if (el.shadowRoot.getElementById('vwm-custom-wash').value !== '175'
        || el.shadowRoot.querySelector('.vwm-mode-name').value !== 'standard'
        || el.shadowRoot.querySelector('.vwm-mode-val').value !== '5.5') {
      throw new Error('saved usage calibration was not restored into the form');
    }

    rejectSettingsSave = true;
    el.shadowRoot.getElementById('vwm-custom-tank').value = '4300';
    const originalConsoleError = window.console.error;
    window.console.error = () => {};
    let failed;
    try {
      failed = await el._saveCustomCalibration();
    } finally {
      window.console.error = originalConsoleError;
    }
    if (failed !== false) throw new Error('failed calibration save did not return false');
    const errorStatus = el.shadowRoot.getElementById('vwm-custom-status');
    if (!errorStatus || !/could not|failed|error/i.test(errorStatus.textContent)) {
      throw new Error('failed save has no visible error status');
    }

    rejectSettingsSave = false;
    const cleared = await el._clearCustomCalibration();
    if (cleared !== true) throw new Error('successful calibration clear did not return true');
    if (settings.custom_calibration['entity:vacuum.a170']) {
      throw new Error('calibration clear did not remove the device-scoped Store entry');
    }
    const clearedTank = el.shadowRoot.getElementById('vwm-custom-tank');
    const clearedWash = el.shadowRoot.getElementById('vwm-custom-wash');
    if (!clearedTank || clearedTank.value !== '' || !clearedWash || clearedWash.value !== '') {
      throw new Error('calibration clear left stale values in the form');
    }
    if (el.shadowRoot.querySelector('.vwm-mode-val')?.value) {
      throw new Error('calibration clear left stale mopping-mode values in the form');
    }
  } finally {
    window.close();
  }
}

async function smokeBackendDescriptorsAndTruthfulAccounting(target) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
  });
  const { window } = dom;
  let settings = {
    user_devices: [
      { vacuum_entity: 'vacuum.opaque_xiaomi', name: 'Kitchen Xiaomi' },
      { vacuum_entity: 'vacuum.a170', name: 'Qrevo' },
      { vacuum_entity: 'vacuum.a245', name: 'FlowX' },
      { vacuum_entity: 'vacuum.tapo_matter', name: 'Tapo Matter' }
    ],
    custom_calibration: {
      'entity:vacuum.a170': { tank_ml: 4100, water_per_m2: { measured: 5.5 }, preserve_me: 'keep' },
      'entity:vacuum.unrelated': { tank_ml: 2222 }
    }
  };
  const descriptors = [
    {
      entity_id: 'vacuum.opaque_xiaomi', name: 'Kitchen Xiaomi', profile_key: 'xiaomi_h50',
      profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only',
      evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000,
      reservoirs_ml: { dock_clean: 4000, dock_dirty: 4000, robot_clean: null, robot_dirty: null }, signals: {}
    },
    {
      entity_id: 'vacuum.a170', name: 'Qrevo', profile_key: 'roborock_qrevo_5ae',
      profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only',
      evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000,
      reservoirs_ml: { dock_clean: 4000, dock_dirty: 3500, robot_clean: 80, robot_dirty: null },
      signals: { status_sensor: 'sensor.a170_status', area_sensor: 'sensor.a170_area' }
    },
    {
      entity_id: 'vacuum.a245', name: 'FlowX', profile_key: 'roborock_qrevo_curv_2_flow',
      profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only',
      evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000,
      reservoirs_ml: { dock_clean: 4000, dock_dirty: null, robot_clean: null, robot_dirty: 100 },
      signals: { status_sensor: 'sensor.a245_status', area_sensor: 'sensor.a245_area' }
    },
    {
      entity_id: 'vacuum.tapo_matter', name: 'Tapo Matter', profile_key: 'tapo_rv50_pro_omni',
      profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only',
      evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 5000,
      reservoirs_ml: { dock_clean: 5000, dock_dirty: 4000, robot_clean: 95, robot_dirty: null }, signals: {}
    }
  ];
  let tankStates = {
    'vacuum.opaque_xiaomi': { used_ml: 0, initialized: false, last_accounting_reason: 'missing_area_rate' },
    'vacuum.a170': { used_ml: 0, initialized: true, last_reset_iso: '2026-08-30T10:00:00+00:00' },
    'vacuum.a245': { used_ml: 150, initialized: true, last_reset_iso: '2026-08-30T10:00:00+00:00' },
    'vacuum.tapo_matter': { used_ml: 0, initialized: false, last_accounting_reason: 'missing_area_rate' }
  };
  try {
    stub(window);
    window.eval(fs.readFileSync(target.file, 'utf8'));
    const el = window.document.createElement(target.tag);
    const hass = mockHass({
      states: {
        'vacuum.opaque_xiaomi': { entity_id: 'vacuum.opaque_xiaomi', state: 'docked', attributes: {} },
        'vacuum.a170': { entity_id: 'vacuum.a170', state: 'docked', attributes: {} },
        'vacuum.a245': { entity_id: 'vacuum.a245', state: 'docked', attributes: {} },
        'vacuum.tapo_matter': { entity_id: 'vacuum.tapo_matter', state: 'docked', attributes: {} },
        'sensor.a170_status': { entity_id: 'sensor.a170_status', state: 'washing_the_mop', attributes: {} },
        'sensor.a170_area': { entity_id: 'sensor.a170_area', state: '12.4', attributes: {} },
        'sensor.a245_status': { entity_id: 'sensor.a245_status', state: 'cleaning', attributes: {} },
        'sensor.a245_area': { entity_id: 'sensor.a245_area', state: '4.2', attributes: {} }
      },
      callWS: async (message) => {
        if (message.type.endsWith('/get_state')) return { settings, tank_states: tankStates };
        if (message.type.endsWith('/list_vacuums')) return { vacuums: descriptors };
        if (message.type.endsWith('/set_settings')) {
          settings = { ...settings, ...(message.patch || {}) };
          return { settings };
        }
        return {};
      }
    });
    el.setConfig({ type: 'custom:' + target.tag });
    window.document.body.appendChild(el);
    el.hass = hass;
    await el._ensureServerState();
    await delay(0);

    const devices = el._getDevices();
    const opaque = devices.find(d => d.vacuum_entity === 'vacuum.opaque_xiaomi');
    const a170 = devices.find(d => d.vacuum_entity === 'vacuum.a170');
    const a245 = devices.find(d => d.vacuum_entity === 'vacuum.a245');
    const tapo = devices.find(d => d.vacuum_entity === 'vacuum.tapo_matter');
    if (el._calcDeviceData(opaque).totalMl !== 4000) throw new Error('opaque Xiaomi descriptor capacity was not used');
    if (a170.profile_key !== 'roborock_qrevo_5ae' || a170.status_sensor !== 'sensor.a170_status' || a170.area_sensor !== 'sensor.a170_area') {
      throw new Error('a170 backend profile or same-device signals were not used');
    }
    if (a245.profile_key !== 'roborock_qrevo_curv_2_flow' || a245.status_sensor !== 'sensor.a245_status' || a245.area_sensor !== 'sensor.a245_area') {
      throw new Error('a245 backend profile or same-device signals were not used');
    }
    const uninitialized = el._calcDeviceData(opaque);
    if (uninitialized.usedMl !== null || uninitialized.percentRemaining !== null) {
      throw new Error('uninitialized tank fabricated a full 0-used/100-percent state');
    }
    const uninitializedHtml = el._buildWaterTab(opaque, uninitialized);
    if (!/needs a refill baseline/i.test(uninitializedHtml)) throw new Error('uninitialized tank has no refill-baseline explanation');
    const initialized = el._calcDeviceData(a170);
    if (initialized.usedMl !== 0 || initialized.percentRemaining !== 100) {
      throw new Error('valid post-refill zero-used/full state was not retained');
    }
    const tapoHtml = el._buildWaterTab(tapo, el._calcDeviceData(tapo));
    if (!/manual-only/i.test(tapoHtml) || !/calibration.*manual refill/i.test(tapoHtml)) {
      throw new Error('Tapo Matter manual-only limitation is not visible');
    }
    const diagnostics = el._buildWaterTab(a170, initialized);
    for (const expected of ['roborock_qrevo_5ae', 'dock_clean', 'sensor.a170_status', 'sensor.a170_area', '4,100 ml']) {
      if (!diagnostics.includes(expected)) throw new Error(`backend diagnostics missing ${expected}`);
    }

    el._activeDeviceIdx = devices.findIndex(d => d.vacuum_entity === 'vacuum.a170');
    el._activeTab = 'maintenance'; el._lastHtml = ''; el._render();
    el.shadowRoot.getElementById('vwm-custom-calibration-body').style.display = 'block';
    el.shadowRoot.getElementById('vwm-custom-tank').value = '4200';
    const saved = await el._saveCustomCalibration();
    if (!saved) throw new Error('calibration merge fixture could not save');
    const merged = settings.custom_calibration['entity:vacuum.a170'];
    if (merged.tracked_capacity_ml !== 4200 || merged.preserve_me !== 'keep' || settings.custom_calibration['entity:vacuum.unrelated']?.tank_ml !== 2222) {
      throw new Error('calibration save replaced fields or another device instead of merging');
    }
  } finally {
    window.close();
  }
}

async function smokeRoundOneDescriptorContracts(target) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
  });
  const { window } = dom;
  const calls = [];
  let settings = {
    custom_calibration: {
      default: { tank_ml: 3000, water_per_m2: { default: 1 }, mop_wash_ml: 100 },
      roborock_qrevo_5ae: { tracked_capacity_ml: 3500, usage_ml_per_m2: { profile: 2 }, wash_volume_ml: 150 },
      'entity:vacuum.a170': { tank_ml: 4200, water_per_m2: { entity: 3 }, mop_wash_ml: 175, preserve_me: 'keep' },
      'entity:vacuum.other': { tracked_capacity_ml: 2222 }
    }
  };
  const descriptors = [
    { entity_id: 'vacuum.a170', profile_key: 'roborock_qrevo_5ae', profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only', evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000, reservoirs_ml: { dock_clean: 4000, dock_dirty: 3500 }, signals: { status_sensor: 'sensor.a170_status', area_sensor: 'sensor.a170_area' } },
    { entity_id: 'vacuum.a245', profile_key: 'roborock_qrevo_curv_2_flow', profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only', evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000, reservoirs_ml: { dock_clean: 4000, robot_dirty: 100 }, signals: { status_sensor: 'sensor.a245_status', area_sensor: 'sensor.a245_area' } },
    { entity_id: 'vacuum.paused', profile_key: 'roborock_s8_maxv_ultra', profile_source: 'model_id', profile_confidence: 'high', capability: 'automatic_estimate', evidence: 'maintainer_estimate', tracked_reservoir: 'legacy_tank', tracked_capacity_ml: 3000, reservoirs_ml: {}, signals: {} },
    { entity_id: 'vacuum.conflict', profile_key: 'roborock_s7_maxv', profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only', evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000, reservoirs_ml: { dock_clean: 4000 }, signals: {} },
    { entity_id: 'vacuum.yaml_capacity', profile_key: 'roborock_qrevo_5ae', profile_source: 'model_id', profile_confidence: 'high', capability: 'manual_only', evidence: 'manufacturer_specifications', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000, reservoirs_ml: { dock_clean: 4000 }, signals: { status_sensor: 'sensor.backend_must_not_override' } },
    { entity_id: 'vacuum.hostile', profile_key: '<img data-vwm-descriptor-xss>', profile_source: '<b>source</b>', profile_confidence: 'high', capability: 'unknown', evidence: '<script>evidence</script>', tracked_reservoir: '<i>reservoir</i>', tracked_capacity_ml: 1000, reservoirs_ml: { '<svg data-vwm-descriptor-xss>': '1000' }, signals: { status_sensor: '<img data-vwm-descriptor-xss>' } }
  ];
  const tank_states = {
    'vacuum.a170': { initialized: true, used_ml: 40, last_reset_iso: '2026-08-30T10:00:00+00:00', last_accounting_source: 'area', last_accounting_rate_ml: 6, last_accounting_evidence: 'user_calibration', last_accounting_reason: null },
    'vacuum.a245': { initialized: true, used_ml: 20, last_reset_iso: '2026-08-30T10:00:00+00:00' },
    'vacuum.paused': { initialized: true, used_ml: 20, last_reset_iso: '2026-08-30T10:00:00+00:00', last_accounting_source: 'area', last_accounting_reason: 'missing_area_rate' },
    'vacuum.hostile': { initialized: true, used_ml: 1, last_reset_iso: '2026-08-30T10:00:00+00:00' }
  };
  try {
    stub(window);
    window.eval(fs.readFileSync(target.file, 'utf8'));
    const el = window.document.createElement(target.tag);
    const hass = mockHass({
      states: {
        'vacuum.a170': { entity_id: 'vacuum.a170', state: 'docked', attributes: {} },
        'vacuum.a245': { entity_id: 'vacuum.a245', state: 'docked', attributes: {} },
        'vacuum.paused': { entity_id: 'vacuum.paused', state: 'docked', attributes: {} },
        'vacuum.conflict': { entity_id: 'vacuum.conflict', state: 'docked', attributes: {} },
        'vacuum.hostile': { entity_id: 'vacuum.hostile', state: 'docked', attributes: {} },
        'vacuum.native_one': { entity_id: 'vacuum.native_one', state: 'docked', attributes: {} },
        'vacuum.matter_two': { entity_id: 'vacuum.matter_two', state: 'docked', attributes: {} },
        'sensor.a170_status': { entity_id: 'sensor.a170_status', state: 'washing_the_mop', attributes: {} },
        'sensor.a170_area': { entity_id: 'sensor.a170_area', state: '12', attributes: {} },
        'sensor.a245_status': { entity_id: 'sensor.a245_status', state: 'cleaning', attributes: {} },
        'sensor.a245_area': { entity_id: 'sensor.a245_area', state: '8', attributes: {} }
      },
      entities: {
        'vacuum.native_one': { platform: 'roborock', device_id: 'native' },
        'vacuum.matter_two': { platform: 'matter', device_id: 'matter' }
      },
      devices: { native: { manufacturer: 'Roborock' }, matter: { manufacturer: 'Roborock' } },
      callWS: async (message) => {
        calls.push(message);
        if (message.type.endsWith('/get_state')) return { settings, tank_states };
        if (message.type.endsWith('/list_vacuums')) return { vacuums: descriptors };
        if (message.type.endsWith('/set_settings')) { settings = { ...settings, ...(message.patch || {}) }; return { settings }; }
        return {};
      }
    });
    el.setConfig({ type: 'custom:' + target.tag, devices: [
      { vacuum_entity: 'vacuum.a170', brand_profile: 'roborock_s8_maxv_ultra' },
      { vacuum_entity: 'vacuum.a245' },
      { vacuum_entity: 'vacuum.paused' },
      { vacuum_entity: 'vacuum.conflict' },
      { vacuum_entity: 'vacuum.hostile' },
      { vacuum_entity: 'vacuum.yaml_capacity', water_total_ml: 4300, signals: {} }
    ] });
    window.document.body.appendChild(el); el.hass = hass;
    await el._ensureServerState(); await delay(0);

    const devices = el._getDevices();
    const a170 = devices.find(d => d.vacuum_entity === 'vacuum.a170');
    const a245 = devices.find(d => d.vacuum_entity === 'vacuum.a245');
    const paused = devices.find(d => d.vacuum_entity === 'vacuum.paused');
    const conflict = devices.find(d => d.vacuum_entity === 'vacuum.conflict');
    const hostile = devices.find(d => d.vacuum_entity === 'vacuum.hostile');
    const yaml = devices.find(d => d.vacuum_entity === 'vacuum.yaml_capacity');
    const a170Data = el._calcDeviceData(a170);
    if (a170Data.totalMl !== 4200) throw new Error('effective default/profile/entity calibration did not win in rendered capacity');
    el._activeDeviceIdx = devices.indexOf(a170); el._activeTab = 'water'; el._lastHtml = ''; el._render();
    const a170Dom = el.shadowRoot.textContent;
    if (!a170Dom.includes('Measured calibration active') || a170Dom.includes('Add calibration')) throw new Error('active measured manual accounting guidance is inaccurate');
    if (!a170Dom.includes('sensor.a170_status') || !a170Dom.includes('4,200 ml')) throw new Error('a170 diagnostics are not rendered');
    const legacyConflict = el._withExplicitKeys({ vacuum_entity: 'vacuum.conflict', water_total_ml: 4100 }, []);
    const calibrationBeforeConflict = el._serverState.settings.custom_calibration;
    el._serverState.settings.custom_calibration = {};
    const conflictData = el._calcDeviceData(legacyConflict);
    const conflictHtml = el._buildWaterTab(conflict, conflictData);
    el._serverState.settings.custom_calibration = calibrationBeforeConflict;
    if (conflictData.totalMl !== 4000 || !conflictHtml.includes('4.0 L') || conflictHtml.includes('4.1 L')) throw new Error(`backend descriptor capacity did not override legacy client profile capacity (${conflictData.totalMl})`);
    el._activeDeviceIdx = devices.indexOf(a245); el._lastHtml = ''; el._render();
    if (!el.shadowRoot.textContent.includes('sensor.a245_status') || !el.shadowRoot.textContent.includes('sensor.a245_area')) throw new Error('a245 raw same-device signals are not rendered');
    el._activeDeviceIdx = devices.indexOf(paused); el._lastHtml = ''; el._render();
    if (!/Missing rate/.test(el.shadowRoot.textContent) || /Active automatic estimate/.test(el.shadowRoot.textContent)) throw new Error('paused automatic accounting guidance is inaccurate');
    el._activeDeviceIdx = devices.indexOf(hostile); el._lastHtml = ''; el._render();
    if (el.shadowRoot.querySelector('[data-vwm-descriptor-xss]') || !el.shadowRoot.textContent.includes('<img data-vwm-descriptor-xss>')) throw new Error('hostile descriptor diagnostics were not escaped');
    const discoveredBeforeFallback = el._discoveredVacuums;
    el._discoveredVacuums = [];
    if (el._autoDiscoverVacuums().filter(d => d.entity_id === 'vacuum.native_one' || d.entity_id === 'vacuum.matter_two').length !== 2) throw new Error('old-backend fallback deduplicated separate same-manufacturer vacuums');
    el._discoveredVacuums = discoveredBeforeFallback;

    el._activeDeviceIdx = devices.indexOf(a170); el._activeTab = 'maintenance'; el._lastHtml = ''; el._render();
    el.shadowRoot.getElementById('vwm-custom-calibration-body').style.display = 'block';
    if (!/Effective dock clean capacity/.test(el.shadowRoot.textContent) || !el.shadowRoot.textContent.includes('4,200 ml')) throw new Error('calibration UI does not render effective tracked reservoir capacity');
    el.shadowRoot.getElementById('vwm-custom-tank').value = '4300';
    el.shadowRoot.getElementById('vwm-custom-wash').value = '220';
    el.shadowRoot.querySelector('.vwm-mode-name').value = 'measured';
    el.shadowRoot.querySelector('.vwm-mode-val').value = '6';
    if (!await el._saveCustomCalibration()) throw new Error('canonical calibration save failed');
    const patch = calls.filter(call => call.type.endsWith('/set_settings')).at(-1).patch.custom_calibration;
    const saved = patch['entity:vacuum.a170'];
    if (saved.tracked_capacity_ml !== 4300 || saved.wash_volume_ml !== 220 || saved.usage_ml_per_m2?.measured !== 6 || 'tank_ml' in saved || 'mop_wash_ml' in saved || 'water_per_m2' in saved || saved.preserve_me !== 'keep' || patch['entity:vacuum.other']?.tracked_capacity_ml !== 2222) throw new Error('calibration patch did not use canonical merged selected-record keys');
    if (el._calcDeviceData(yaml).totalMl !== 4300 || yaml.signals.status_sensor) throw new Error('explicit YAML capacity or empty signals opt-out lost precedence');
    el._discoveredVacuums = [];
    const calibrationBeforeOldBackend = el._serverState.settings.custom_calibration;
    el._serverState.settings.custom_calibration = {};
    const oldBackendHtml = el._buildWaterTab({ vacuum_entity: 'vacuum.a170' }, el._calcDeviceData({ vacuum_entity: 'vacuum.a170' }));
    el._serverState.settings.custom_calibration = calibrationBeforeOldBackend;
    if (!oldBackendHtml.includes('4.0 L')) throw new Error('old-backend model fallback is not rendered');
  } finally { window.close(); }
}

async function smokeFinalFixContracts(target) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
  });
  const { window } = dom;
  const calls = [];
  const descriptors = [
    { entity_id: 'vacuum.a170', name: 'Qrevo', profile_key: 'roborock_qrevo_5ae', profile_source: 'model_id', capability: 'manual_only', tracked_reservoir: 'dock_clean', tracked_capacity_ml: 4000, signals: { area_sensor: 'sensor.a170_area' } },
    { entity_id: 'vacuum.numeric', name: 'Numeric', profile_key: 'generic', capability: 'manual_only', tracked_reservoir: 17, tracked_capacity_ml: 1000, signals: {} },
    { entity_id: 'vacuum.object', name: 'Object', profile_key: 'generic', capability: 'manual_only', tracked_reservoir: { hostile: '<img data-vwm-reservoir-xss>' }, tracked_capacity_ml: 1000, signals: {} }
  ];
  const settings = {
    user_devices: [
      { vacuum_entity: 'vacuum.numeric', name: 'Numeric' },
      { vacuum_entity: 'vacuum.object', name: 'Object' }
    ]
  };
  try {
    stub(window);
    window.eval(fs.readFileSync(target.file, 'utf8'));
    const el = window.document.createElement(target.tag);
    const hass = mockHass({
      states: {
        'vacuum.a170': { entity_id: 'vacuum.a170', state: 'docked', attributes: {} },
        'vacuum.numeric': { entity_id: 'vacuum.numeric', state: 'docked', attributes: {} },
        'vacuum.object': { entity_id: 'vacuum.object', state: 'docked', attributes: {} }
      },
      callWS: async (message) => {
        calls.push(message);
        if (message.type.endsWith('/get_state')) return {
          settings,
          tank_states: {
            'vacuum.a170': { used_ml: 0, last_reset_ts: 1788084000000, last_accounting_reason: 'status_unavailable' },
            'vacuum.numeric': { used_ml: 0, last_reset_ts: 1788084000000 },
            'vacuum.object': { used_ml: 0, last_reset_ts: 1788084000000 }
          }
        };
        if (message.type.endsWith('/list_vacuums')) return { vacuums: descriptors };
        if (message.type.endsWith('/set_settings')) return { settings: { ...settings, ...(message.patch || {}) } };
        return {};
      }
    });
    el.setConfig({
      type: 'custom:' + target.tag,
      vacuum_entity: 'vacuum.a170',
      brand_profile: 'roborock_s8_maxv_ultra',
      water_total_ml: 3100,
      signals: {},
      status_sensor: 'sensor.user_status',
      usage_ml_per_m2: { measured: 7 },
      wash_volume_ml: 123,
      accounting_evidence: 'user_measurement',
      tracked_reservoir: 'robot_clean',
      profile_locked: true
    });
    window.document.body.appendChild(el); el.hass = hass;
    await el._ensureServerState(); await delay(0);

    const configuredCall = calls.find(call => call.type.endsWith('/set_settings') && call.patch?.configured_devices);
    if (!configuredCall) throw new Error('single-device YAML was not persisted');
    const stored = configuredCall.patch.configured_devices[0];
    if (stored.dock_error_sensor || stored.main_brush_sensor) throw new Error('single-device YAML persisted legacy profile expansion');
    for (const key of ['water_total_ml', 'signals', 'status_sensor', 'usage_ml_per_m2', 'wash_volume_ml', 'accounting_evidence', 'tracked_reservoir', 'profile_locked', 'brand_profile']) {
      if (!stored.config_provenance?.authored_fields?.includes(key)) throw new Error(`authored provenance omitted ${key}`);
    }

    const timestampOnly = el._calcDeviceData(el._getDevices().find(d => d.vacuum_entity === 'vacuum.a170'));
    if (!timestampOnly.initialized || timestampOnly.usedMl !== 0 || timestampOnly.percentRemaining !== 100 || !timestampOnly.lastReset) {
      throw new Error('finite positive timestamp-only Store state was not initialized');
    }
    if (!/Unavailable signal/i.test(el._buildAccountingGuidance(timestampOnly))) {
      throw new Error('status-unavailable accounting reason rendered as ready');
    }

    const legacyLocked = el._withBackendDescriptor(el._decorateLegacyProfile({
      vacuum_entity: 'vacuum.a170',
      brand_profile: 'roborock_s8_maxv_ultra',
      profile_locked: true,
    }));
    if (el._calcDeviceData(legacyLocked).totalMl !== 4000) {
      throw new Error('legacy profile lock without provenance did not control frontend capacity');
    }

    const falseySignals = el._withBackendDescriptor({
      vacuum_entity: 'vacuum.a170',
      status_sensor: '',
      area_sensor: null,
      config_provenance: { authored_fields: ['vacuum_entity', 'status_sensor', 'area_sensor'] },
      __vwmExplicitKeys: ['vacuum_entity', 'status_sensor', 'area_sensor'],
      __vwmGeneratedKeys: [],
    });
    if (falseySignals.status_sensor !== '' || falseySignals.area_sensor !== null) {
      throw new Error('authored falsey direct signal opt-out was overwritten by registry');
    }
    if (falseySignals.signals?.status_sensor || falseySignals.signals?.area_sensor) {
      throw new Error('authored falsey direct signal opt-out remained in effective signals');
    }

    el._userDevices = [{
      vacuum_entity: 'vacuum.a170',
      config_provenance: { authored_fields: ['vacuum_entity'] },
    }];
    el._upsertUserDevicePatch(el._userDevices[0], { reset_door_sensor: 'binary_sensor.refill_door' });
    if (!el._userDevices[0].config_provenance?.authored_fields?.includes('reset_door_sensor')) {
      throw new Error('user-device patch did not add reset door to authored provenance');
    }
    el._upsertUserDevicePatch(el._userDevices[0], { reset_door_sensor: null });
    if (!el._userDevices[0].config_provenance?.authored_fields?.includes('reset_door_sensor')) {
      throw new Error('null user-device opt-out lost authored provenance');
    }

    for (const entity of ['vacuum.numeric', 'vacuum.object']) {
      const device = el._getDevices().find(d => d.vacuum_entity === entity);
      const html = el._buildMaintenanceTab(device, el._calcDeviceData(device));
      if (!html.includes('Tracked reservoir') && !html.includes('Effective')) throw new Error(`${entity} diagnostics did not render`);
      const holder = window.document.createElement('div'); holder.innerHTML = html;
      if (holder.querySelector('[data-vwm-reservoir-xss]')) throw new Error(`${entity} hostile reservoir created markup`);
    }

    el._userDevices = [];
    if (!el._addUserDevice('vacuum.numeric')) throw new Error('manual device add failed');
    const added = el._userDevices[0];
    if (added.water_total_ml || added.area_sensor || added.dock_error_sensor) throw new Error('manual device add persisted a legacy profile expansion');
    if (!added.config_provenance?.authored_fields?.includes('vacuum_entity')) throw new Error('manual device add omitted provenance');
  } finally { window.close(); }
}

(async () => {
  const files = listCardFiles();
  const targets = [];
  for (const f of files) {
    const code = fs.readFileSync(f, 'utf8');
    if (code.includes('window.HAToolsBentoCSS')) { console.error('smoke: residual global Bento CSS singleton'); process.exit(1); }
    for (const t of tagsIn(code)) targets.push({ file: f, tag: t });
  }
  if (!targets.length) { console.log('smoke: no custom elements found — skipping'); process.exit(0); }
  let pass = 0; const fail = [];
  for (const t of targets) {
    let problem = null;
    try {
      const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' });
      const { window } = dom;
      stub(window);
      window.HAToolsBentoCSS = '/* poisoned-ha-tools-bento-css */';
      let asyncErr = null;
      window.addEventListener('error', e => { asyncErr = asyncErr || (e.error && e.error.message) || e.message; });
      window.onerror = (m) => { asyncErr = asyncErr || m; };
      window.eval(fs.readFileSync(t.file, 'utf8'));
      const el = window.document.createElement(t.tag);
      if (typeof el.setConfig === 'function') el.setConfig({ type: 'custom:' + t.tag });
      el.hass = mockHass();
      window.document.body.appendChild(el);
      el.hass = mockHass();
      await delay(250);
      const len = el.shadowRoot ? el.shadowRoot.innerHTML.length : 0;
      if (!el.shadowRoot) problem = 'no shadowRoot';
      else if (len < 50) problem = 'empty render (len=' + len + ')';
      else if (el.shadowRoot.innerHTML.includes('poisoned-ha-tools-bento-css')) problem = 'pre-seeded global Bento CSS overrode component-local CSS';
      else if (asyncErr) problem = 'async error: ' + asyncErr;
      window.close();
    } catch (e) { problem = (e && e.message) ? e.message : String(e); }
    if (problem) fail.push(`${t.tag}  (${path.basename(t.file)})  -> ${problem}`); else pass++;
  }

  for (const t of targets.filter(t => t.tag === 'ha-vacuum-water-monitor')) {
    try {
      await smokeHostileIcons(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} hostile-icon-boundaries (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  for (const t of targets.filter(t => t.tag === 'ha-vacuum-water-monitor')) {
    try {
      await smokeRoundOneDescriptorContracts(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} round-one-contracts (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  for (const t of targets.filter(t => t.tag === 'ha-vacuum-water-monitor')) {
    try {
      await smokeDraftAndCalibration(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} draft/calibration (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  for (const t of targets.filter(t => t.tag === 'ha-vacuum-water-monitor')) {
    try {
      await smokeBackendDescriptorsAndTruthfulAccounting(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} backend-descriptors/accounting (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  for (const t of targets.filter(t => t.tag === 'ha-vacuum-water-monitor')) {
    try {
      await smokeFinalFixContracts(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} final-fix-contracts (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  console.log(`smoke: ${targets.length} element(s) | PASS ${pass} | FAIL ${fail.length}`);
  fail.forEach(f => console.log('  FAIL ' + f));
  process.exit(fail.length ? 1 : 0);
})();
