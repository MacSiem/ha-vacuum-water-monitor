# Task 3 — card integration, diagnostics and release readiness

Date: 2026-08-30
Branch: `fix/model-signal-detector-v5.2`

## Implementation

- The card now decorates every configured/discovered device with the backend `list_vacuums`
  descriptor. Backend `profile_key`, source/confidence, capability, evidence, tracked
  capacity/reservoir, distinct reservoirs and same-device signals win over the legacy card
  resolver. The browser model catalog remains only for an older backend response without a
  descriptor.
- Card accounting respects the Store's `initialized`/`last_reset_iso` state. A state that
  has not received a refill baseline renders remaining/used/percent as unknown and shows
  **Needs a refill baseline**; a genuinely initialized `used_ml: 0` still renders 100%.
- The Water tab gives distinct guidance for manual-only, automatic-estimate, missing-rate,
  unavailable-signal and unknown accounting. Manual-only Tapo Matter explicitly asks for
  calibration/manual refill and never claims invented automatic telemetry.
- Added privacy-safe, rendered diagnostics (canonical profile, confidence/source, tracked
  and distinct reservoirs, same-device raw signal roles, accounting source/reason/evidence).
  Dynamic diagnostic values are escaped before entering card markup.
- The custom-calibration form now shows effective tracked capacity, evidence and distinct
  reservoirs. Saving merges the active record (including rate mappings) while preserving
  its unedited fields and all other device records.
- The root card was mechanically synchronized to the bundled `www` card; after fix round 1
  the copies have the same SHA-256: `0683ef8ff2b9063e28ac63a2f4be303928b2f76b78a4ccbfe9112dabf6cf834c`.
- Release surfaces now identify 5.2.0: card header, integration manifest, Python constant,
  validation package/lock and frontend registration test. README, changelog and model
  capacity source documentation cover estimate-only semantics, the refill baseline,
  manual-only capability and authoritative backend descriptors.

## Files changed

- `.github/smoke.cjs`
- `ha-vacuum-water-monitor.js`
- `custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js`
- `tests/test_frontend_registration.py`
- `custom_components/ha_vacuum_water_monitor/const.py`
- `custom_components/ha_vacuum_water_monitor/manifest.json`
- `package.json`, `package-lock.json`
- `README.md`, `CHANGELOG.md`, `docs/model-capacity-sources.md`

## RED → GREEN evidence

1. Added a JSDOM runtime fixture for an opaque Xiaomi entity plus backend descriptors for
   Roborock `a170`/`a245`, Tapo Matter, initialized/uninitialized tank states, diagnostics,
   and calibration merge preservation.
2. RED command: `npm run test:smoke`.
   Result: exit 1, both distributed card copies failed with
   `opaque Xiaomi descriptor capacity was not used`.
3. Added descriptor decoration, authoritative metadata use, truthful initialization,
   accounting/diagnostic rendering and calibration merge.
4. GREEN command: `npm run test:smoke`.
   Result: exit 0; `smoke: 2 element(s) | PASS 8 | FAIL 0`.
5. Updated the frontend release-surface expectation before the release values.
   RED command: `python3 -m unittest tests.test_frontend_registration`.
   Result: exit 1; manifest still reported `5.1.14` instead of `5.2.0`.
6. Updated manifest, `const.VERSION`, card header, validation package/lock and test.
   GREEN command: `python3 -m unittest tests.test_frontend_registration`.
   Result: exit 0; 3 tests passed.

## Verification matrix

| Command | Result |
| --- | --- |
| `python3 -m compileall -q custom_components tests && python3 -m tests` | exit 0; compile successful; 56 tests passed |
| `npm ci --ignore-scripts && npm run test:smoke` | exit 0; runtime smoke `PASS 8 / FAIL 0` |
| `node --check ha-vacuum-water-monitor.js` | exit 0 |
| `node --check custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js` | exit 0 |
| `cmp -s ha-vacuum-water-monitor.js custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js` | exit 0; byte-identical |
| `node -e "…JSON.parse(package/lock, hacs, manifest, catalog)…"` | exit 0; `json: valid` |
| `git diff --check` | exit 0 |
| targeted key/material scan (`rg` for private keys, cloud/GitHub/Slack tokens and `p8/pem/key/keystore` files) | exit 0; `security-material-scan: clean` |
| local HA/HACS metadata assertion (domain, version, integration type, HA floor) | exit 0; `ha-hacs-metadata: valid` |
| `tests.test_frontend_registration` | exit 0; static-path/metadata/version/copy invariant validated |

`npm ci` emitted the upstream deprecation notice for transitive `whatwg-encoding@3.1.1`;
the smoke command itself was clean and passed. The existing full Python suite prints its
expected refusal message for an empty-list settings patch while all 56 tests pass.

