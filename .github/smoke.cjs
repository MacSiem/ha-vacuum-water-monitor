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
    if (!scoped || scoped.tank_ml !== 4123) throw new Error('calibration was not scoped to the active device');
    if (scoped.mop_wash_ml !== 175 || scoped.water_per_m2?.standard !== 5.5) {
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

(async () => {
  const files = listCardFiles();
  const targets = [];
  for (const f of files) {
    const code = fs.readFileSync(f, 'utf8');
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
      await smokeDraftAndCalibration(t);
      pass++;
    } catch (e) {
      fail.push(`${t.tag} draft/calibration (${path.basename(t.file)}) -> ${(e && e.message) ? e.message : String(e)}`);
    }
  }
  console.log(`smoke: ${targets.length} element(s) | PASS ${pass} | FAIL ${fail.length}`);
  fail.forEach(f => console.log('  FAIL ' + f));
  process.exit(fail.length ? 1 : 0);
})();
