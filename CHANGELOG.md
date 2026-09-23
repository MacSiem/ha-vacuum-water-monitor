# Changelog

## 5.7.0-beta.4 (2026-09-23)

Beta: fixes from a full live run of 5.7.0-beta.3 (two tasks, an error in between, eight mop
washes, each counted once; replay of the recorded run reproduces the live counter to 0.1 ml).

### Fixed

- **A run that restarts its area counter keeps its whole area in the history.** Robots with a
  per-task counter (Roborock `cleaning_area`) start a new task at zero when they resume after
  an error. The session now carries the area covered before the restart (46.8 m² instead of
  the last task's 23.4 m²) and keeps its water. A whole-cycle calibrated dose still treats a
  restart as an interruption, and a drop to a non-zero value is still a counter anomaly.
- **One refill, one history entry.** Pressing Refilled twice (or after the dock already cleared
  the tank) within ten minutes no longer erases the water counted in between; lid and button
  entities already used this window.
- **Readable names from the first start.** A vacuum whose state is not loaded yet when Home
  Assistant starts (Matter, slow integrations) got sensors named after its raw entity id; the
  registry name is used instead.

## 5.7.0-beta.3 (2026-09-23)

Beta: fixes found in a week of live testing of 5.7.0-beta.2 on a Roborock S8 MaxV Ultra. Each
fix is reproduced on recorded Home Assistant history replayed through the engine.

### Fixed

- **A mop wash could be counted twice at the end of a run.** Roborock's `*_cleaning` task flag
  stays on while the robot washes and empties the bin at the dock; it was read as "cleaning
  resumed", so a two-second wash status after the bin emptying was charged as a second wash
  (+150 ml on a S8 MaxV Ultra). With a status signal bound, only the status ends a wash now.
- **Sessions disappeared from the water history** when the mop settings changed during a run
  or the tank was refilled midway. The history keeps the run's water; such a session is still
  not used as a clean measurement for calibration or sharing. A broken count (counter reset,
  unbridged gap, missing rate) still leaves the water unknown.
- **One tank size everywhere.** The capacity entered in the card (`water_total_ml`) was shown by
  the sensors while calibration anchored to the model's tank. The engine now uses the same
  number; the dock empty anchor and automatic refill stay enabled. Changing it restarts the
  device's calibration, as any capacity change does.
- An idle heartbeat rewrote the whole Store every minute only to update its tick timestamp; such
  passes stay in memory until the next real write.
- Home Assistant's deprecated `device_registry.devices` mapping access in discovery.
- `scripts/shadow_capture.py` requested history without an end time and replayed only one day.

## 5.7.0-beta.2 (2026-09-16)

Beta: every refill option works, calibration survives real-world anchors, accounting follows
entity changes. Found by a pre-test audit of 5.7.0-beta.1 on a Roborock S8 MaxV Ultra setup.

### Added

- **Refill options that all reset the tank:** the Refilled button, automatic refill when the
  dock's empty error clears (now with an off switch), an `input_button`/`button` entity, a tank
  lid or door sensor, and the new `ha_vacuum_water_monitor.mark_refilled` action for
  automations and scripts. The *Last refill* sensor shows what reported each refill.
- **Accounting on entity changes:** a vacuum is recalculated about two seconds after any of its
  bound entities changes, with the 60-second heartbeat as a fallback. Disk writes from these
  updates are coalesced and flushed on shutdown.
- **Calibration confirmation:** before three tanks are learned, a tank outside the estimate's
  accuracy waits for the next tank to confirm it (a lifted tank or an unreported top-up no
  longer teaches the robot a wrong correction).
- Diagnostics for a tank awaiting confirmation, a water level without its own factor, bridged
  signal gaps and recent refills.
- Read-only shadow replay (`scripts/shadow_capture.py`) reports sessions against a reference
  counter, empty tanks, refills and dock-error transitions, in event or heartbeat mode.
- Home Assistant runtime tests (`tests_ha`) run inside a real Home Assistant core.

### Fixed

- The card's button and door-sensor refill methods created automations that only reset DIY
  helper entities, never the integration's tank; a lid sensor was also blocked by the dock
  contract. The card no longer creates those automations and offers to remove old ones.
- Pressing **Refilled** while the dock still showed its empty-tank error emptied the tank again
  on the next update.
- One unavailable reading of the robot, its status or its area during cleaning invalidated the
  whole tank. A gap of up to 5 minutes is now bridged when the mop settings are unchanged and
  the cleaned area kept pace with the robot (so a hidden wash is not skipped); a longer Home
  Assistant downtime still marks the tank incomplete.
- With automatic refill off, an empty error that flickers no longer counts as several tanks;
  an empty error first seen right after you reported the refill does not empty the tank again.
- Binding a different button or lid, or a button restoring an older press time after a restart,
  is not a refill; a lid closed shortly after the dock already cleared is the same refill.
- Refills reported by a button or lid are written to disk immediately.
- Area cleaned just before the robot heads to a wash or back to the dock was not counted.
- A wash the dock could not finish because it ran dry was charged in full (now half).
- Saving only a tank size in the calibration form switched the estimate to a whole-cycle rate
  and stopped counting dock washes; a saved scope now applies only to a measured rate.
- A tank size corrected in the card no longer silently turns off automatic dock refill.
- Roborock water levels `slight`/`min` map to low and `extreme` gets its own factor; a level
  without a factor is reported instead of silently averaged.
- A calibration window left behind by an older version after a rollback is ignored.
- A calculation that finished after a refill no longer overwrites that refill.

### Note

- Upgrading from 5.7.0-beta.1 restarts a learned correction once, because the estimates gained
  the `extreme` water level. Upgrading from 5.6 keeps the tank balance.

## 5.7.0-beta.1 (2026-09-15)

Beta: labelled estimates from the model database with automatic empty-tank calibration.

### Added

- **Every recognised model gets a water estimate.** Model records carry a mop system and,
  where available, a labelled estimate; class priors cover pad, rotating-pad and roller robots
  and a generic prior covers the rest. Each basis has a fixed, documented accuracy.
- **Automatic calibration from the dock's empty-water signal.** The median of the last eight
  tanks becomes the robot's correction; an abnormal tank and tanks with missing signals are
  skipped. The card shows the accuracy and the last tank results.
- **Automatic refill** when the dock's `water_empty` error clears to OK (Refilled stays as an override).
- **Optional anonymous calibration sharing** (off by default, reviewed payload, user-submitted).
- Roborock S8 MaxV Ultra estimate from owner-device accounting (S8 Pro Ultra by family
  transfer); Qrevo Curv 2 Flow (`roborock.vacuum.a245`) gains its sourced 4 l / 3 l capacity.
- Independent physics benchmark and card/backend parity tests in CI.

### Fixed

- Pressing **Refilled** no longer turns the balance incomplete one tick later (#12).
- A per-session cleaned-area counter restarting at zero is a new baseline, not a gap.
- Small area increments accumulate instead of being dropped.
- Restarts or unavailable robots while docked no longer invalidate the balance, and a later
  reason can no longer hide a missing rate.
- An unrelated dock error after an empty tank is no longer treated as a refill.
- A mop wash passing through docking/returning states is counted once.
- Changing mop mode or upgrading the dataset keeps the learned calibration.
- Missing capacities are shown as "unknown" instead of 0 / `null ml`; Polish labels in the
  English card were translated.
- A vacuum-only run (water level off) never uses water, and a whole-cycle user rate no longer
  adds or flags dock washes it already includes.
- An automatic refill clears an incomplete balance, and a session that ran entirely while the
  robot or Home Assistant was unavailable is reported as incomplete.
- Authored refill/anchor settings and a tank capacity that differs from the model are kept as
  configured; your own calibration replaces the estimate label and accuracy.


## 5.6.0 (2026-09-09)

### Fixed

- **A vacuum whose manufacturer is written in registry form is recognised again.**
  5.5.0 narrowed the catalogue by comparing the Home Assistant device-registry
  manufacturer for whole-string equality. Home Assistant reports vendor-formatted
  values such as `Beijing Roborock Technology Co., Ltd.` or
  `TP-Link Corporation Limited`, so the catalogue was narrowed to nothing and an
  otherwise exact `model_id` match was discarded. The vacuum then appeared
  unrecognised even though its model was present in the catalogue. Reported for
  the Qrevo Curv 2 Flow X (`roborock.vacuum.a245`) and seen for the Qrevo 5AE
  (`roborock.vacuum.a170`) and the Tapo RV50 Pro Omni (Matter `1797`).
  A known manufacturer is now also matched on token boundaries. A stated but
  unknown manufacturer still scopes the search, so a product id that is not
  unique across vendors stays unresolved rather than matching another brand.

- **The shipped consumption snapshot is reproducible from published inputs.**
  5.5.0 shipped a snapshot compiled from an uncommitted working tree of the data
  repository (`source_revision` ending in `-dirty`) that nobody could rebuild.
  The snapshot is now compiled from the committed data-repository revision, and
  a release test refuses any snapshot whose `source_revision` is not a full
  commit sha.

### Added

- Release gate: the bundled card under `custom_components/.../www/` must be
  byte-identical to the repository card, so a stale copy cannot ship.
- Regression coverage for registry manufacturer forms, for cross-vendor product
  ids and for snapshot provenance.

### Documentation

- `docs/consumption-roadmap.json` declared `local_git_created_not_public` and a
  stale revision long after the repository was public. Corrected.
- The changelog section describing the 5.5.0 content was still headed
  *Unreleased* and claimed no release had happened.

### Unchanged, and deliberately so

- **No consumption rates are shipped.** The dataset still contains zero approved
  consumption profiles and two manufacturer-declared, display-only quantities.
  A model with no measured rate reports `unknown` with a reason, and the card
  points to calibration. Coverage is not complete: the acceptance gate
  (`scripts/check_consumption_coverage.py --require-complete`) still exits 2 with
  `goal_complete: false` and 1023 unresolved criteria across 133 models.


## 5.5.0 (2026-09-05)

- Evidence-gated 133-record model/variant catalogue with five separate reservoirs,
  dated provenance, explicit regional/HA unknowns and no shipped consumption rates.
- Registry/MAC identity deduplication in backend and card preserves one history owner.
- Same-reservoir real volume takes precedence; unavailable inputs, counter gaps and
  context changes rebaseline safely. No inferred time rate or unproved full refill.
- Separate floor/wash measurement scope prevents hybrid double counting; automatic
  session history retains unknown volumes. Reprofiling preserves authored settings.
- Generated frontend catalogue, adapter contract fixtures, expanded regression checks,
  diagnostics and coverage documentation.

## 5.4.0 (2026-09-02)

- Added signal mapping for vacuums integrated through XiaoMi's official
  `xiaomi_home` and through `xiaomi_miot`. Both name entities after canonical
  MIoT properties instead of a Home Assistant `translation_key`, so previously
  every role stayed unresolved and usage could never advance. Roles are now
  matched on the MIoT property, always preferring the longest match so that the
  dock tank, the robot tank and the plain run status stay distinct.
- Added a manual **Signal mapping** section in Settings. Any role can be
  assigned to an entity of the same device by hand, which takes precedence over
  automatic detection; choosing *Automatic* hands the role back to detection.
  Only a genuine correction is stored, so a device keeps benefiting from future
  detection improvements.
- Fixed a duplicated vendor `translation_key` silently dropping a role. HA Core
  `xiaomi_miio` registers `is_water_box_attached` twice for mop-capable models,
  which removed the mop evidence for every such vacuum. Interchangeable
  binary/enum evidence is now resolved deterministically, while two competing
  measurements (area, duration, tank level) still refuse to guess.
- Roles with several equally ranked candidates are reported as ambiguous and
  flagged in the card for confirmation instead of failing silently.
- Added water-output level as mop evidence for MIoT integrations. Vacuums that
  expose a water level but no mop-mode or mop-attachment entity, such as the
  Xiaomi H50 and H50 Pro, previously failed the mop gate on every run. A level
  of zero now also ends mopping regardless of any mode label. This is limited
  to adapters whose level really is a water control: Roomba binds that role to
  `fan_speed` and Ecovacs' `water_amount` has no off position, so reading
  either as proof of mopping would have billed plain vacuuming as water. Only
  recognized numeric or documented level tokens count, because these enums are
  rendered in the user's own language.
- Lifetime counters are no longer mistaken for the current run. `total_*` and
  `statistical_*` properties are excluded, so a growing all-time total cannot
  be read as one session or crowd out the real per-run sensor.
- Descriptors expose the assignable same-device entities and their
  `device_class`, unit and `state_class`, so the card can offer a mapping even
  for integrations this build has never seen.

Note for Xiaomi H50 and H50 Pro owners: this release makes the robot's signals
resolve, which is what previously blocked everything. Xiaomi does not publish a
water-consumption rate for these models, so automatic estimation still needs a
measured calibration entered in the card — the release alone will not start the
counter.

## 5.3.0 (2026-09-01)

- Added per-integration machine-signal adapters for Roborock, Xiaomi Miio,
  Ecovacs, Matter RVC, iRobot Roomba/Braava, SmartThings, TP-Link, Dreame Vacuum
  and Valetudo. Unknown platforms now remain manual-only unless the user maps
  explicit same-device signals.
- Corrected integration-specific signal semantics: Valetudo area is normalized
  from cm², Roomba area follows the HA metric/imperial unit system, Dreame
  prefers `state` over `status` and preserves exact dynamic entity bindings,
  and Xiaomi Miio no longer misuses the non-vacuum `water_level` entity.
- Added a fail-closed mop gate. Vacuum-only/sweeping runs never consume virtual
  water merely because the vacuum is active or a water tank remains installed;
  exact Roborock and Dreame mopping states are covered by regression tests.
- Added area → duration → bounded active-time accounting, mode/intensity-aware
  rates, model-specific ranged water controls and Braava compound spray tokens.
- Added debounced low-water calibration with a configurable reserve, bounded
  learning and rejection of implausibly early alerts; exact empty and missing
  tank states remain distinct.
- Tightened station and Matter semantics: dock `water_shortage` now follows the
  debounced threshold path, generic station `cleaning` cannot count as a mop
  wash, and Tapo Matter accounting is gated by its real `clean_mode` signal.
- Improved profile/source diagnostics, uncertainty explanations, calibration
  controls, dock-state wording, typography and mobile readability.
- Corrected the S8 MaxV Ultra clean-water profile to the manufacturer-published
  4 l dock and 100 ml onboard tanks while keeping consumption rates explicitly
  labelled as estimates.
- Clarified the two intentional unknown states reported in issue #10: water sensors need
  a first full-reservoir refill baseline, while maintenance due needs a configured
  maintenance schedule. The HA entities now expose a machine-readable `state_reason`
  and `action_required`, and an exact Matter model `1797` post-refill regression test
  proves that Water remaining, Water used and Last refill become known after reset.

## 5.2.0 (2026-08-30)

- Fixed model detection to use the Home Assistant registry descriptor (model ID, model and catalog identifiers) instead of guessing from display names or manufacturer. The descriptor now supplies the canonical profile, capacity, reservoirs, confidence, evidence and same-device signal roles to the card.
- Fixed truthful tank initialization: before an explicit refill baseline, remaining water and used water are shown as unknown instead of fabricated `0 used / 100%` values. A real post-refill `0 / 100%` state remains valid.
- Added card diagnostics for profile resolution, tracked and distinct reservoirs, discovered raw status/area roles and accounting reason/evidence. Calibration saves now merge only the active device record.
- Tapo Matter uses the real `clean_mode` axis as an affirmative mop gate. A supported profile can apply a bounded, high-uncertainty cross-model active-time seed and learn from low-water/refill anchors; missing or vacuum-only mode fails closed, and no unexposed intensity is invented.

## 5.1.14 (2026-08-28)

- Isolation: Bento CSS is component-local in both frontend copies and cannot be captured from `window.HAToolsBentoCSS` by load order.
- Compatibility: raised the Home Assistant floor to 2024.7 for the static-path API used by the bundled-card registration.
- Performance: moved the bundled-card filesystem stat off the Home Assistant event loop.
- Security: removed the legacy global injector, which traversed and modified unrelated custom-card shadow DOMs.
- UX: restored the donate footer within this card's own shadow root.

## 5.1.13 (2026-08-22)

- Added manufacturer-sourced profiles and model aliases for Roborock Qrevo 5AE (`a170`), Qrevo Curv 2 Flow/FlowX (`a245`), Xiaomi H50/H50 Pro, and Tapo RV50 Pro Omni.
- Expanded the model database to distinguish clean/dirty dock tanks, clean/dirty robot tanks, tested maximum area per fill, water-flow levels, mop speed/lift/pressure, and model-specific wash/drying facts.
- Kept unpublished ml/m² and generic wash-cycle values unset. Xiaomi's published H50 Pro 180 ml pre-task and 120 ml mid-task values are shown separately and are not misused as one automatic accounting rate.
- Fixed custom calibration editing: drafts, focus, caret position and expanded state now survive Home Assistant/Store refreshes; saves are device-scoped, awaited, and show success or failure.
- Fixed server-side accounting to apply saved per-device ml/m² and mop-wash calibration.
- Fixed one physical mop-wash sequence being counted more than once when a vacuum transitions between internal wash statuses.
- Added Python accounting tests, model/profile render smoke coverage, pinned frontend test dependencies, and a CI invariant that both distributed card copies stay identical.
- Documented primary manufacturer sources and data-quality rules in `docs/model-capacity-sources.md`.

## 5.1.12 (2026-08-21)

- Security: escape configured and persisted device/maintenance icons at every HTML render boundary. The same sweep also escapes Home Assistant entity names, states, IDs, and error messages when they are interpolated into card markup.
- Tests: the runtime smoke test now proves hostile icon and Home Assistant values render as text in both distributed card copies.

## 5.1.11 (2026-07-18)

- Fix: threshold changes made in the integration Options now apply immediately. The options flow saved them, but nothing re-read them, so they previously only took effect after a Home Assistant restart.

## 5.1.10 (2026-07-18)

- Fix (UI): the small accent dot before section titles no longer detaches from the title text (it was pushed to the opposite edge by the header's flex space-between); it is now pinned next to the title.

## 5.1.9 (2026-07-18)

- Fix (#4): removing a manually-added device now works even when it is the last one. The card used the generic settings patch, whose empty-list guard refused the write, so the device silently reappeared with no feedback. A dedicated remove command persists the deletion and the card shows a confirmation / error toast.
- Fix (#3): the donate/support footer no longer flickers on state changes, tab switches, or view navigation — it is re-injected synchronously before paint.

## 5.1.8 (2026-07-17)

- Fix (UI): responsive tab bar — tabs stretch to fill the card width and wrap on narrow layouts instead of being pinned to content width and clipped (shared HA Tools tab styling).

## [5.1.7] - 2026-07-12

Fixes for [#1](https://github.com/MacSiem/ha-vacuum-water-monitor/issues/1) and
[#2](https://github.com/MacSiem/ha-vacuum-water-monitor/issues/2). Thanks @chris400!

- Fix: ghost "Vacuum" device created for users who added the card from the UI picker.
  The card's stub config carried a brand profile whose default `vacuum_entity` leaked
  into saved settings. The stub is now minimal, brand profiles can no longer inject an
  entity id, and the card only persists config devices whose entity exists in HA.
- Fix: one-time migration prunes previously saved ghost `configured_devices` (no matching
  HA entity and no tank history) and removes their leftover device registry entries.
- Fix: vacuums seeded from stored tank state are now named with their HA friendly name
  (e.g. "Roborock S7 MaxV") instead of the raw entity id.
- Fix: the card now works for non-admin Home Assistant users — websocket commands no
  longer require admin (authentication is still required).
- Docs: rewritten README with a "How it works" section, automatic-vs-manual table, quick
  start, entity/automation examples, and FAQ; new English screenshots (light + dark).
- Chore: removed committed `__pycache__` from the repo; aligned versions across
  `manifest.json`, `const.VERSION`, and the bundled card header (5.1.7).

## [5.1.6] - 2026-06-27

- Fix: large i18n cleanup — the setup banner, all 29 brand-profile notes, the refill notification, the auto-created automation alias, button/status states, and table labels were hardcoded in Polish; they now render in English. The bilingual `_t` table for the main UI is unchanged. The bundled card (repo root + integration `www` copy) is kept in sync.
- Docs: added a real card screenshot to the README.

## [5.1.5] - 2026-06-15

- Theme: dark/light now follows the active Home Assistant theme (luminance of --card-background-color) instead of OS prefers-color-scheme.
- Sync bundled card (root and integration www copy now identical, both themed).


## [5.1.4] - 2026-06-15

- Theme: dark/light now follows the active Home Assistant theme (luminance of --card-background-color) instead of OS prefers-color-scheme.
- Sync bundled card (root and integration www copy now identical, both themed).


## [5.1.3] - 2026-06-15

- Theme: dark/light now follows the active Home Assistant theme (luminance of --card-background-color) instead of OS prefers-color-scheme.
- Sync bundled card (root and integration www copy now identical, both themed).


## [5.1.2] - 2026-06-13

### Fixed

- **Card now auto-resolves the vacuum model profile (tank capacity) from the
  entity id** — a known model such as `vacuum.roborock_s8_maxv_ultra` shows its
  real tank size (e.g. 3000 ml) and tracks water out of the box, without the
  user manually picking a Brand Profile. Previously a discovered vacuum with no
  stored `brand_profile` rendered as "Generic / 300 ml / doesn't track water".
- Added `getGridOptions()` for correct sizing in HA's sections (grid) layout.
- Periodic `hass`-driven re-render is now gated by a vacuum-state signature, so
  the card no longer rebuilds every 10s when nothing changed.

## [5.1.1] - 2026-06-13

### Fixed

- **Water remaining/used sensors now know tank capacity from the vacuum model
  automatically**, without manual calibration. Capacity falls back to a built-in
  per-model database (ported from the card's `CALIBRATION_DATA`), auto-detected
  from the `brand_profile` or the vacuum entity id — e.g. a Roborock S8 MaxV
  Ultra resolves to 3000 ml out of the box. Unrecognised models still report
  `unknown` rather than a misleading percentage (mirrors the card's water calc).

## [5.1.0] - 2026-06-13

### Added

- Added Store-backed `sensor` platform entities for each known vacuum:
  water remaining percentage, water used since refill, last refill timestamp,
  and next custom maintenance due in days.
- Sensor entities refresh from the same Store write/tick path used by the
  bundled card, so automations and dashboards can react without opening the
  card.
- Added pure-python tests for water estimate math, refill timestamp parsing,
  Store device merging, and custom maintenance due derivation.

## [5.0.4] - 2026-05-24

### Fixed

- **`BRAND_PROFILES.roborock_s8_maxv_ultra` no longer pre-fills four
  Maciej-private template/input entities** (`sensor.roborock_water_remaining`,
  `input_number.roborock_water_used_ml`,
  `sensor.roborock_water_used_last_session_2`,
  `input_datetime.roborock_last_water_reset`). On a fresh HACS install those
  entities don't exist, so the card was rendering four blank "unknown" tiles
  even though server-side accounting in `tick.py` was working fine via the
  hybrid-mode fallback. The Roborock profile now exposes only entities created
  by the official `roborock` integration. Advanced users who maintain their
  own DIY counter helpers can wire them in via per-card YAML — see
  [README "Advanced YAML"](README.md#advanced-yaml).
- **Mop dosing now reads the real Roborock select entities** instead of
  always defaulting to `standard` mop_mode and `medium` mop_intensity. Added
  `mop_mode_entity: select.roborock_s8_maxv_ultra_mop_mode` and
  `mop_intensity_entity: select.roborock_s8_maxv_ultra_mop_intensity` to the
  S8 MaxV Ultra brand profile, so the 60s tick uses your actual mop settings.
  Prior behaviour underestimated water usage by ~50% at `deep`/`high`
  (real 9 × 1.3 = 11.7 ml/m² vs default 6 × 1.0 = 6 ml/m²).
- **`_addUserDevice` brand-profile matching is now fuzzy by model suffix**.
  Previously the match required an exact `vacuum_entity` equality, so renamed
  entities (`vacuum.s8_maxv_ultra`, `vacuum.salon_q_revo`,
  `vacuum.parter_s7_maxv`) silently fell through to the generic profile
  (`water_total_ml: 0` → blank water tile, no dock sensors). The matcher now
  accepts entity IDs ending with `_<model_suffix>` or `.<model_suffix>`, then
  forces `vacuum_entity` back to the user's actual entity ID after the spread.

### Notes

- If you upgraded **from v5.0.0 or v5.0.1** at any point on 2026-05-18 and
  also maintain your own `input_number.*_water_used_ml` helper via a template
  sensor / automation, your counter may have been double-counted for a few
  hours (regression window between v5.0.0 publication and the v5.0.2 patch
  that landed the `_hasPrivHelpers` check). Spot-check your counter history
  for that day and reset the input_number manually if numbers look ~2× off.

## [4.1.6] - 2026-05-18

### Fixed
- **Calibration label** now reads from the per-device auto-detected `brand_profile` (e.g. `roborock_s8_maxv_ultra`) instead of the card-level YAML config. Multi-device cards no longer collapse every device to the same calibration; a Roborock S8 MaxV Ultra renders as such (Tank 3000 ml, Mop VibraRise 3.0 dual spinning, ~250 m² per charge) rather than "Generic / Unknown model".
- **Matter-bridge dedup**. When the same physical robot is exposed via both the native vendor integration (e.g. `vacuum.roborock_s8_maxv_ultra`, platform `roborock`) and a Matter bridge (`vacuum.robotic_vacuum_cleaner`, platform `matter`), auto-discovery now drops the Matter exposure if a non-matter alternative with the same manufacturer string exists. Prefers the native entity because it exposes the rich sensor surface (water, dock, mop, brushes). Reads `hass.entities` + `hass.devices` synchronously — no extra WS calls.

## [4.1.5] - 2026-05-18

### Fixed
- **Auto-discovery now picks up all vacuum entities** instead of silently skipping the hardcoded `vacuum.robotic_vacuum_cleaner` ID that leaked in from a prior workaround. Vacuums without native water sensors are still auto-added; estimation falls back to area/state-based dosing per the 'generic' brand profile, and users can remove unwanted vacuums via the Settings tab.

# Changelog — Vacuum Water Monitor

## [5.0.3] - 2026-05-18

### Fixed
- Mirrors v4.1.6 plugin fixes (commit 5546671): per-device `brand_profile` in calibration label + Matter-bridge dedup in auto-discovery. Same bug surface lived in the bundled v5 integration card; both fixes applied verbatim so the card behaves identically whether installed as Lovelace plugin or via the integration.

## [5.0.2] - 2026-05-18

### Fixed
- **Respect user's pre-existing DIY automations.** `_hasPrivHelpers()` in the card was hard-coded to `false`, so the integration always ran its own water accounting even when the user already had an `input_number.*_water_used_ml` helper updated by their own template sensor / automation. Now both the JS card and the Python tick check whether `device.water_used_input` resolves to an existing HA entity and skip integration-side accounting when it does — the card only displays state, never overwrites it. Pairs with the v4 plugin's `_hasPrivHelpers` check (line 1393) which had been working since the standalone-mode aneks 2026-04-18.

## [5.0.1] - 2026-05-18

### Fixed
- **Auto-discovery now picks up all vacuum entities** instead of silently skipping the hardcoded `vacuum.robotic_vacuum_cleaner` ID that leaked in from a prior workaround. Vacuums without native water sensors are still auto-added; estimation falls back to area/state-based dosing per the `generic` brand profile, and users can remove unwanted vacuums via the Settings tab.

## [5.0.0] - 2026-05-18

### Major
- Migrated from a HACS Lovelace plugin to a HACS integration with a bundled Lovelace card.
- Added config flow setup and automatic card registration through the integration frontend path.
- Moved vacuum water tank counters and refill timestamps from browser storage to Home Assistant Store.
- Ported the standalone water accounting loop to a 60-second server-side tick task.
- Added WebSocket commands for vacuum discovery, persisted state, settings, tank reset, and intro dismissal.

## [4.1.3] - 2026-05-12

### Fixed
- Removed Google Fonts CDN @import (1 occurrence(s)); now uses system font stack with Inter as the preferred locally-installed face.
- Normalized bare `font-family: "Inter", sans-serif` declarations to a complete cross-platform system stack.
- Privacy section in README: claim now matches behaviour (no CDN dependencies).

All notable changes to **Vacuum Water Monitor** are documented here.

## [4.0.0] - 2026-05-10

### Major
- **Split from `MacSiem/ha-tools` monorepo** into a dedicated standalone HACS plugin.
- Bundled Bento Design System CSS inline — no shared dependency required.
- Inlined `_haToolsEsc` XSS sanitizer.
- Persistence keys migrated to per-tool namespace `ha-vacuum-water-monitor-…` (clean break — old data under `ha-tools-…` is **not** migrated automatically).
- Donation/support footer added to the panel.
- Cross-tool discovery banner removed; each tool stands on its own.

### Compatibility

- Home Assistant ≥ 2024.1.0

### Replacement sprint (unreleased)
- Strict consumption resolver, private measured calibration, whole-cycle accounting and reservoir diagnostics; no new shared rates.
