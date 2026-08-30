# Vacuum Water Monitor model and signal detector reliability plan

## Goal

Fix issues #10, #11, and #12 by resolving vacuums from Home Assistant's entity/device registries instead of relying on human-readable entity IDs, discovering only same-device telemetry, and making water accounting explicit and observable. Preserve existing installations and never invent unsupported Matter telemetry.

## Global Constraints

- Home Assistant compatibility floor remains `2024.7.0`; registry code must therefore use APIs available in HA 2024.7 and read optional `model_id` with `getattr(..., None)`.
- Explicit user/YAML configuration wins over discovery. Registry metadata is next, then legacy `brand_profile`/entity aliases. Never overwrite a user-selected signal or calibration.
- Related entities may be auto-linked only when they share the vacuum entity's non-empty `device_id`. Ignore disabled registry entries and ambiguous duplicate roles. Never link by manufacturer alone.
- Matching uses raw registry/device identifiers and raw entity states, not localized UI labels.
- Target fixtures: Roborock `a170` resolves to `roborock_qrevo_5ae`; Roborock `a245` resolves to `roborock_qrevo_curv_2_flow`; Xiaomi model `Xiaomi Robot Vacuum H50 Pro` resolves even for opaque entity IDs; Tapo model `RV50 Pro Omni (1797)` or model id `1797` resolves to `tapo_rv50_pro_omni` through Matter.
- Tapo Matter is `manual_only` unless real same-device usage signals or user calibration exist. Do not fabricate status, area, wash-volume, or ml/m2 telemetry.
- Remove automatic generic accounting fallbacks of 150 ml/wash and 4/6/9 ml/m2. Automatic accounting requires an explicit model-profile or user-calibrated rate. Existing supported-model estimates may be retained only as explicit per-profile values with `maintainer_estimate` evidence surfaced in state/card metadata.
- Count a wash once on entry into a verified raw wash-state sequence. Area dosing requires a positive plausible delta, active cleaning, and an explicit rate; resets/decreases establish a new baseline and consume nothing.
- Water remaining is unknown until capacity is known and a refill baseline exists. Water used may be `0` only with an initialized baseline; Last refill and maintenance remain unknown when no source event/schedule exists. Surface `initialized`, `state_reason`, `capability`, profile source/confidence, and accounting evidence.
- Store migration must be additive and lossless. Keep legacy entity-keyed tank history and custom calibration working. New metadata must not silently reinterpret ambiguous `robot_tank_ml` as clean or dirty.
- Both distributed card files remain byte-identical. No shared `window.*` helper, no unsafe `innerHTML` interpolation, no blocking I/O on the HA event loop, no secrets, and no private-HA deployment.
- TDD is mandatory: every behavioral change starts with a focused failing test whose expectation is independently derived, then minimal implementation, then the full Python suite and card runtime smoke test.
- This plan authorizes worktree commits only. Push, tag, release, and GitHub comments happen later under the orchestrator's separate publication gate after complete verification.

## Task 1: Canonical profiles and registry-based discovery

Create a backend-owned model/profile and discovery layer.

Files:
- Add `custom_components/ha_vacuum_water_monitor/model_profiles.json`.
- Add `custom_components/ha_vacuum_water_monitor/profiles.py`.
- Add `custom_components/ha_vacuum_water_monitor/discovery.py`.
- Update `custom_components/ha_vacuum_water_monitor/tick.py`, `sensor_calculations.py`, and `websocket_api.py` to consume the new interfaces.
- Add `tests/test_profiles.py` and `tests/test_discovery.py`; adapt existing tests only where the public contract intentionally changes.

Requirements:
1. Move canonical identifiers, capacities/reservoir semantics, explicit accounting rates, evidence, sources, and capability declarations into `model_profiles.json`. At minimum preserve every currently recognized canonical profile and alias; the four target fixtures above are mandatory. Keep dock clean, dock dirty, robot clean, and robot dirty reservoirs distinct, with an explicit `tracked_reservoir` and `tracked_capacity_ml`.
2. `profiles.py` must load and validate the catalog, normalize identifiers, resolve a profile with deterministic precedence (explicit locked override; model_id; model; catalog identifiers/aliases; legacy brand_profile; entity alias; unknown), and return profile key/source/confidence/capability/evidence plus safe effective accounting fields. Invalid catalog records fail closed with a clear exception during tests/import rather than silently defaulting.
3. `discovery.py` must produce a serializable descriptor for every `vacuum.*`: entity id/name/state/battery, platform, registry unique id, device id, manufacturer, model, optional model_id, stable `source_id`, resolved profile metadata, and a `signals` map. Implement pure helper boundaries so registry-shaped fixtures can exercise real resolution without a running HA.
4. Discover same-device roles using entity-registry `translation_key`, platform, original name, and entity id as normalized identifiers. Mandatory roles: `status_sensor`, `area_sensor`, `mop_mode_entity`, `mop_intensity_entity`. Prefer exact translation keys (`status`, `cleaning_area`, known vendor equivalents); ignore disabled/unavailable candidates and omit ambiguous roles. For Roborock, raw status `washing_the_mop` must be discoverable even when the vacuum entity itself is `docked`.
5. `list_vacuums()` and its WebSocket response must use these enriched descriptors. Configured/user devices must merge descriptor data without replacing explicit fields. Preserve entity-id storage keys for compatibility while exposing `source_id` for stable identity and diagnostics.
6. Tests must first fail on the four target fixtures, same-manufacturer two-device isolation, disabled/ambiguous sibling rejection, precedence, and catalog validation. Record RED/GREEN evidence.

