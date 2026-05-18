
## [4.1.5] - 2026-05-18

### Fixed
- **Auto-discovery now picks up all vacuum entities** instead of silently skipping the hardcoded `vacuum.robotic_vacuum_cleaner` ID that leaked in from a prior workaround. Vacuums without native water sensors are still auto-added; estimation falls back to area/state-based dosing per the 'generic' brand profile, and users can remove unwanted vacuums via the Settings tab.

# Changelog — Vacuum Water Monitor

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
