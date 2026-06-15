# Changelog

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
