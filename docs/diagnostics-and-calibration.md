# Diagnostics and measured calibration

Open the card's Water → Diagnostics. Record the method, evidence/confidence, tracked
reservoir, profile resolution, signal contract and reason code. `unknown` is intentional:
a model name or capacity cannot establish a consumption rate.

## Calibrate one reservoir

1. Confirm whether the counter tracks dock clean, dock dirty, robot clean/internal or
   detergent. Never use the waste tank's size as the clean tank's consumption.
2. For an ordinary complete cleaning, measure the water needed to restore the same
   clean reservoir to the same full reference. Record area or active minutes, mode,
   intensity, firmware/integration versions and wash count. Exclude spills and unrelated
   manual drains. Repeat under comparable conditions; retain sample count and range.
3. In Maintenance → Your measurements (optional) select **Whole cycle** when the refill measurement
   includes dock washing. Enter measured loss / measured area (ml/m²) or measured loss /
   active minutes (ml/min). The axes are independent; there is no assumed cleaning speed.
4. Select **Floor only** only if floor water and dock-wash water were measured separately.
   Then a measured ml/wash may coexist with the floor dose. A wash sample never also
   charges floor/time. A wash-only calibration can be used without an area/time rate.
5. Press **Refilled** only at the full reference. Closing a lid or clearing a shortage
   warning does not prove a full refill. An explicit same-reservoir real mL/L sensor is
   authoritative and can report remaining water without a manual full baseline.

One cycle can seed a device calibration, but cannot independently validate a rate derived
from that same cycle. A subsequent comparable measured cycle is the accuracy holdout.
Do not report an error percentage without separate prediction and physical observation.

## Read-only production shadow

`scripts/shadow_capture.py --help` describes the local collector. Its secret argument is a
file reference; never put a token in CLI text. The collector uses only GET states/history
and registry-list WebSocket commands, sanitizes identity in memory and writes aggregate
counts/reasons only. It neither operates a vacuum nor changes Home Assistant.

Recorder-event replay is not a scheduled live deployment test. Missing recorder samples,
unknown mop evidence and unmeasured consumption keep predicted/observed values null.
No raw registry, entity IDs, location, device names or Diagnostics are written.

## Share a useful, sanitized report

In **History → Optional measurements and contribution drafts**, normal tracking continues
without manual measurements. Before a future cycle, expand **Prepare optional future
measurements** and declare only known technical settings not exposed by HA. Leave unknown
values blank; `not_applicable` means the device does not have that setting. Bound HA
telemetry takes precedence, including an unavailable signal. Saving a plan does not
operate the robot, alter a past cycle or certify the accuracy of declared settings.

Select a complete recorded cycle, enter independently measured full-to-full refill volume,
instrument and resolution, and confirm the reservoir boundaries and uninterrupted cycle.
**Save private measurement** stores the measurement locally. Three distinct training samples
with the same complete context fit an experimental whole-cycle ml/m² approximation within
the measured area range. Outliers do not train it; separate validation samples do not change
the fit. Training spread and resolution are not systematic-error bounds. Outside the range,
available automatic estimates continue. Missing historical settings cannot be filled with
current settings. Elapsed duration is not active mopping time.

Expand **Share a confirmed measurement (optional)**, enable preview and select a saved
physical measurement. Inspect every field of **Preview contribution draft**, then tick
consent for that exact packet. Only then can **Download reviewed draft** save the displayed
JSON. Attach it yourself to the maintained dataset measurement form. The form link contains
only a template selector, never measurement data. No automatic upload or robot operation
occurs. OFF, selection changes and changed saved measurements invalidate the old consent.

The packet projects technical model/SKU/dock, firmware, integration, reservoir, settings,
measured dose/area, resolution and quality. Private identifiers, absolute dates, names,
accounts, tokens, MAC/IP addresses, rooms, maps and raw histories are excluded. Unknown
technical values remain null and require review. Technical combinations may still identify
a device indirectly; GitHub publishes the contributor account. Contributions remain
experimental and runtime-ineligible until independent qualification. Request withdrawal
in the dataset repository; public copies may remain. See [privacy](../PRIVACY.md).

