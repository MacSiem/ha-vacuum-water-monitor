// Runtime render smoke (jsdom) — instantiates this repo's card(s) with a mock hass
// and fails if a card throws or renders nothing. Catches runtime errors that
// `node --check` cannot (e.g. a render() calling an undefined method).
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');
const ROOT = process.cwd();
const VWM_SUBSCRIBE_STATE = 'ha_vacuum_water_monitor/subscribe_state';

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
function mockHass() {
  const connection = {
    subscribeEventsCalls: 0,
    subscribeMessageCalls: [],
    subscribeEvents() {
      this.subscribeEventsCalls++;
      return Promise.resolve(() => {});
    },
    subscribeMessage(callback, message) {
      this.subscribeMessageCalls.push({ callback, message });
      return Promise.resolve(() => {});
    },
    sendMessagePromise: () => Promise.resolve([]), socket: { readyState: 1 }
  };
  return {
    states: {}, themes: { darkMode: false, themes: {} }, language: 'en',
    locale: { language: 'en', number_format: 'language', time_format: '24' },
    user: { id: 'u', name: 'Demo', is_admin: true, is_owner: true },
    config: { unit_system: { temperature: 'C' }, version: '2025.6.0' },
    callApi: () => Promise.resolve({}), callService: () => Promise.resolve({}),
    callWS: () => Promise.resolve([]), sendWS: () => Promise.resolve([]),
    formatEntityState: (s) => (s && s.state != null) ? String(s.state) : '',
    formatEntityAttributeValue: () => '',
    connection,
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

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function recordsEqual(actual, expected) {
  if (!actual || Object.keys(actual).length !== Object.keys(expected).length) return false;
  return Object.entries(expected).every(([key, value]) => actual[key] === value);
}

function assertIntegrationSubscriptionUsage(hass, expectedCalls, context) {
  const connection = hass.connection;
  assert(connection.subscribeEventsCalls === 0, `${context} used legacy subscribeEvents ${connection.subscribeEventsCalls} time(s)`);
  assert(connection.subscribeMessageCalls.length === expectedCalls, `${context} called subscribeMessage ${connection.subscribeMessageCalls.length} time(s), expected ${expectedCalls}`);
  connection.subscribeMessageCalls.forEach(({ message }) => {
    assert(
      message && message.type === VWM_SUBSCRIBE_STATE && Object.keys(message).length === 1,
      `${context} used the wrong subscription command: ${JSON.stringify(message)}`,
    );
  });
}

function createDom(file) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' });
  const { window } = dom;
  stub(window);
  let asyncErr = null;
  window.addEventListener('error', e => { asyncErr = asyncErr || (e.error && e.error.message) || e.message; });
  window.onerror = (m) => { asyncErr = asyncErr || m; };
  window.eval(fs.readFileSync(file, 'utf8'));
  return { dom, window, getAsyncError: () => asyncErr };
}

async function focusRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const wsCalls = [];
    const operations = [];
    const subscriptions = new Map();
    let subscribeAttempts = 0;
    const hass = mockHass();
    hass.callWS = (message) => {
      wsCalls.push(message);
      operations.push(message.type);
      if (message.type.endsWith('/get_state')) {
        return Promise.resolve({ settings: {}, tank_states: {} });
      }
      if (message.type.endsWith('/list_vacuums')) {
        return Promise.resolve({ vacuums: [] });
      }
      if (message.type.endsWith('/set_settings')) {
        return Promise.resolve({ settings: message.patch || {} });
      }
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscribeAttempts++;
      operations.push('subscribeMessage:' + message.type);
      subscriptions.set(message.type, callback);
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({ type: 'custom:' + tag, default_tab: 'maintenance' });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);

    const countWS = suffix => wsCalls.filter(call => call.type.endsWith(suffix)).length;
    assert(countWS('/get_state') === 1, `initial hydration called get_state ${countWS('/get_state')} time(s), expected once`);
    assert(countWS('/list_vacuums') === 1, `initial hydration called list_vacuums ${countWS('/list_vacuums')} time(s), expected once`);
    const subscribeIndex = operations.indexOf('subscribeMessage:' + VWM_SUBSCRIBE_STATE);
    const snapshotIndex = operations.findIndex(operation => operation.endsWith('/get_state'));
    assert(subscribeIndex !== -1 && subscribeIndex < snapshotIndex, 'initial hydration read get_state before establishing the Store event subscription');
    assertIntegrationSubscriptionUsage(hass, 1, 'normal hydration');

    const maintName = el.shadowRoot && el.shadowRoot.querySelector('#maint-name');
    assert(maintName, 'maintenance tab did not render #maint-name');
    maintName.value = 'Clean sensor draft';
    maintName.focus();
    assert(el.shadowRoot.activeElement === maintName, '#maint-name could not receive focus before hass updates');
    let blurCount = 0;
    maintName.addEventListener('blur', () => { blurCount++; });

    // Home Assistant assigns hass frequently, even when the entities relevant to
    // this card did not change. Let each assignment settle so a re-fetch cannot
    // hide behind an in-flight-promise guard.
    for (let i = 0; i < 3; i++) {
      el.hass = hass;
      await delay(10);
    }

    assert(countWS('/get_state') === 1, `repeated hass assignments called get_state ${countWS('/get_state')} time(s), expected once total`);
    assert(countWS('/list_vacuums') === 1, `repeated hass assignments called list_vacuums ${countWS('/list_vacuums')} time(s), expected once total`);
    assert(subscribeAttempts === 1, `stable event subscription attempted ${subscribeAttempts} time(s), expected once`);
    assert(el.shadowRoot.querySelector('#maint-name') === maintName, 'repeated hass assignments replaced #maint-name');
    assert(blurCount === 0, `repeated hass assignments blurred #maint-name ${blurCount} time(s)`);
    assert(maintName.value === 'Clean sensor draft', 'repeated hass assignments cleared the #maint-name draft');
    assert(el.shadowRoot.activeElement === maintName, 'repeated hass assignments moved focus away from #maint-name');

    const serverEvent = subscriptions.get(VWM_SUBSCRIBE_STATE);
    assert(serverEvent, 'card did not subscribe to the integration-owned state stream');
    serverEvent({
      settings: {
        maintenance_items: [{ name: 'Server item', icon: '🔧', intervalDays: 30, lastDone: Date.now() }],
      },
    });
    await delay(0);
    const maintAfterEvent = el.shadowRoot.querySelector('#maint-name');
    assert(el.shadowRoot.querySelector('.custom-maint-row'), 'server settings event did not update maintenance content');
    assert(maintAfterEvent && maintAfterEvent.value === 'Clean sensor draft', 'server settings event cleared the active maintenance draft');
    assert(el.shadowRoot.activeElement === maintAfterEvent, 'server settings event moved focus away from the maintenance draft');

    const calibrationBody = el.shadowRoot.querySelector('#vwm-custom-calibration-body');
    const tankInput = el.shadowRoot.querySelector('#vwm-custom-tank');
    assert(calibrationBody && tankInput, 'custom calibration tank form did not render');
    calibrationBody.style.display = 'block';
    tankInput.value = '4321';
    tankInput.focus();
    serverEvent({
      settings: {
        custom_calibration: {
          'vacuum.unknown_model': {
            tank_ml: 4321,
            water_per_m2: { '<img src=x onerror=alert(1)>': 12 },
            notes: '<img src=x onerror=alert(2)>',
          },
          'vacuum.roborock_s8_maxv_ultra': { tank_ml: 4321 },
          roborock_s8_pro_ultra: { tank_ml: 4444 },
          default: { tank_ml: 999 },
        },
        maintenance_items: [
          { name: 'Server item', icon: '🔧', intervalDays: 30, lastDone: Date.now() },
          { name: 'Another server item', icon: '🧹', intervalDays: 14, lastDone: Date.now() },
        ],
      },
    });
    await delay(0);
    const calibrationAfterEvent = el.shadowRoot.querySelector('#vwm-custom-calibration-body');
    const tankAfterEvent = el.shadowRoot.querySelector('#vwm-custom-tank');
    assert(el.shadowRoot.querySelectorAll('.custom-maint-row').length === 2, 'second server settings event did not update visible maintenance content');
    assert(calibrationAfterEvent && calibrationAfterEvent.style.display === 'block', 'server settings event collapsed the custom calibration panel');
    assert(tankAfterEvent && tankAfterEvent.value === '4321', 'server settings event cleared the custom tank draft');
    assert(el.shadowRoot.activeElement === tankAfterEvent, 'server settings event moved focus away from the custom tank draft');
    assert(el._calcDeviceData({ vacuum_entity: 'vacuum.unknown_model' }).totalMl === 4321, 'card display did not use the saved custom tank capacity');
    assert(el._calcDeviceData({ vacuum_entity: 'vacuum.other_model' }).totalMl === 999, 'legacy default calibration fallback stopped working');
    assert(el._calcDeviceData({
      vacuum_entity: 'vacuum.roborock_s8_maxv_ultra',
      brand_profile: 'roborock_s8_maxv_ultra',
      water_total_ml: 3000,
      water_total_source: 'profile',
    }).totalMl === 4321, 'custom tank calibration did not override a built-in profile capacity');
    assert(el._calcDeviceData({
      vacuum_entity: 'vacuum.roborock_s8_maxv_ultra',
      brand_profile: 'roborock_s8_maxv_ultra',
      water_total_ml: 2750,
      water_total_source: 'config',
    }).totalMl === 2750, 'custom tank calibration overrode an explicit YAML capacity');
    assert(el._calcDeviceData({
      vacuum_entity: 'vacuum.roborock_s8_pro_ultra',
    }).totalMl === 4444, 'legacy profile calibration was not inferred from the vacuum entity id');
    const unsafeDevice = { vacuum_entity: 'vacuum.unknown_model' };
    const waterHtml = el._buildWaterTab(unsafeDevice, el._calcDeviceData(unsafeDevice));
    assert(!waterHtml.includes('<img'), 'custom calibration rendered stored HTML without escaping');
    assert(waterHtml.includes('&lt;img'), 'custom calibration mode name was not safely escaped');

    // Draft preservation must not depend on a field still having focus. Users
    // often click the panel header or Add mode before the next HA update.
    el._addCustomMode();
    const modeNames = el.shadowRoot.querySelectorAll('.vwm-mode-name');
    const modeValues = el.shadowRoot.querySelectorAll('.vwm-mode-val');
    modeNames[3].value = 'detail';
    modeValues[3].value = '12';
    tankAfterEvent.blur();
    serverEvent({
      settings: {
        custom_calibration: { default: { tank_ml: 4321 } },
        maintenance_items: [
          { name: 'Server item', intervalDays: 30, lastDone: Date.now() },
          { name: 'Another server item', intervalDays: 14, lastDone: Date.now() },
          { name: 'Third server item', intervalDays: 7, lastDone: Date.now() },
        ],
      },
    });
    await delay(0);
    assert(el.shadowRoot.querySelectorAll('.custom-maint-row').length === 3, 'unfocused server update did not render');
    assert(el.shadowRoot.querySelector('#vwm-custom-calibration-body').style.display === 'block', 'unfocused server update collapsed the calibration panel');
    assert(el.shadowRoot.querySelector('#vwm-custom-tank').value === '4321', 'unfocused server update cleared the tank draft');
    assert(el.shadowRoot.querySelectorAll('.vwm-mode-name').length === 4, 'unfocused server update removed an added custom mode');
    assert(el.shadowRoot.querySelectorAll('.vwm-mode-name')[3].value === 'detail', 'unfocused server update cleared the added mode name');
    assert(el.shadowRoot.querySelectorAll('.vwm-mode-val')[3].value === '12', 'unfocused server update cleared the added mode value');

    hass.states['vacuum.new_robot'] = {
      entity_id: 'vacuum.new_robot', state: 'docked', attributes: { friendly_name: 'New Robot' },
    };
    assert(el._getDevices().some(device => device.vacuum_entity === 'vacuum.new_robot'), 'live discovery did not include a newly added vacuum');
    delete hass.states['vacuum.new_robot'];
    assert(!el._getDevices().some(device => device.vacuum_entity === 'vacuum.new_robot'), 'live discovery kept a removed vacuum from the initial cache');

    const editorTag = tag + '-editor';
    assert(window.customElements.get(editorTag), `${editorTag} was not registered`);
    const editor = window.document.createElement(editorTag);
    window.document.body.appendChild(editor);
    editor.setConfig({ type: 'custom:' + tag, title: 'Original title' });
    const titleInput = editor.shadowRoot.querySelector('#cf_title');
    assert(titleInput, 'visual editor did not render #cf_title');
    titleInput.focus();
    titleInput.value = 'Title being typed';
    let changedEvent = null;
    editor.addEventListener('config-changed', (event) => {
      changedEvent = event;
      // Lovelace sends the emitted config straight back to the editor.
      editor.setConfig(event.detail.config);
    });
    titleInput.dispatchEvent(new window.Event('input', { bubbles: true, composed: true }));
    await delay(0);
    const titleAfterRoundTrip = editor.shadowRoot.querySelector('#cf_title');
    assert(changedEvent, 'visual editor did not emit config-changed for title input');
    assert(changedEvent.detail.config.title === 'Title being typed', 'config-changed did not contain the typed title');
    assert(titleAfterRoundTrip === titleInput, 'config-changed/setConfig round-trip replaced the editor title input');
    assert(titleAfterRoundTrip.value === 'Title being typed', 'config-changed/setConfig round-trip changed the editor title value');
    assert(editor.shadowRoot.activeElement === titleInput, 'config-changed/setConfig round-trip moved focus away from the editor title input');

    assert(!getAsyncError(), 'async error during focus regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function hassStateRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const hass = mockHass();
    hass.states = {
      'vacuum.test_robot': {
        entity_id: 'vacuum.test_robot',
        state: 'docked',
        attributes: { friendly_name: 'Configured Robot', battery_level: 40 },
      },
      'vacuum.discovery_robot': {
        entity_id: 'vacuum.discovery_robot',
        state: 'docked',
        attributes: { friendly_name: 'Discovery Alpha', battery_level: 20 },
      },
      'sensor.filter_hours': {
        entity_id: 'sensor.filter_hours',
        state: '120',
        attributes: { friendly_name: 'Filter hours' },
      },
    };
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: {}, tank_states: {} });
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      if (message.type.endsWith('/set_settings')) return Promise.resolve({ settings: message.patch || {} });
      return Promise.resolve({});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      vacuum_entity: 'vacuum.test_robot',
      filter_time_sensor: 'sensor.filter_hours',
      default_tab: 'maintenance',
    });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assertIntegrationSubscriptionUsage(hass, 1, 'hass state refresh');

    const filterValue = () => {
      const row = Array.from(el.shadowRoot.querySelectorAll('.consumable-row'))
        .find(candidate => candidate.textContent.includes('Filter'));
      return row && row.querySelector('.con-val');
    };
    assert(filterValue() && filterValue().textContent.includes('5 days'), 'configured filter sensor did not render its initial value');
    const maintName = el.shadowRoot.querySelector('#maint-name');
    maintName.value = 'State update draft';
    maintName.focus();

    // Only the configured non-vacuum entity changes; vacuum.state stays docked.
    hass.states['sensor.filter_hours'] = {
      ...hass.states['sensor.filter_hours'],
      state: '5',
    };
    el._lastRenderTime = 0;
    el.hass = hass;
    await delay(0);
    const maintAfterSensor = el.shadowRoot.querySelector('#maint-name');
    assert(filterValue() && filterValue().textContent.includes('5h'), 'configured non-vacuum sensor change did not refresh visible maintenance data');
    assert(maintAfterSensor && maintAfterSensor.value === 'State update draft', 'configured sensor refresh cleared the active maintenance draft');
    assert(el.shadowRoot.activeElement === maintAfterSensor, 'configured sensor refresh moved focus away from the maintenance draft');

    el.setActiveTab('settings');
    const discoveryRow = () => el.shadowRoot.querySelector('.disc-row[data-entity="vacuum.discovery_robot"]');
    assert(discoveryRow() && discoveryRow().textContent.includes('Discovery Alpha'), 'discovered vacuum did not render its initial attributes');
    const manualInput = el.shadowRoot.querySelector('#manual-vacuum-entity');
    manualInput.value = 'vacuum.draft_robot';
    manualInput.focus();

    // The vacuum state remains docked; only attributes used by the visible row change.
    hass.states['vacuum.discovery_robot'] = {
      ...hass.states['vacuum.discovery_robot'],
      attributes: { friendly_name: 'Discovery Beta', battery_level: 87 },
    };
    el._lastRenderTime = 0;
    el.hass = hass;
    await delay(0);
    const manualAfterAttribute = el.shadowRoot.querySelector('#manual-vacuum-entity');
    assert(discoveryRow() && discoveryRow().textContent.includes('Discovery Beta'), 'vacuum attribute change did not refresh the visible discovery name');
    assert(discoveryRow().textContent.includes('87%'), 'vacuum attribute change did not refresh the visible battery value');
    assert(manualAfterAttribute && manualAfterAttribute.value === 'vacuum.draft_robot', 'vacuum attribute refresh cleared the active manual-device draft');
    assert(el.shadowRoot.activeElement === manualAfterAttribute, 'vacuum attribute refresh moved focus away from the manual-device draft');
    assert(!getAsyncError(), 'async error during hass state regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function configuredDevicePersistenceFailureRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    window.console.error = () => {};
    window.console.debug = () => {};
    window.console.warn = () => {};
    let getStateCalls = 0;
    let listVacuumCalls = 0;
    let configuredDeviceSaveCalls = 0;
    let subscribeCalls = 0;
    const hass = mockHass();
    hass.states = {
      'vacuum.persistence_robot': {
        entity_id: 'vacuum.persistence_robot',
        state: 'docked',
        attributes: { friendly_name: 'Persistence Robot' },
      },
    };
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        getStateCalls++;
        return Promise.resolve({
          settings: {
            maintenance_items: [{ name: 'Hydrated despite save failure', icon: '🔧', intervalDays: 30, lastDone: Date.now() }],
          },
          tank_states: {},
        });
      }
      if (message.type.endsWith('/list_vacuums')) {
        listVacuumCalls++;
        return Promise.resolve({ vacuums: [] });
      }
      if (message.type.endsWith('/set_settings')) {
        assert(
          message.patch && Array.isArray(message.patch.configured_devices),
          'hydration persisted an unexpected settings patch',
        );
        configuredDeviceSaveCalls++;
        return Promise.reject(new Error('expected configured_devices persistence failure'));
      }
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscribeCalls++;
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      vacuum_entity: 'vacuum.persistence_robot',
      device_name: 'Persistence Robot',
      default_tab: 'maintenance',
    });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);

    assert(getStateCalls === 1, `persistence-failure hydration called get_state ${getStateCalls} time(s), expected once`);
    assert(listVacuumCalls === 1, `persistence-failure hydration called list_vacuums ${listVacuumCalls} time(s), expected once`);
    assert(configuredDeviceSaveCalls === 1, `configured_devices persistence was attempted ${configuredDeviceSaveCalls} time(s), expected once`);
    assert(subscribeCalls === 1, `persistence-failure hydration subscribed ${subscribeCalls} time(s), expected once`);
    assertIntegrationSubscriptionUsage(hass, 1, 'configured-device persistence failure');
    assert(el._serverReady === true, 'configured_devices persistence failure left Store hydration unready');
    assert(el.shadowRoot.textContent.includes('Hydrated despite save failure'), 'configured_devices persistence failure prevented hydrated Store data from rendering');
    assert(el.shadowRoot.querySelector('.device-name')?.textContent.includes('Persistence Robot'), 'configured vacuum did not render after its persistence failed');

    const maintName = el.shadowRoot.querySelector('#maint-name');
    assert(maintName, 'maintenance draft field did not render after configured_devices persistence failed');
    maintName.value = 'Persistence failure draft';
    maintName.focus();
    let blurCount = 0;
    maintName.addEventListener('blur', () => { blurCount++; });
    for (let i = 0; i < 3; i++) {
      el.hass = hass;
      await delay(10);
    }

    assert(getStateCalls === 1, `repeated hass assignments retried get_state ${getStateCalls} time(s) after persistence failure`);
    assert(listVacuumCalls === 1, `repeated hass assignments retried list_vacuums ${listVacuumCalls} time(s) after persistence failure`);
    assert(configuredDeviceSaveCalls === 1, `repeated hass assignments retried configured_devices persistence ${configuredDeviceSaveCalls} time(s)`);
    assert(subscribeCalls === 1, `repeated hass assignments re-subscribed ${subscribeCalls} time(s) after persistence failure`);
    assert(el.shadowRoot.querySelector('#maint-name') === maintName, 'repeated hass assignments replaced the focused draft after persistence failure');
    assert(blurCount === 0, `repeated hass assignments blurred the draft ${blurCount} time(s) after persistence failure`);
    assert(maintName.value === 'Persistence failure draft', 'repeated hass assignments cleared the draft after persistence failure');
    assert(el.shadowRoot.activeElement === maintName, 'repeated hass assignments moved focus after persistence failure');
    assert(!getAsyncError(), 'async error during configured-device persistence failure regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function staleConfiguredDeviceSaveRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const freshSettings = {
      maintenance_items: [{ name: 'Fresh connection item', icon: '🧹', intervalDays: 14, lastDone: Date.now() }],
    };
    const staleSavedSettings = {
      maintenance_items: [{ name: 'Stale old save item', icon: '⚠️', intervalDays: 1, lastDone: Date.now() }],
    };
    let resolveOldConfiguredDeviceSave;
    const oldConfiguredDeviceSave = new Promise(resolve => { resolveOldConfiguredDeviceSave = resolve; });
    let oldGetStateCalls = 0;
    let oldListVacuumCalls = 0;
    let oldSaveCalls = 0;
    let freshGetStateCalls = 0;
    let freshListVacuumCalls = 0;
    let freshSaveCalls = 0;
    const vacuumState = {
      'vacuum.connection_robot': {
        entity_id: 'vacuum.connection_robot',
        state: 'docked',
        attributes: { friendly_name: 'Connection Robot' },
      },
    };

    const oldHass = mockHass();
    oldHass.states = vacuumState;
    oldHass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        oldGetStateCalls++;
        return Promise.resolve({ settings: { maintenance_items: [] }, tank_states: {} });
      }
      if (message.type.endsWith('/list_vacuums')) {
        oldListVacuumCalls++;
        return Promise.resolve({ vacuums: [] });
      }
      if (message.type.endsWith('/set_settings')) {
        assert(message.patch && Array.isArray(message.patch.configured_devices), 'old connection received an unexpected settings patch');
        oldSaveCalls++;
        return oldConfiguredDeviceSave;
      }
      return Promise.resolve({});
    };

    const freshHass = mockHass();
    freshHass.states = vacuumState;
    freshHass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        freshGetStateCalls++;
        return Promise.resolve({ settings: freshSettings, tank_states: {} });
      }
      if (message.type.endsWith('/list_vacuums')) {
        freshListVacuumCalls++;
        return Promise.resolve({ vacuums: [] });
      }
      if (message.type.endsWith('/set_settings')) {
        assert(message.patch && Array.isArray(message.patch.configured_devices), 'fresh connection received an unexpected settings patch');
        freshSaveCalls++;
        return Promise.resolve({ settings: freshSettings });
      }
      return Promise.resolve({});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      vacuum_entity: 'vacuum.connection_robot',
      device_name: 'Connection Robot',
      default_tab: 'maintenance',
    });
    window.document.body.appendChild(el);
    el.hass = oldHass;
    await delay(25);
    assert(oldGetStateCalls === 1 && oldListVacuumCalls === 1, 'old connection did not reach configured_devices persistence after its snapshot reads');
    assert(oldSaveCalls === 1, `old connection deferred configured_devices persistence ${oldSaveCalls} time(s), expected once`);
    assertIntegrationSubscriptionUsage(oldHass, 1, 'old deferred-save connection');

    // Replace the connection while its configured_devices write is unresolved.
    // The new generation must be allowed to finish and become authoritative.
    el.hass = freshHass;
    await delay(25);
    assert(freshGetStateCalls === 1, `fresh connection called get_state ${freshGetStateCalls} time(s), expected once`);
    assert(freshListVacuumCalls === 1, `fresh connection called list_vacuums ${freshListVacuumCalls} time(s), expected once`);
    assert(freshSaveCalls === 1, `fresh connection persisted configured_devices ${freshSaveCalls} time(s), expected once`);
    assertIntegrationSubscriptionUsage(freshHass, 1, 'fresh connection hydration');
    assert(el._serverReady === true, 'fresh connection did not complete hydration while the old save was pending');
    assert(el.shadowRoot.textContent.includes('Fresh connection item'), 'fresh connection Store state did not render');
    assert(!el.shadowRoot.textContent.includes('Stale old save item'), 'stale old save appeared before its response resolved');

    const maintName = el.shadowRoot.querySelector('#maint-name');
    maintName.value = 'Fresh connection draft';
    maintName.focus();
    resolveOldConfiguredDeviceSave({ settings: staleSavedSettings });
    await delay(25);

    assert(el._serverState.settings.maintenance_items?.[0]?.name === 'Fresh connection item', 'old configured_devices response overwrote the fresh internal Store state');
    assert(el.shadowRoot.textContent.includes('Fresh connection item'), 'old configured_devices response removed fresh rendered Store content');
    assert(!el.shadowRoot.textContent.includes('Stale old save item'), 'old configured_devices response rendered stale Store content');
    assert(el.shadowRoot.querySelector('#maint-name') === maintName, 'old configured_devices response replaced the fresh connection draft field');
    assert(maintName.value === 'Fresh connection draft', 'old configured_devices response cleared the fresh connection draft');
    assert(el.shadowRoot.activeElement === maintName, 'old configured_devices response moved focus from the fresh connection draft');
    assert(freshGetStateCalls === 1 && freshListVacuumCalls === 1 && freshSaveCalls === 1, 'old configured_devices completion restarted fresh hydration');
    assert(!getAsyncError(), 'async error during stale configured-device save regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function subscriptionRecoveryRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    window.console.debug = () => {};
    let serverSnapshot = { settings: { maintenance_items: [] }, tank_states: {} };
    let getStateCalls = 0;
    let subscribeAttempts = 0;
    const subscriptions = new Map();
    const hass = mockHass();
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        getStateCalls++;
        return Promise.resolve(serverSnapshot);
      }
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscribeAttempts++;
      if (subscribeAttempts === 1) return Promise.reject(new Error('transient subscription failure'));
      subscriptions.set(message.type, callback);
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({ type: 'custom:' + tag, default_tab: 'maintenance' });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assert(subscribeAttempts === 1, 'initial subscription failure was not exercised');
    assertIntegrationSubscriptionUsage(hass, 1, 'failed initial subscription');
    assert(getStateCalls === 1, `initial Store hydration called get_state ${getStateCalls} time(s), expected once`);
    assert(!el.shadowRoot.textContent.includes('Recovered missed item'), 'recovery item appeared before the missed Store update');

    const maintName = el.shadowRoot.querySelector('#maint-name');
    maintName.value = 'Recovery draft';
    maintName.focus();
    // This Store change occurs while no event subscription is active, so the
    // only way to observe it is a fresh snapshot after the retry succeeds.
    serverSnapshot = {
      settings: {
        maintenance_items: [{ name: 'Recovered missed item', icon: '🔧', intervalDays: 21, lastDone: Date.now() }],
      },
      tank_states: {},
    };
    el.hass = hass;
    await delay(25);

    const maintAfterRecovery = el.shadowRoot.querySelector('#maint-name');
    assert(subscribeAttempts === 2, `event subscription attempted ${subscribeAttempts} time(s), expected one successful retry`);
    assertIntegrationSubscriptionUsage(hass, 2, 'subscription recovery');
    assert(subscriptions.has(VWM_SUBSCRIBE_STATE), 'successful subscription retry did not install the integration-owned callback');
    assert(getStateCalls === 2, `subscription recovery called get_state ${getStateCalls} time(s), expected one recovery snapshot`);
    assert(el.shadowRoot.textContent.includes('Recovered missed item'), 'recovery snapshot did not render the Store update missed during subscription failure');
    assert(maintAfterRecovery && maintAfterRecovery.value === 'Recovery draft', 'recovery snapshot cleared the active maintenance draft');
    assert(el.shadowRoot.activeElement === maintAfterRecovery, 'recovery snapshot moved focus away from the maintenance draft');
    assert(!getAsyncError(), 'async error during subscription recovery regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function connectionReconnectRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  const unhandledRejections = [];
  const onUnhandledRejection = reason => { unhandledRejections.push(reason); };
  process.on('unhandledRejection', onUnhandledRejection);
  try {
    window.console.debug = () => {};
    let serverSnapshot = { settings: { maintenance_items: [] }, tank_states: {} };
    let getStateCalls = 0;
    const connectionListeners = new Map();
    const addedReadyHandlers = [];
    const removedReadyHandlers = [];
    let unsubscribeCalls = 0;
    const hass = mockHass();
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        getStateCalls++;
        return Promise.resolve(serverSnapshot);
      }
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      return Promise.resolve(() => {
        unsubscribeCalls++;
        return Promise.reject(new Error('expected async unsubscribe failure'));
      });
    };
    hass.connection.addEventListener = (eventType, callback) => {
      if (!connectionListeners.has(eventType)) connectionListeners.set(eventType, new Set());
      connectionListeners.get(eventType).add(callback);
      if (eventType === 'ready') addedReadyHandlers.push(callback);
    };
    hass.connection.removeEventListener = (eventType, callback) => {
      const listeners = connectionListeners.get(eventType);
      if (listeners) listeners.delete(callback);
      if (eventType === 'ready') removedReadyHandlers.push(callback);
    };
    const fireConnectionEvent = (eventType) => {
      const listeners = connectionListeners.get(eventType);
      if (listeners) Array.from(listeners).forEach(callback => callback());
    };

    const el = window.document.createElement(tag);
    el.setConfig({ type: 'custom:' + tag, default_tab: 'maintenance' });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);

    assert(getStateCalls === 1, `normal reconnect hydration called get_state ${getStateCalls} time(s), expected once`);
    assertIntegrationSubscriptionUsage(hass, 1, 'connection reconnect');
    assert(addedReadyHandlers.length === 1, `connection registered ${addedReadyHandlers.length} ready handler(s), expected one`);
    assert(connectionListeners.get('ready') && connectionListeners.get('ready').size === 1, 'connection did not retain exactly one ready listener');
    const maintName = el.shadowRoot.querySelector('#maint-name');
    maintName.value = 'Offline recovery draft';
    maintName.focus();

    // The Store changes while the socket is offline and no VWM event is
    // delivered. A connection-ready snapshot must close that event gap.
    hass.connection.socket.readyState = 0;
    serverSnapshot = {
      settings: {
        maintenance_items: [{ name: 'Offline missed item', icon: '🔧', intervalDays: 9, lastDone: Date.now() }],
      },
      tank_states: {},
    };
    hass.connection.socket.readyState = 1;
    fireConnectionEvent('ready');
    await delay(25);

    const maintAfterReady = el.shadowRoot.querySelector('#maint-name');
    assert(getStateCalls === 2, `connection ready produced ${getStateCalls - 1} catch-up get_state call(s), expected exactly one`);
    assert(el.shadowRoot.textContent.includes('Offline missed item'), 'connection-ready snapshot did not render the Store update missed while offline');
    assert(maintAfterReady && maintAfterReady.value === 'Offline recovery draft', 'connection-ready snapshot cleared the active maintenance draft');
    assert(el.shadowRoot.activeElement === maintAfterReady, 'connection-ready snapshot moved focus away from the maintenance draft');

    el.remove();
    assert(removedReadyHandlers.length === 1, `card removal removed ${removedReadyHandlers.length} ready handler(s), expected one`);
    assert(removedReadyHandlers[0] === addedReadyHandlers[0], 'card removal did not remove the originally registered ready handler');
    assert(!connectionListeners.get('ready') || connectionListeners.get('ready').size === 0, 'ready listener remained attached after card removal');
    fireConnectionEvent('ready');
    await delay(10);
    assert(getStateCalls === 2, 'detached card fetched a Store snapshot after a later ready event');
    assert(unsubscribeCalls === 1, `card removal invoked async unsubscribe ${unsubscribeCalls} time(s), expected once`);
    assert(unhandledRejections.length === 0, 'async unsubscribe rejection escaped as an unhandled rejection');
    assert(!getAsyncError(), 'async error during connection reconnect regression: ' + getAsyncError());
  } finally {
    process.removeListener('unhandledRejection', onUnhandledRejection);
    dom.window.close();
  }
}

