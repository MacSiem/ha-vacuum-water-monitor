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
3. In Maintenance → Custom calibration select **Whole cycle** when the refill measurement
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

In **History → Help improve consumption data**, select a recorded automatic cycle.
Optionally enter measured refill volume and the instrument's resolution in ml, then
choose **Preview contribution draft**. Review the content before **Download reviewed draft**.
There is no upload, vacuum service call or calibration write in this flow.

The draft contains only numeric cycle summaries, a new random draft ID and fixed guidance.
It excludes device/entity IDs, names, maps and dates. Estimated water stays separate from
your entered measurement. A changed cycle list is rejected instead of attaching the
measurement to a different cycle. Changing the form requires a new preview.

This is a preparation aid, not an approved dataset observation. Historical settings,
public model/SKU/dock, firmware, integration, reservoir and measurement boundaries still
need verification. Current settings are not assigned to an older cycle. Elapsed duration
is not active mopping time, and recorded area delta may omit the first observed interval.
Complete the missing context using the [contribution guide](llm-assisted-contribution.md).

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

- Restarts/reloads retain counters, history and calibration. Missing intervals and gaps
  over 180 seconds rebaseline; no retroactive catch-up dose is invented.
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
is charged once at completion and excludes additional wash dosing. Missing historical
fields are displayed before fitting. See [the runtime contract](runtime-consumption-contract.md)
for applicability, unknown totals, independent reservoir levels and limitations.
