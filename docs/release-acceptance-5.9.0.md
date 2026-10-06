# 5.9.0 features and acceptance boundaries

Updated 6 October 2026. This is a candidate, not a public release. Model recognition,
automatic estimation and physical accuracy are separate claims. Unit and CI checks
verify code behavior; they do not replace live HACS and household-interface acceptance.

## Function matrix

| Function | Candidate behavior | Code evidence | Live evidence and remaining limits |
|---|---|---|---|
| Discovery | Registry-based, same-device signals; S7 MaxV/a27 and H50 Pro/ov42gl aliases survive entity renaming | Discovery, adapter and real-runtime regressions | Authors' exact firmware/integration and native reprofile |
| Floor accounting | Area first; explicitly supplied time rate can cover active intervals; no guessed area-to-time conversion | Tick, runtime and numeric-output regressions | Actual model/integration settings and physical volume |
| Short area dropout | A bounded gap can recover without a time rate when the cumulative counter and settings remain valid | `test_issue12_area_recovery.py`; unchanged gap-protection regressions | Normal use on the reporting Qrevo |
| Vacuum-only and settings | Affirmative mop evidence required; unknown output levels do not silently use a default | Runtime and numeric range tests | Exact device telemetry |
| Mop washing | Separate observed wash sequence, counted once; whole-cycle calibration excludes extra wash dosing | Tick and refill/calibration regressions | Device-specific wash visibility and water amount |
| Refill | Card, device button, service, bound button/lid and eligible dock clear share bookkeeping; deduplication retains intervening use | Refill and runtime tests | Routes, auto-refill switch and deduplication accepted on live synthetic fixtures; device-specific refill truth still depends on its signal |
| Calibration | Complete refill-to-empty learning; incomplete/outlier samples excluded; authored measurements stay separate | Calibration, local-measurement and replay tests | Live rejection/refill accepted; saved-history replay with frozen later comparison; full refill after empty accepted as the owner reference, nominal capacity still disputed; physical metered accuracy unknown |
| Tank settings and history | Per-robot capacity and baseline/history preserved; session water formatted without changing original records | Setup, storage and presentation regressions | Native fresh/upgrade, reload/restart and public-version preservation accepted |
| Health and Repairs | Missing rate explains calibration rather than an ineffective full-tank Repair; unknown stays unknown | `test_issue10_missing_rate.py`, setup and card tests | Native first-start, missing capacity and saved-capacity guidance accepted |
| Forecasts and reminders | Cleanings/days and forecast error use available tank history; genuine zero differs from missing data | Forecast, setup and presentation tests; blueprint in repository | Actual HA forecast entities and blueprint notification after60s accepted; forecast error is not measured water accuracy |
| Polish/English and layout | Localized labels, provenance and missing-data guidance; shared millilitre formatting and theme styles | Card, smoke and language regressions | Light/dark, narrow/wide, keyboard/focus and stability accepted; 180CSS reflow accepted with an explicit emulation limit |
| Privacy and sharing | Local state; optional reviewed contribution drafts; no automatic transmission | Diagnostics/sharing/contribution tests and source review | Live cancellation without transmission and admin/household diagnostic access accepted |

## Live acceptance matrix

| Scenario | Existing evidence | Whole-scenario status |
|---|---|---|
| Public baseline fresh installation | Native HACS 5.7.0, 28 exact files; setup/card/history/reload in `native-stage/public-baseline-fresh` | Accepted for that unchanged baseline |
| Public baseline upgrade | Native HACS 5.6→5.7, exact 25/28-file public packages, HA restarts and native history; nondefault HA options23/11, counter160ml, four tanks, calibration and history preserved in `native-public-upgrade-qa` | Accepted; isolated reused QA clone, with new settings/exposure produced by the running old version |
| Exact candidate loaded assets | Ordinary Browser reload, 752465 exact module bytes, no disk/SW cache in `native-manual-qa/browser-resource-readback.json`; saved duck/dodo icons absent in Water, Stats, Settings and after reload | Accepted for the repaired runtime/card package |
| Candidate fresh and upgrade | Native 39-file candidate fresh/upgrade, baseline/calibration/history preserved in `native-stage`; repaired package downloaded exactly and changed paths verified in `native-manual-qa` | Accepted within the tested software scope |
| Shared staging restoration | Seven sessions restored and read back; 20 entries, 19 foreign, Baby 24 categories/timers, Network Map 3 devices | Accepted through `native-public-upgrade-qa/restore-runtime-readback.json`; no pending restore |
| Administrator and household roles | Native settings/refill/reload; diagnostics admin200/household401; cancelled sharing without transmission in `native-stage/household-*` | Accepted for unchanged role behavior |
| Layout and accessibility | PL/EN, light/dark390/1440, keyboard/draft, details stability; 360 Sections and 180CSS reflow with neighbor | Accepted with owner-approved limit: saved180CSS emulation, not actual browser200% zoom; unchanged CSS verified, latest full180px DOM not rerun |
| First run and recovery | Native no-robot setup, unknown capacity, reprofile/focus, reload/restart; actual forecasts and blueprint reminder after60s; repaired manual Tapo conflict verified in native card and HA sensor | Accepted within the tested software scope |
| Reported device paths | Separate real-runtime reproductions, live fixture paths and drafts for issues10–13 | Accepted for reproduced software paths; authors' exact hardware/firmware stays unverified, with individual post-release retest guidance and no blanket closure |

The manual-profile regression is repaired in the backend and bundled card, including sparse
manual settings with generated legacy defaults. A locked Tapo keeps its rotating-pad class,
sources and initial50% prior band despite conflicting Roborock discovery. Authored rates and
signal bindings remain authoritative. The repaired package passed566 unit tests,16 card
checks, independent review and live HA/HACS acceptance. Actual HA rejected two8000ml and
two1600ml cycles on a1200ml tank without learning, kept the pending sample empty and
performed automatic refills after the real cooldown. These are synthetic functional checks.

The source review covers133 models from16 manufacturers and73 known tracked capacities.
No additional measured consumption rates were inferred from capacity or advertised runtime.
Available local history was replayed, with learning frozen for later comparison. The owner
confirms full refills after empty signals and accepts these as a nominal reference. Both
3000ml and4000ml capacity hypotheses were replayed with targets2850ml and3800ml
(the5% residual is assumed). Their recalculated factors are0.965736 and1.287648; both
later conditional anchor differences remain−0.3% and−17.1%. Scaling the training and
target together does not identify capacity or establish measured accuracy. Device identity
and physical dock capacity must be reconciled before choosing one calibration. Physical
accuracy remains unknown without an independent volume or mass reference; verifying every
model physically is not a release requirement. The owner accepts saved180CSS reflow
evidence with its emulation limit; actual browser200% zoom is a later supplementary check.
Remaining acceptance covers the disputed dock identity, final review and public delivery.

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