## Self-review

- Reviewed the final diff and file list: only Task 3 card, smoke, release-surface and
  documentation files changed; no backend catalog/resolution logic was recreated.
- Backend descriptor values are merged centrally and then reused by card device paths;
  legacy model matching is entered only when a descriptor lacks `profile_key`.
- The uninitialized path blocks both `used_ml` and remaining percent, preventing fabricated
  `0 / 100%`; the initialized path keeps a legitimate zero-used result.
- New interpolated diagnostics/calibration values use `_esc`; no global helper or unsafe
  dynamic `innerHTML` path was introduced.
- Confirmed both distributed cards are byte-identical after the final synchronization.

## Concerns

- No local HACS CLI is installed, so no external HACS action was run. Static HACS/HA
  metadata validation and the integration registration tests passed; no external mutation
  was performed.
- No push, tag, release, GitHub comment or private-HA deployment was performed.

## Fix round 1 — review follow-up

### Implementation

- Replaced the card's single-record calibration lookup with backend-aligned layers:
  `default → resolved profile → entity`. Every layer normalizes legacy aliases before
  merging (`tank_ml`/`tracked_capacity_ml`, `water_per_m2`/`usage_ml_per_m2`, and
  `mop_wash_ml`/`wash_volume_ml`); mapping values merge additively per layer.
- Calibration writes now normalize the selected record, remove those legacy aliases, and
  send canonical `tracked_capacity_ml`, `usage_ml_per_m2`, and `wash_volume_ml` fields.
  Unedited selected-record fields and all other device records remain intact.
- Added device-origin tracking. Explicit YAML/user capacity, direct signal fields and an
  explicit `signals: {}` opt-out retain precedence. Registry descriptors only supersede
  unmarked legacy client-profile expansion/defaults.
- Removed manufacturer-only native/Matter dedup from the old-backend fallback. Without a
  shared stable physical identity, each `vacuum.*` entity remains visible.
- Accounting guidance now uses initialized/source/rate/evidence/reason. A manual-only
  model actively consuming via user calibration says **Measured calibration active**;
  paused automatic accounting says missing/unavailable instead of active.
- Diagnostics and calibration-reservoir formatting safely coerce non-numeric/non-string
  descriptor values and escape every interpolated value. The calibration label names the
  actual tracked reservoir instead of always calling it a dock tank.
- README now states HA 2024.7+, makes automatic accounting conditional on real same-device
  signals and resolved model/user rates, and removes generic default-water-rate promises.
- Captured the intentional empty-list guard warning inside its own unit test so the full
  Python suite output is clean without hiding the behavior.

### Behavior-specific RED → GREEN evidence

1. Added `smokeRoundOneDescriptorContracts` for layered default/profile/entity calibration,
   canonical WS payloads, active measured manual accounting, paused automatic accounting,
   `a245` raw roles, descriptor-vs-legacy capacity conflict, YAML capacity/empty-signals
   precedence, old-backend same-manufacturer entities, fallback rendering, and hostile
   descriptor diagnostics.
2. RED command: `npm run test:smoke`.
   Result: exit 1; both card copies failed with
   `effective default/profile/entity calibration did not win in rendered capacity`.
3. Implemented canonical layered calibration, origin-aware descriptor merge, truthful
   guidance, fallback behavior and canonical save normalization. Intermediate smoke runs
   exposed and corrected the test's old-fallback fixture ordering and legacy expectations.
4. GREEN command: `npm run test:smoke`.
   Result: exit 0; `smoke: 2 element(s) | PASS 10 | FAIL 0`.
5. Full Python run after warning capture: `python3 -m tests`.
   Result: exit 0; 56 tests pass without the former `Refusing empty-list settings patch`
   log line.

### Fix round 1 verification (final evidence)

| Command | Result |
| --- | --- |
| `npm ci --ignore-scripts --loglevel=error` | exit 0; 39 packages audited, 0 vulnerabilities; no deprecation warning |
| `python3 -m compileall -q custom_components tests && python3 -m tests` | exit 0; 56 tests passed; no empty-list guard warning |
| `npm run --silent test:smoke` | exit 0; clean output: `smoke: 2 element(s) | PASS 10 | FAIL 0` |
| `node --check` for both distributed cards | exit 0 |
| `cmp -s` root/package card copies | exit 0; byte-identical |
| JSON parse of package/lock, HACS, manifest and model catalog | exit 0; `json: valid` |
| `git diff --check` | exit 0 |
| targeted secret/signing-material scan | exit 0; no matches |
| local HA/HACS metadata assertion | exit 0; `release-metadata: valid` |

No push, tag, publication, GitHub comment or deployment occurred in this round.
