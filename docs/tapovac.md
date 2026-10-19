# TapoVac-ADV: experimental RV50 support

VWM 5.13 consumes the existing [TapoVac-ADV integration](https://github.com/jan-tdy/TapoVac-ADV), domain `tapo_rv30`. Install and configure that integration separately. VWM reads Home Assistant states; it does not connect to TPAP, store Tapo credentials or send robot/dock commands.

The upstream authors report testing the RV50 Pro Omni (EU). VWM's automated tests use synthetic producer-shaped telemetry. Actual values and firmware behavior on the issue #10 tester's robot still require verification. This is an estimate, not a direct measurement of water in ml.

## Install the beta

This version is **5.13.0-beta.2**, a GitHub prerelease. The stable release remains 5.12.0.

1. In HACS, open Vacuum Water Monitor, choose the three-dot menu and **Redownload**, then **Need a different version?** and select **v5.13.0-beta.2** in the release picker. If the beta is not listed, use **Update information** first. Newer HACS versions also provide a prerelease switch on the repository device; see the [HACS beta switch documentation](https://www.hacs.dev/docs/use/entities/switch/).
2. Download the selected beta, restart Home Assistant, then refresh the VWM dashboard. Check that VWM reports **5.13.0-beta.2**.
3. If TapoVac-ADV is not installed, follow its [installation guide](https://github.com/jan-tdy/TapoVac-ADV#installation-via-hacs): add its repository to HACS as an Integration, download, restart, then add and configure **TapoVac-ADV** in Settings → Devices & services. Keep credentials in that integration, not in an issue comment.
4. Keep Matter connected. Open VWM and confirm **Link robot** only if the suggested Matter and TapoVac entries are the same physical robot. VWM selects the Matter programme automatically and keeps one tracking owner. No YAML or manual rate entry is needed. See below before starting a new full-tank cycle.

To return to stable, use HACS Redownload, explicitly select **v5.12.0**, restart Home Assistant and refresh the dashboard. Returning to stable does not add native TapoVac support; choose the existing Matter owner for that workflow. Do not mark a partially used tank as full just to restart learning.

## Inputs and safe defaults

| Input | Use |
| --- | --- |
| `clean_area` vacuum attribute | Cumulative session area, only when the exact same-entry, same-device area-unit select reports `m²` |
| `clean_time_min` | Observed session minutes, converted to seconds internally |
| `water_level` | Setting off/low/medium/high; off vetoes dosing; does not show remaining water |
| `mop_attached` | False vetoes mopping; true alone never proves active mopping |
| `status_code` | 1 permits cleaning; 2 means mapping and cannot consume water; missing/unknown raw codes open a telemetry gap |

Area and time counters are used as alternatives, never added together for one floor interval. No inferred ft² conversion is enabled: upstream's imperial mapping has not been independently verified, and its area sensor always labels values m². With missing or imperial area units, area accounting is disabled. The observed `clean_time_min` counter and an explicitly confirmed current mop mode can still support automatic nominal learning after three compatible full tanks, without a manually entered rate. An independently established time calibration remains an optional alternative. Missing counters do not authorize a wall-clock guess.

## Link the same robot in the card

TapoVac-ADV does not currently expose an unambiguous vacuum-only versus active-mopping phase. Keep Matter connected: its selected cleaning programme supplies the missing intent signal, while Tapo supplies the observed area/time and water setting. Neither programme nor a mounted mop measures physical water flow. A sequential plan such as Vacuum then Mop does not identify its current phase and cannot activate accounting by itself.

When VWM suggests that the Matter and TapoVac entries are the same robot, press **Link robot** only after confirming this. VWM automatically uses the single linked Matter cleaning-mode select, including labels such as `Vacuum and Mop;Deep Clean`. Matching names or models alone never authorize sharing. A shared registry identity can also establish the link. Ambiguous sources remain unbound. Explicit advanced bindings retain priority.

The selected control is discovered again from the current registry, rather than saved as manual card YAML. Unlinking, removal or loss of the control revokes the automatic binding. Native status, mounted-mop false, water off and unavailable/unknown programmes still veto accounting. Changes are reflected in the open card without reloading the page.

No manually entered rate is needed. Confirm a genuinely full tank with Refilled, use the robot normally, and report Tank empty when the tracked tank runs dry. VWM observes `clean_time_min` during eligible cleaning intervals. After three compatible full-to-empty tanks, it can use a private nominal whole-tank rate starting with the next confirmed full tank. Before then the rate stays unknown. Missing counters, active counter resets, telemetry gaps, changed settings or a refill during a partial cycle invalidate that sample. The 5% residual remains an assumption, not a measurement.

Native Tapo does not inherit class-prior coefficients or intensity multipliers. Advanced existing `usage_ml_per_m2`/`usage_ml_per_active_minute` configuration can still use independently established per-level coefficients (`low`, `medium`, `high`); ordinary use does not require users to perform or enter manual measurements.

The two vacuum entities may appear as separate robots in VWM. Confirm their duplicate relationship in the card and choose one tracking owner before using both connections. Matching model names are insufficient. Linking prevents a second balance and shares only the selected Matter programme. It never adds counters together or transfers calibration banks. Keep the existing Matter workflow until you are ready to start a genuine full-tank cycle with native tracking. Switching to native counter-based tracking starts its own full-tank learning context after an honest full-tank baseline; an old time calibration is not a measured area rate.

## What the source inspection actually establishes

| Data | TapoVac-ADV in HA | Matter in HA | Consequence for VWM |
| --- | --- | --- | --- |
| Session area / time | `clean_area`, `clean_time_min` | No corresponding counters in the inspected VWM adapter | Use native counters, with verified units |
| Water setting / mounted mop | `water_level`, `mop_attached` | No equivalent confirmed tester telemetry | Settings and hardware presence, not flow |
| Selected wet/dry programme | No such exposed field | RVC clean-mode select, subject to the robot's supported modes | Borrow only after confirmed physical identity |
| Current physical wet phase | Not established | Selected programme does not establish pump flow | No physical-accuracy claim; reject sequential-only intent |
| Actual consumed ml | Not established | Not established | Calibrated estimate only |

The local protocol has more fields than these two HA integrations publish. Independent RV50 research in [opentapovac](https://github.com/tobixen/opentapovac/tree/b53d2cc3d73d57164e54bfee2ae16c23e74108da) documents `getCleanAttr(type=global).clean_type`. Both inspected Tapo HA clients discard that field. More importantly, global settings can differ from the current room task, so simply exposing it would not prove the current phase. `clean_mode` / `getCleanStatus.clean_status` describe spatial tasks such as whole-house, room or zone, not vacuum-versus-mop mode.

The same research documents currently unused `getCleanStatus` flags for washing, loading/unloading mops, mapping and relocation, and `getBaseStatus.clean_water` / error 26 for an empty or missing dock tank. These are potential future station-state inputs, not water-volume readings or confirmed complete wash counts. Neither inspected HA producer exposes a complete event contract for VWM. No invented `type=current` or per-wash ml getter is assumed.

RV50 observations show mop removal/attachment during sequential tasks, but [the upstream research TODO](https://github.com/tobixen/opentapovac/blob/b53d2cc3d73d57164e54bfee2ae16c23e74108da/TODO.md#L93) explicitly leaves vacuum-only with a mounted mop unresolved. That evidence does not justify making attachment a positive mopping signal. Protocol/source verification and synthetic HA tests do not establish every field's behavior on the tester's firmware.

## Floor water and station water

No confirmed consumed-water volume, tank-volume reading or completed-wash counter was found in the inspected API. `getVolume` controls speaker volume. Dock probes such as `getBackWashMode` and `getDryMopMode` confirm features/settings, not actual washes or their water use. Other getters in [cavefire/tapo-vacuum-ha](https://github.com/cavefire/tapo-vacuum-ha) expose additional settings, without a verified water dose.

Use floor-only rates only with measurements that exclude station washes. A whole-dock-tank calibration includes station consumption and must not be labelled as physical floor flow. Do not add a guessed wash dose or count a wash because a dock control exists. Automatic separate station accounting remains unavailable until a real event/measurement contract is verified.

## Hardware test checklist for issue #10

1. Record the TapoVac-ADV version, robot firmware and actual entity IDs. Check attributes and the Area Unit select before, during and after a session.
2. Compare `clean_area` and `clean_time_min` with the Tapo app. Verify resets between sessions and behavior after pauses/reconnection. Confirm metric units; do not change robot settings just to pass a test.
3. Verify the confirmed mode reports vacuum-only and current mopping correctly. Vacuum-only with the mop mounted, mapping, water off and missing/unknown mode must leave water use unchanged.
4. Record water-level changes and ensure new settings start a new calibration context. Do not reuse coefficients across settings without measurements.
5. During normal use, confirm full and empty tanks and check provisional progress across three compatible tanks. No manual water measurement is required. Independent physical-volume validation and separation of station/floor consumption remain separate engineering acceptance criteria; nominal repeatability does not establish those results.
6. With Matter and TapoVac enabled, confirm the duplicate link and one accounting owner. Check that history/settings survive restart and that no second tank is accumulating usage.

Source inspection pinned on 19 October 2026: opentapovac `b53d2cc3d73d57164e54bfee2ae16c23e74108da`, TapoVac-ADV `887050da97aa63db1ca0fd39b7d61aa97a9bf796`, cavefire `265a24f9f17536a646d18efaa57bdcbd428d9009`. Latest stable HA was 2026.10.2; the latest published beta 2026.10.0b7 predates it. Source/CI inspection is not a robot test or proof that TapoVac works on every HA beta.
