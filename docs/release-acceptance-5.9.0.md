# 5.9.0 features and acceptance boundaries

Prepared 5 October 2026. This is a candidate, not a public release. Model recognition,
automatic estimation and physical accuracy are separate claims. Unit and CI checks
verify code behavior; they do not replace live HACS and household-interface acceptance.

## Function matrix

| Function | Candidate behavior | Code evidence | Remaining live evidence |
|---|---|---|---|
| Discovery | Registry-based, same-device signals; S7 MaxV/a27 and H50 Pro/ov42gl aliases survive entity renaming | Discovery, adapter and real-runtime regressions | Authors' exact firmware/integration and native reprofile |
| Floor accounting | Area first; explicitly supplied time rate can cover active intervals; no guessed area-to-time conversion | Tick, runtime and numeric-output regressions | Actual model/integration settings and physical volume |
| Short area dropout | A bounded gap can recover without a time rate when the cumulative counter and settings remain valid | `test_issue12_area_recovery.py`; unchanged gap-protection regressions | Normal use on the reporting Qrevo |
| Vacuum-only and settings | Affirmative mop evidence required; unknown output levels do not silently use a default | Runtime and numeric range tests | Exact device telemetry |
| Mop washing | Separate observed wash sequence, counted once; whole-cycle calibration excludes extra wash dosing | Tick and refill/calibration regressions | Device-specific wash visibility and water amount |
| Refill | Card, device button, service, bound button/lid and eligible dock clear share bookkeeping; deduplication retains intervening use | Refill and runtime tests | Every route in the candidate's live interface |
| Calibration | Complete refill-to-empty learning; incomplete/outlier samples excluded; authored measurements stay separate | Calibration, local-measurement and replay tests | Measured accuracy; no new physical runs currently authorized |
| Tank settings and history | Per-robot capacity and baseline/history preserved; session water formatted without changing original records | Setup, storage and presentation regressions | Current candidate fresh/upgrade, reload/restart persistence |
| Health and Repairs | Missing rate explains calibration rather than an ineffective full-tank Repair; unknown stays unknown | `test_issue10_missing_rate.py`, setup and card tests | Current native Repairs/card behavior |
| Forecasts and reminders | Cleanings/days and forecast error use available tank history; genuine zero differs from missing data | Forecast, setup and presentation tests; blueprint in repository | Live entities, blueprint and sufficient history |
| Polish/English and layout | Localized labels, provenance and missing-data guidance; shared millilitre formatting and theme styles | Card, smoke and language regressions | Light/dark, narrow/zoomed layout, keyboard/focus and no flicker in HA |
| Privacy and sharing | Local state; optional reviewed contribution drafts; no automatic transmission | Diagnostics/sharing/contribution tests and source review | Live preview/cancellation and redaction review |

## Live acceptance matrix

| Scenario | Existing evidence | Whole-scenario status |
|---|---|---|
| Public baseline fresh installation | Earlier package/API evidence retained | Open: native HACS and card flow |
| Public baseline upgrade | Earlier settings/baseline migration evidence retained | Open: native upgrade/reload/restart |
| Exact candidate loaded assets | Current code and CI | Open: loaded asset identity/cache and native rendering |
| Candidate fresh and upgrade | Earlier candidate package/API migrations retained as history | Open: changed candidate installation and migration |
| Shared staging restoration | Earlier byte-exact restoration and readiness evidence retained | Open for a new candidate run; baseline/restore must be checked again |
| Administrator and household roles | Earlier scoped checks and subscription regressions retained | Open: all current-candidate role flows |
| Layout and accessibility | Source/card harness coverage retained | Open: themes, phone width, Sections neighbors, zoom and keyboard |
| First run and recovery | Setup/storage tests retained | Open: no robot, unknown model/capacity, resource registration, reload/restart |
| Reported device paths | Separate reproductions and drafts for issues 10–13 | Open: authors' hardware; no blanket issue closure |

## Installation, upgrade and privacy

HACS category is **Integration**, minimum HA is **2025.1.0**, and the bundled card uses
`custom:ha-vacuum-water-monitor`. Follow the README installation flow; do not reinstall
as a frontend plugin. Upgrading v5 preserves server-side settings, calibration and history.
The v4 browser-only counters cannot be claimed as migrated server history. Retain an HA
backup before an installation/upgrade; a new full-tank baseline is a real user action,
not a routine migration step.

Use README Privacy and the diagnostics sanitization guide. The HA download redacts
user names but can retain identifiers and timestamps. It is not an anonymous public
attachment. The optional summary excludes household identifiers, is disabled by default
and requires the user's reviewed manual submission. No fleet endpoint is enabled.

## GitHub issue boundaries

- #10: actual Tapo Matter mode is recognized; no verified ml/min rate exists in its profile. Guidance is corrected, automatic water tracking remains unconfirmed.
- #11: H50 Pro identity/health matching is corrected in source; missing telemetry and device-specific rate applicability remain open.
- #12: short area-only recovery no longer prematurely invalidates a bridged tank. The reporter's screenshot cannot establish which signal disappeared; do not claim all dropouts or restart cases fixed.
- #13: S7 MaxV/a27 recognition is independent of entity name. An unverified dock capacity remains unknown.

Each reply remains a separate unsent draft until acceptance and release. Publication and
reply approval remain separate from code/CI success. Physical accuracy requires an
authorized measurement, not a synthetic fixture or an empty-tank calibration anchor.