async function sameConnectionReattachRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    let resolveInitialState;
    const pendingInitialState = new Promise(resolve => { resolveInitialState = resolve; });
    let getStateCalls = 0;
    let listVacuumCalls = 0;
    const subscriptionCallbacks = [];
    const unsubscribeCalls = [];
    const hass = mockHass();
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) {
        getStateCalls++;
        if (getStateCalls === 1) return pendingInitialState;
        return Promise.resolve({
          settings: {
            maintenance_items: [{ name: 'Fresh reattach item', icon: '🔧', intervalDays: 10, lastDone: Date.now() }],
          },
          tank_states: {},
        });
      }
      if (message.type.endsWith('/list_vacuums')) {
        listVacuumCalls++;
        return Promise.resolve({ vacuums: [] });
      }
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      const index = subscriptionCallbacks.length;
      subscriptionCallbacks.push(callback);
      unsubscribeCalls[index] = 0;
      return Promise.resolve(() => { unsubscribeCalls[index]++; });
    };

    const el = window.document.createElement(tag);
    el.setConfig({ type: 'custom:' + tag, default_tab: 'maintenance' });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(10);
    assert(getStateCalls === 1, `pending hydration started get_state ${getStateCalls} time(s), expected once`);
    assert(subscriptionCallbacks.length === 1, 'pending hydration did not establish its first state subscription');

    // Detach and reattach the same element with the same connection before the
    // first snapshot resolves. Connection identity alone cannot distinguish
    // these A→B→A-style lifecycle generations.
    el.remove();
    assert(unsubscribeCalls[0] === 1, `detach released the initial subscription ${unsubscribeCalls[0]} time(s), expected once`);
    window.document.body.appendChild(el);
    await delay(25);

    assertIntegrationSubscriptionUsage(hass, 2, 'same-connection reattach');
    assert(getStateCalls === 2, `reattach started get_state ${getStateCalls} time(s), expected one fresh hydration`);
    assert(listVacuumCalls === 2, `reattach called list_vacuums ${listVacuumCalls} time(s), expected once per hydration`);
    assert(el.shadowRoot.textContent.includes('Fresh reattach item'), 'fresh reattach hydration did not render its Store snapshot');

    // A queued callback and the late initial snapshot both belong to the old
    // generation and must be ignored even though the connection object matches.
    subscriptionCallbacks[0]({
      settings: {
        maintenance_items: [{ name: 'Stale callback item', intervalDays: 1, lastDone: Date.now() }],
      },
    });
    resolveInitialState({
      settings: {
        maintenance_items: [{ name: 'Stale hydration item', intervalDays: 1, lastDone: Date.now() }],
      },
      tank_states: {},
    });
    await delay(25);

    assert(getStateCalls === 2, 'late initial hydration triggered an extra Store snapshot');
    assert(el.shadowRoot.textContent.includes('Fresh reattach item'), 'stale same-connection generation replaced the fresh snapshot');
    assert(!el.shadowRoot.textContent.includes('Stale callback item'), 'detached generation callback updated the reattached card');
    assert(!el.shadowRoot.textContent.includes('Stale hydration item'), 'detached generation hydration updated the reattached card');
    assert(!getAsyncError(), 'async error during same-connection reattach regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function remoteRefillRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    let serverSettings = {
      refill_config: { test_robot: { buttonEntity: 'input_button.old_refill' } },
    };
    const subscriptions = new Map();
    const hass = mockHass();
    hass.states = {
      'vacuum.test_robot': {
        entity_id: 'vacuum.test_robot', state: 'docked', attributes: { friendly_name: 'Test Robot' },
      },
      'input_button.old_refill': {
        entity_id: 'input_button.old_refill', state: 'unknown', attributes: { friendly_name: 'Old refill helper' },
      },
      'input_button.new_refill': {
        entity_id: 'input_button.new_refill', state: 'unknown', attributes: { friendly_name: 'New refill helper' },
      },
    };
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: serverSettings, tank_states: {} });
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      if (message.type.endsWith('/set_settings')) {
        serverSettings = { ...serverSettings, ...(message.patch || {}) };
        return Promise.resolve({ settings: serverSettings });
      }
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscriptions.set(message.type, callback);
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      vacuum_entity: 'vacuum.test_robot',
      default_tab: 'water',
    });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assertIntegrationSubscriptionUsage(hass, 1, 'remote refill update');
    // Open Settings after hydration so the old selection is a genuine rendered
    // baseline, not a pre-hydration blank captured by the first Store snapshot.
    el.setActiveTab('settings');

    const refillSelect = el.shadowRoot.querySelector('#refill-btn-select');
    assert(
      refillSelect && refillSelect.value === 'input_button.old_refill',
      `initial refill_config selection did not render (value=${refillSelect && refillSelect.value}, config=${JSON.stringify(el._refillConfig)}, devices=${JSON.stringify(el._getDevices())})`,
    );
    refillSelect.focus();
    const serverEvent = subscriptions.get(VWM_SUBSCRIBE_STATE);
    assert(serverEvent, 'refill regression did not establish the integration-owned subscription');
    serverSettings = {
      ...serverSettings,
      refill_config: { test_robot: { buttonEntity: 'input_button.new_refill' } },
    };
    serverEvent({ settings: serverSettings });
    await delay(0);

    const refillAfterEvent = el.shadowRoot.querySelector('#refill-btn-select');
    assert(el._refillConfig.test_robot.buttonEntity === 'input_button.new_refill', 'remote refill_config was not applied to card state');
    assert(refillAfterEvent && refillAfterEvent.value === 'input_button.new_refill', 'captured old refill selection overwrote the remote refill_config update');
    assert(el.shadowRoot.activeElement === refillAfterEvent, 'remote refill_config update moved focus away from the refill select');
    assert(!getAsyncError(), 'async error during remote refill regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function deviceIdentityRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const deviceA = { vacuum_entity: 'vacuum.device_a', name: 'Device A', icon: '🤖' };
    const deviceB = { vacuum_entity: 'vacuum.device_b', name: 'Device B', icon: '🤖' };
    let serverSettings = {
      user_devices: [deviceA, deviceB],
      custom_calibration: {
        'vacuum.device_a': { tank_ml: 1111 },
        'vacuum.device_b': { tank_ml: 2222 },
      },
    };
    const subscriptions = new Map();
    const hass = mockHass();
    hass.states = {
      'vacuum.device_a': { entity_id: 'vacuum.device_a', state: 'docked', attributes: { friendly_name: 'Device A' } },
      'vacuum.device_b': { entity_id: 'vacuum.device_b', state: 'docked', attributes: { friendly_name: 'Device B' } },
    };
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: serverSettings, tank_states: {} });
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscriptions.set(message.type, callback);
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({ type: 'custom:' + tag, default_tab: 'maintenance' });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assertIntegrationSubscriptionUsage(hass, 1, 'device identity update');

    const deviceTabs = el.shadowRoot.querySelectorAll('.dtab');
    assert(deviceTabs.length === 2, `multi-device regression rendered ${deviceTabs.length} device tab(s), expected two`);
    deviceTabs[1].click();
    assert(el.shadowRoot.querySelector('.device-name').textContent.includes('Device B'), 'device B did not become the active device');

    const calibrationBody = el.shadowRoot.querySelector('#vwm-custom-calibration-body');
    const tankInput = el.shadowRoot.querySelector('#vwm-custom-tank');
    assert(calibrationBody && tankInput, 'device B calibration form did not render');
    calibrationBody.style.display = 'block';
    tankInput.value = '9876';
    tankInput.focus();
    assert(el.shadowRoot.activeElement === tankInput, 'device B tank draft could not receive focus');

    const serverEvent = subscriptions.get(VWM_SUBSCRIBE_STATE);
    assert(serverEvent, 'device identity regression did not establish the integration-owned subscription');
    // Device B disappears while index 1 is active. The same index now falls
    // back to A, so B's captured draft must not be transplanted into A's form.
    serverSettings = {
      user_devices: [deviceA],
      custom_calibration: { 'vacuum.device_a': { tank_ml: 1111 } },
    };
    serverEvent({ settings: serverSettings });
    await delay(0);

    const tankAfterRemoval = el.shadowRoot.querySelector('#vwm-custom-tank');
    const calibrationAfterRemoval = el.shadowRoot.querySelector('#vwm-custom-calibration-body');
    assert(el.shadowRoot.querySelectorAll('.dtab').length === 0, 'removed device B still appeared in device tabs');
    assert(el.shadowRoot.querySelector('.device-name').textContent.includes('Device A'), 'active device did not fall back to A after B was removed');
    assert(tankAfterRemoval && tankAfterRemoval.value !== '9876', `device B tank draft leaked into A (value=${tankAfterRemoval && tankAfterRemoval.value})`);
    assert(calibrationAfterRemoval && calibrationAfterRemoval.style.display === 'none', 'device B expanded calibration state leaked into A');
    assert(el.shadowRoot.activeElement !== tankAfterRemoval, 'device B tank focus was restored into A');
    assert(!tankInput.isConnected, 'device B tank input remained connected after the device changed');
    assert(!getAsyncError(), 'async error during device identity regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function savedCalibrationRoundTripRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const unsafeMode = '<img src=x onerror=window.__calibrationXss=true>';
    const savedModes = {
      low: 4,
      normal: 7,
      deep: 12,
      max: 16,
      [unsafeMode]: 9,
    };
    let serverSettings = {
      custom_calibration: {
        'vacuum.calibration_robot': {
          tank_ml: 3200,
          robot_tank_ml: 350,
          mop_wash_ml: 175,
          avg_area_per_charge: 240,
          water_per_m2: { ...savedModes },
          mop_modes: { ...savedModes },
        },
        'vacuum.other_robot': { tank_ml: 999 },
      },
    };
    let savedCalibrationPatch = null;
    window.__calibrationXss = false;
    const hass = mockHass();
    hass.states = {
      'vacuum.calibration_robot': {
        entity_id: 'vacuum.calibration_robot',
        state: 'docked',
        attributes: { friendly_name: 'Calibration Robot' },
      },
    };
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: serverSettings, tank_states: {} });
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      if (message.type.endsWith('/set_settings')) {
        if (message.patch && message.patch.custom_calibration) {
          savedCalibrationPatch = message.patch.custom_calibration;
        }
        serverSettings = { ...serverSettings, ...(message.patch || {}) };
        return Promise.resolve({ settings: serverSettings });
      }
      return Promise.resolve({});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      vacuum_entity: 'vacuum.calibration_robot',
      default_tab: 'maintenance',
    });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assertIntegrationSubscriptionUsage(hass, 1, 'saved calibration hydration');

    const sr = el.shadowRoot;
    const calibrationBody = sr.querySelector('#vwm-custom-calibration-body');
    calibrationBody.previousElementSibling.click();
    assert(calibrationBody.style.display === 'block', 'saved calibration panel did not open');
    assert(sr.querySelector('#vwm-custom-tank').value === '3200', 'saved dock tank was not prefilled');
    assert(sr.querySelector('#vwm-custom-robot-tank').value === '350', 'saved robot tank was not prefilled');
    assert(sr.querySelector('#vwm-custom-wash').value === '175', 'saved mop-wash volume was not prefilled');
    assert(sr.querySelector('#vwm-custom-area').value === '240', 'saved coverage was not prefilled');

    const modeNames = Array.from(sr.querySelectorAll('.vwm-mode-name'));
    const modeValues = Array.from(sr.querySelectorAll('.vwm-mode-val'));
    assert(modeNames.length === 5 && modeValues.length === 5, `saved calibration rendered ${modeNames.length} mode row(s), expected five`);
    const loadedModes = {};
    modeNames.forEach((input, index) => { loadedModes[input.value] = Number(modeValues[index].value); });
    assert(recordsEqual(loadedModes, savedModes), `saved modes were not prefilled intact: ${JSON.stringify(loadedModes)}`);
    assert(modeNames.some(input => input.value === unsafeMode), 'unsafe mode label was not preserved as an input value');
    assert(!sr.querySelector('#vwm-custom-modes img'), 'saved mode label was interpreted as HTML');
    assert(window.__calibrationXss === false, 'saved mode label executed markup while prefilling');

    // Change exactly one field and use the real form action. Saving must merge
    // the edit with every untouched value that was loaded from the Store.
    sr.querySelector('#vwm-custom-tank').value = '3300';
    const saveButton = Array.from(sr.querySelectorAll('button'))
      .find(button => (button.getAttribute('onclick') || '').includes('_saveCustomCalibration'));
    assert(saveButton, 'custom calibration Save button did not render');
    saveButton.click();
    await delay(10);

    assert(savedCalibrationPatch, 'custom calibration Save did not persist settings');
    const persisted = savedCalibrationPatch['vacuum.calibration_robot'];
    assert(persisted && persisted.tank_ml === 3300, 'edited dock tank was not persisted');
    assert(persisted.robot_tank_ml === 350, 'saving dock tank discarded the saved robot tank');
    assert(persisted.mop_wash_ml === 175, 'saving dock tank discarded the saved mop-wash volume');
    assert(persisted.avg_area_per_charge === 240, 'saving dock tank discarded the saved coverage');
    assert(recordsEqual(persisted.water_per_m2, savedModes), 'saving one field discarded or changed saved water modes');
    assert(recordsEqual(persisted.mop_modes, savedModes), 'saving one field discarded or changed saved mop modes');
    assert(savedCalibrationPatch['vacuum.other_robot'].tank_ml === 999, 'saving one device discarded another device calibration');
    assert(!getAsyncError(), 'async error during saved calibration round-trip: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function storedStringXssRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const maintenanceIcon = '<img src=maintenance-icon onerror=window.__storedXss=true>';
    const userIcon = '<img src=user-icon onerror=window.__storedXss=true>';
    const userName = 'Stored <img src=user-name onerror=window.__storedXss=true>';
    const userEntity = 'vacuum.<img src=user-entity onerror=window.__storedXss=true>';
    const userWaterTotal = '<img src=user-water-total onerror=window.__storedXss=true>';
    const sessionArea = '<img src=session-area onerror=window.__storedXss=true>';
    const sessionWater = '<img src=session-water onerror=window.__storedXss=true>';
    const sessionDuration = '<img src=session-duration onerror=window.__storedXss=true>';
    let serverSettings = {};
    let subscriptionCallback = null;
    window.__storedXss = false;

    const hass = mockHass();
    hass.states = {};
    hass.callWS = (message) => {
      if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: serverSettings, tank_states: {} });
      if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
      if (message.type.endsWith('/set_settings')) {
        serverSettings = { ...serverSettings, ...(message.patch || {}) };
        return Promise.resolve({ settings: serverSettings });
      }
      return Promise.resolve({});
    };
    hass.connection.subscribeMessage = (callback, message) => {
      hass.connection.subscribeMessageCalls.push({ callback, message });
      subscriptionCallback = callback;
      return Promise.resolve(() => {});
    };

    const el = window.document.createElement(tag);
    el.setConfig({
      type: 'custom:' + tag,
      default_tab: 'maintenance',
    });
    window.document.body.appendChild(el);
    el.hass = hass;
    await delay(25);
    assertIntegrationSubscriptionUsage(hass, 1, 'stored-string security hydration');
    assert(subscriptionCallback, 'stored-string security regression did not establish a live Store subscription');

    serverSettings = {
      maintenance_items: [{
        name: 'Stored maintenance item',
        icon: maintenanceIcon,
        intervalDays: 30,
        lastDone: Date.now(),
      }],
      user_devices: [{
        vacuum_entity: userEntity,
        name: userName,
        icon: userIcon,
        water_total_ml: userWaterTotal,
      }],
      sessions: {
        [userEntity]: [{
          ts: Date.now(),
          area: sessionArea,
          water: sessionWater,
          duration: sessionDuration,
        }],
      },
    };
    subscriptionCallback({ settings: serverSettings });
    await delay(0);

    const sr = el.shadowRoot;
    const maintenanceRow = sr.querySelector('.custom-maint-row');
    assert(maintenanceRow, 'live Store maintenance item did not render');
    assert(maintenanceRow.textContent.includes(maintenanceIcon), 'stored maintenance icon did not render as literal text');
    assert(!maintenanceRow.querySelector('img'), 'stored maintenance icon created an img element');
    assert(window.__storedXss === false, 'stored maintenance icon executed its onerror handler');

    const activeStoreDevice = el._getDevices()[0];
    assert(activeStoreDevice && activeStoreDevice.water_total_ml === userWaterTotal, 'hostile Store water_total_ml did not reach the active user device');
    const activeStoreData = el._calcDeviceData(activeStoreDevice);
    assert(activeStoreData.totalMl === 0, `hostile Store water_total_ml became calculated total ${JSON.stringify(activeStoreData.totalMl)}`);
    el.setActiveTab('water');
    const waterContent = sr.querySelector('.tab-content');
    assert(waterContent && !waterContent.textContent.includes(userWaterTotal), 'hostile Store water_total_ml rendered as the displayed total');
    assert(!waterContent.querySelector('img'), 'hostile Store water_total_ml created an img element');
    assert(window.__storedXss === false, 'hostile Store water_total_ml executed its onerror handler');

    el.setActiveTab('settings');
    const userDeviceRow = sr.querySelector('.user-dev-remove')?.closest('.disc-row');
    assert(userDeviceRow, 'live Store user device did not render in Settings');
    [
      [userIcon, 'icon'],
      [userName, 'name'],
      [userEntity, 'entity'],
    ].forEach(([value, field]) => {
      assert(userDeviceRow.textContent.includes(value), `stored user-device ${field} did not render as literal text`);
    });
    assert(!userDeviceRow.querySelector('img'), 'stored user-device strings created an img element');
    assert(window.__storedXss === false, 'stored user-device string executed its onerror handler');

    el.setActiveTab('history');
    const sessionRow = sr.querySelector('.session-row');
    assert(sessionRow, 'live Store session did not render in History');
    [
      [sessionArea, 'area'],
      [sessionWater, 'water'],
      [sessionDuration, 'duration'],
    ].forEach(([value, field]) => {
      assert(sessionRow.textContent.includes(value), `stored session ${field} did not render as literal text`);
    });
    assert(!sessionRow.querySelector('img'), 'stored session strings created an img element');
    assert(window.__storedXss === false, 'stored session string executed its onerror handler');
    assert(!getAsyncError(), 'async error during stored-string security regression: ' + getAsyncError());
  } finally {
    dom.window.close();
  }
}

