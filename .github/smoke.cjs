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
  console.log(`smoke: ${targets.length} element(s) | PASS ${pass} | FAIL ${fail.length}`);
  fail.forEach(f => console.log('  FAIL ' + f));
  process.exit(fail.length ? 1 : 0);
})();