Use Home Assistant's integration Diagnostics download only when the device owner chooses
to provide it. Keep the original local. Create a separate sanitized copy before sharing:
remove tokens, account IDs, serials, MAC/IP addresses, home/room names, maps, coordinates,
entity/device/config-entry/unique IDs and user labels. Replace relationships consistently
with `device.sample`, `vacuum.sample`, `sensor.sample_area`, preserving platform,
translation_key/canonical property, units, numeric values and event order.

Include model/SKU and region from the product label, firmware and integration versions,
tracked reservoir and the small relevant event sequence. State whether data is hardware
Diagnostics, synthetic contract data or empirical measurement. Submit only the sanitized
copy to the existing relevant issue; never upload raw private HA data.

### Public issue intake template

Use this compact template in an issue or a future public dataset contribution. It is
enough to diagnose the integration path without exposing a household installation:

```text
Integration version:
Model/SKU and region:
Firmware:
Tracked reservoir:
Entity domain and canonical property/translation key (replace IDs with sample aliases):
Relevant attributes, units and state transitions:
What happened and when in the cleaning/wash cycle:
```

Keep the original Diagnostics archive private. Before sharing the template, remove tokens,
account IDs, serials, MAC/IP addresses, device/entity/config-entry/unique IDs, home or
room names, maps, coordinates, user labels and absolute timestamps. Preserve only the
entity domain, canonical property or translation key, units, sanitized attributes and the
relative order of relevant events.

For a mopping or mop-wash session, partial evidence is welcome. Add model, integration,
firmware, reservoir, settings, area, duration, completed mop washes and measured water
used only when each is available; mark the rest `unknown`. Label a numeric claim as
**Measured**, **Manufacturer data**, **Derived estimate** or **Unknown**. Use relative
times such as `wash +18 min`, never an absolute household timestamp. The full field list
and evidence meanings are in the [model support matrix](model-support-matrix.md).

Current repository fixtures are **synthetic contract fixtures**, not redacted recordings.
They validate bindings/units and foreign-device rejection, not firmware compatibility.

## State and migration boundaries

- Restarts/reloads retain counters, history and calibration. Active-time intervals over
  180 seconds are not dosed blindly. A cumulative area counter may cover a gap up to
  5 minutes only with continuity, sufficient cleaning progress and unchanged settings.
  A short area-only dropout waits for that decision even when no time coefficient exists;
  it never invents an ml/min dose. Long, discontinuous or setting-changing gaps keep the
  tank incomplete until a real new baseline.
- Decreasing area/time counters establish a new baseline. Wash latches survive reset so
  one ongoing wash is not charged twice.
- Reprofiling preserves authored fields/history and removes generated profile locks.
- A changed model, adapter, reservoir, sensor/rate or measurement scope invalidates
  sample baselines and learned correction factors; counters/history are not added together.
- Storage changes are additive. Tests preserve unknown future fields during reset/reprofile;
  this is not certification of every older HA/plugin executable. Keep an HA backup before
  any future owner-authorized release/upgrade. No such production change is part of this sprint.

## Private measured wizard (replacement sprint)

History now also offers **Save private measurement**, separate from contribution preview.
It requires complete historical context, a single uninterrupted cycle observed from zero
area, measured refill/resolution and explicit boundaries. Three distinct training cycles
fit one private whole-cycle ml/m² dose; validation cycles never change the fit. The dose
replaces that session’s provisional floor/wash estimate atomically at completion; the
audit retains superseded events, and unrelated session doses remain intact. Missing historical
fields are displayed before fitting. See [the runtime contract](runtime-consumption-contract.md)
for applicability, unknown totals, independent reservoir levels and limitations.


## Intermittent unknown after signal loss

`accounting_incomplete` records a tank-wide loss of accounting coverage, not necessarily
a current unavailable robot. `last_accounting_reason` describes only the latest tick;
it can become `area_delta_below_minimum` after an earlier gap. That code alone cannot
identify the original dropout or prove a Home Assistant restart.

For a report, retain the relative order of status, area, duration and wash transitions
from ordinary use, including the last valid counter before the gap and its first recovered
value. Include whether the integration or HA restarted, only if known. Use the sanitized
fields above; no extra run, tank reset or private raw export is needed. A restarted
area counter, a mode change, an unobserved wash or a long gap cannot be repaired by
assuming all elapsed time was floor mopping.

The 5.9.0 area-only recovery fix covers one reproduced false-incomplete path. It does not
prove the cause of every intermittent unknown report or the accuracy of a physical tank.