async function storeThresholdPrecedenceRegression(file, tag) {
  const { dom, window, getAsyncError } = createDom(file);
  try {
    const CardClass = window.customElements.get(tag);
    assert(CardClass && typeof CardClass.getStubConfig === 'function', 'card did not expose getStubConfig()');
    const stubConfig = CardClass.getStubConfig();
    assert(
      !Object.prototype.hasOwnProperty.call(stubConfig, 'warning_threshold'),
      'getStubConfig() pinned warning_threshold instead of inheriting integration Options',
    );
    assert(
      !Object.prototype.hasOwnProperty.call(stubConfig, 'critical_threshold'),
      'getStubConfig() pinned critical_threshold instead of inheriting integration Options',
    );

    const createThresholdCard = async (config, initialSettings, context) => {
      let subscriptionCallback = null;
      const hass = mockHass();
      hass.callWS = (message) => {
        if (message.type.endsWith('/get_state')) return Promise.resolve({ settings: initialSettings, tank_states: {} });
        if (message.type.endsWith('/list_vacuums')) return Promise.resolve({ vacuums: [] });
        return Promise.resolve({});
      };
      hass.connection.subscribeMessage = (callback, message) => {
        hass.connection.subscribeMessageCalls.push({ callback, message });
        subscriptionCallback = callback;
        return Promise.resolve(() => {});
      };
      const el = window.document.createElement(tag);
      el.setConfig({ type: 'custom:' + tag, ...config });
      window.document.body.appendChild(el);
      el.hass = hass;
      await delay(25);
      assertIntegrationSubscriptionUsage(hass, 1, context);
      assert(subscriptionCallback, `${context} did not establish a live Store subscription`);
      return { el, subscriptionCallback };
    };

    const inherited = await createThresholdCard(
      {},
      { warning_threshold: 20, critical_threshold: 10 },
      'Store-inherited thresholds',
    );
    inherited.subscriptionCallback({
      settings: { warning_threshold: 35, critical_threshold: 15 },
    });
    await delay(0);
    assert(inherited.el._config.warning_threshold === 35, 'live Store warning threshold did not update when card config omitted it');
    assert(inherited.el._config.critical_threshold === 15, 'live Store critical threshold did not update when card config omitted it');

    const explicit = await createThresholdCard(
      { warning_threshold: 25, critical_threshold: 5 },
      { warning_threshold: 20, critical_threshold: 10 },
      'card-explicit thresholds',
    );
    explicit.subscriptionCallback({
      settings: { warning_threshold: 40, critical_threshold: 18 },
    });
    await delay(0);
    assert(explicit.el._config.warning_threshold === 25, 'live Store warning threshold overrode explicit card config');
    assert(explicit.el._config.critical_threshold === 5, 'live Store critical threshold overrode explicit card config');
    assert(!getAsyncError(), 'async error during Store threshold precedence regression: ' + getAsyncError());
  } finally {
    dom.window.close();
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
      const { dom, window, getAsyncError } = createDom(t.file);
      const el = window.document.createElement(t.tag);
      if (typeof el.setConfig === 'function') el.setConfig({ type: 'custom:' + t.tag });
      el.hass = mockHass();
      window.document.body.appendChild(el);
      el.hass = mockHass();
      await delay(250);
      const len = el.shadowRoot ? el.shadowRoot.innerHTML.length : 0;
      if (!el.shadowRoot) problem = 'no shadowRoot';
      else if (len < 50) problem = 'empty render (len=' + len + ')';
      else if (getAsyncError()) problem = 'async error: ' + getAsyncError();
      window.close();
      if (!problem && t.tag === 'ha-vacuum-water-monitor') {
        await focusRegression(t.file, t.tag);
        await hassStateRegression(t.file, t.tag);
        await configuredDevicePersistenceFailureRegression(t.file, t.tag);
        await staleConfiguredDeviceSaveRegression(t.file, t.tag);
        await subscriptionRecoveryRegression(t.file, t.tag);
        await connectionReconnectRegression(t.file, t.tag);
        await sameConnectionReattachRegression(t.file, t.tag);
        await remoteRefillRegression(t.file, t.tag);
        await deviceIdentityRegression(t.file, t.tag);
        await storedStringXssRegression(t.file, t.tag);
        await storeThresholdPrecedenceRegression(t.file, t.tag);
        await savedCalibrationRoundTripRegression(t.file, t.tag);
      }
    } catch (e) { problem = (e && e.message) ? e.message : String(e); }
    if (problem) fail.push(`${t.tag}  (${path.basename(t.file)})  -> ${problem}`); else pass++;
  }
  console.log(`smoke: ${targets.length} element(s) | PASS ${pass} | FAIL ${fail.length}`);
  fail.forEach(f => console.log('  FAIL ' + f));
  process.exit(fail.length ? 1 : 0);
})();