Acceptance:
- The four target model fixtures resolve exactly as specified.
- Roborock sibling signals are linked only by matching device_id.
- Tapo Matter resolves capacity/profile but has no invented signals and reports `manual_only`.
- Existing aliases/capacity tests remain green.

## Task 2: Safe accounting, initialization, and calibration migration

Make accounting consume the effective descriptor/profile without generic guesses and make sensor state semantics truthful.

Files:
- Update `custom_components/ha_vacuum_water_monitor/tick.py`.
- Update `custom_components/ha_vacuum_water_monitor/sensor_calculations.py`.
- Update `custom_components/ha_vacuum_water_monitor/sensor.py`.
- Update `custom_components/ha_vacuum_water_monitor/storage.py` and `const.py` only if an additive schema migration is needed.
- Extend `tests/test_tick.py` and `tests/test_sensor_calculations.py`; add `tests/test_storage_migration.py` if storage changes.

Requirements:
1. Replace generic 150 and 4/6/9 fallbacks with optional explicit rates from user calibration or resolved profile. Missing rate means skip that accounting source and set an observable reason; it must never add water.
2. Resolve rate by raw mode/intensity with deterministic fallback only inside an explicit mapping. Count wash on transition from outside to inside the verified wash-state set; transitions inside one wash sequence and integration restarts while already washing do not double count.
3. Area accounting requires cleaning activity, mop not explicitly off, a finite explicit rate, delta >= 0.1 m2, and a configurable conservative anomaly ceiling. A reset/decrease, unavailable gap, or implausible jump updates/bounds the baseline without consumption and records the skip reason.
4. Persist enough per-device accounting metadata to expose last event source/rate/evidence/reason without breaking old tank-state records. Preserve the DIY helper no-double-count behavior.
5. Treat refill as initialization. Before refill, remaining percentage/value is unknown even if capacity is known; used is unknown rather than a misleading initial zero. After refill, used=0 and remaining=100 are valid. Existing histories with a valid refill timestamp remain initialized.
6. Custom calibration merge is additive and entity-scoped. Accept explicit `tracked_capacity_ml`/`tank_ml`, wash rate, and usage rate mappings. Preserve legacy `robot_tank_ml` as `legacy_robot_tank_ml` metadata and do not map it to clean/dirty automatically.
7. Sensor attributes include `initialized`, `state_reason`, `capability`, profile resolution source/confidence, and accounting evidence/reason. Last refill and maintenance remain unavailable when no event/schedule exists.
8. Tests must first fail for no-rate-no-consumption, wash dedup/restart, area reset/decrease/gap/anomaly, initialized/uninitialized output, custom calibration, and legacy-state compatibility. Record RED/GREEN evidence.

Acceptance:
- No unknown or Matter-only device consumes generic default water.
- A detected Roborock with explicit profile/user estimates consumes exactly once per raw wash entry and by valid area deltas.
- Sensor state distinguishes uninitialized, unsupported/manual-only, and valid zero.
- All old regression tests pass or are updated only for the intentional truthful-state contract.

## Task 3: Card integration, diagnostics, documentation, and release readiness

Wire enriched backend data into both card copies, make limitations/action visible, and prepare version 5.2.0 without publishing.

Files:
- Update root `ha-vacuum-water-monitor.js`, then mechanically synchronize `custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js` byte-for-byte.
- Update `.github/smoke.cjs` and frontend/version tests.
- Update `README.md`, `CHANGELOG.md`, `docs/model-capacity-sources.md`, `custom_components/ha_vacuum_water_monitor/manifest.json`, and `const.py`.
- Add a privacy-safe diagnostics payload/WS command only if needed to let issue reporters copy resolved model/profile/signals/reasons without exposing unique IDs; otherwise render these fields in the existing card diagnostics/setup view.

Requirements:
1. The card trusts backend `profile_key`, effective capacity/reservoir, capability, evidence, and signals; legacy client resolution is fallback only for older backend state. It must not reintroduce manufacturer-only dedup.
2. Calibration UI displays the merged effective custom calibration and distinct reservoir fields. It clearly labels tracked reservoir/capacity and estimate evidence. Saving merges the selected device record and never replaces unrelated calibration fields/devices.
3. UI distinguishes: needs refill baseline, automatic estimate, manual-only/no telemetry, missing rate, unavailable signal, and active valid accounting. Tapo Matter tells the user to provide calibration/manual refill rather than claiming automatic usage. Roborock shows discovered raw status/area roles.
4. Add runtime smoke fixtures for opaque Xiaomi entity detection, Roborock a170/a245 descriptors/signals, Tapo Matter manual-only state, initialized vs uninitialized sensor presentation, and calibration merge. Assertions verify rendered/observable behavior, not source substrings.
5. Bump all version surfaces to `5.2.0`; add a concise changelog entry explaining the detector root cause, same-device signal discovery, truthful initialization, and no fabricated Matter/default telemetry. README must state that this is an estimate and explain the refill baseline and manual-only capability.
6. Run the full verification matrix: Python tests; card runtime smoke; `node --check` on both card copies; byte comparison; JSON parse/validation; `git diff --check`; secret/material scan; HACS/HA metadata checks; and inspect the final diff for duplicate frontend copies and unrelated changes.

Acceptance:
- All tests are green with pristine output.
- Root and packaged card copies are byte-identical.
- Version surfaces all report 5.2.0.
- Documentation accurately separates detected capacity from available usage telemetry.
- Branch is release-ready but has not been pushed, tagged, released, or commented externally by the implementer.
