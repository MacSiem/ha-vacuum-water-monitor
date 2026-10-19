# TapoVac-ADV: experimental RV50 support

VWM 5.13 consumes the existing [TapoVac-ADV integration](https://github.com/jan-tdy/TapoVac-ADV), domain `tapo_rv30`. Install and configure that integration separately. VWM reads Home Assistant states; it does not connect to TPAP, store Tapo credentials or send robot/dock commands.

The upstream authors report testing the RV50 Pro Omni (EU). VWM's automated tests use synthetic producer-shaped telemetry. Actual values and firmware behavior on the issue #10 tester's robot still require verification. This is an estimate, not a direct measurement of water in ml.

## Install the beta

This version is **5.13.0-beta.1**, a GitHub prerelease. The stable release remains 5.12.0.

1. In HACS, open Vacuum Water Monitor, choose the three-dot menu and **Redownload**, enable **Show beta versions** if shown, and select **v5.13.0-beta.1** explicitly. If the beta is not listed, use **Update information** first. Newer HACS versions also provide a prerelease switch on the repository device; see the [HACS beta switch documentation](https://www.hacs.dev/docs/use/entities/switch/).
2. Download the selected beta, restart Home Assistant, then refresh the VWM dashboard. Check that VWM reports **5.13.0-beta.1**.
3. If TapoVac-ADV is not installed, follow its [installation guide](https://github.com/jan-tdy/TapoVac-ADV#installation-via-hacs): add its repository to HACS as an Integration, download, restart, then add and configure **Tapo Robot Vacuum** in Settings → Devices & services. Keep credentials in that integration, not in an issue comment.
4. Configure the native vacuum and the confirmed current-mode entity as described below. Keep one tracking owner for the robot before starting a full-tank learning cycle.

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

## Confirm the current mopping mode

TapoVac-ADV does not currently expose an unambiguous vacuum-only versus active-mopping phase. VWM therefore needs an explicitly configured `cleaning_mode_entity` or `mop_mode_entity`. A sequential plan such as Vacuum then Mop does not identify the current phase.

If your Matter integration reports a current mode such as `Vacuum and Mop;Deep Clean`, first confirm that it belongs to the same physical robot. Then explicitly assign that entity in the VWM card configuration. For example, adapt the existing device entry:

```yaml
devices:
  - vacuum_entity: vacuum.your_tapovac_robot
    cleaning_mode_entity: select.your_confirmed_matter_clean_mode
    rate_signal: mop_intensity
```

This example needs no manually entered water rates. Confirm a full tank with Refilled, use the robot normally, and report Tank empty when the tracked tank runs dry. VWM observes the `clean_time_min` counter only while the confirmed mode and raw status identify mopping. After three compatible full-to-empty tanks, it can use a private nominal whole-tank rate starting with the next confirmed full tank. Before then the rate stays unknown. Missing counters, active counter resets, telemetry gaps, changed settings or a refill during a partial cycle invalidate that sample. The 5% residual remains an explicit assumption, not a measurement.

Native Tapo does not inherit class-prior coefficients or intensity multipliers. Advanced existing `usage_ml_per_m2`/`usage_ml_per_active_minute` configuration can still use independently established per-level coefficients (`low`, `medium`, `high`); ordinary use does not require users to perform or enter manual measurements.

The two vacuum entities may appear as separate robots in VWM. Confirm their duplicate relationship in the card and choose one tracking owner before using both connections. Matching model names are insufficient. Linking prevents a second balance; it does not automatically copy signals, add old counters together or transfer calibration banks. Keep the existing Matter owner if you want to preserve the 5.12 nominal-time workflow. Switching to native counter-based tracking starts its own full-tank learning context after an honest full-tank baseline; an old time calibration is not a measured area rate.

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

Source inspection pinned on 19 October 2026: TapoVac-ADV `887050da97aa63db1ca0fd39b7d61aa97a9bf796`, cavefire `265a24f9f17536a646d18efaa57bdcbd428d9009`. Latest stable HA was 2026.10.2; the latest published beta 2026.10.0b7 predates it. Source/CI inspection is not a robot test or proof that TapoVac works on every HA beta.
