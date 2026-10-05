# Model support and evidence matrix

This matrix explains what a model row means in Vacuum Water Monitor. The dated
[coverage table](consumption-model-coverage.md) lists the currently researched models and
sources. Recognizing a model ID only identifies a candidate; it does not prove the Home
Assistant integration exposes the required signals, that a listed tank belongs to the
tracked reservoir, or that a consumption rate applies.

The [October model evidence review](model-evidence-review-2026-10-05.md) covers all
133 catalog rows, adopted capacity facts, rejected transfers and unresolved sources.

## 5.9.0 automatic-start audit — 5 October 2026

The current runtime resolver supplies a labelled provisional prior for all 133
catalog rows. This does not mean that all 133 can account for water immediately:
only 73 rows have a known tracked capacity, and the installed integration must
expose matching mopping, exposure and settings signals. Confirming a full tank
establishes a baseline; it cannot create a missing time rate or signal binding.
Unknown models can save a capacity, but model identity and capacity alone do not
establish automatic consumption accounting.

| Manufacturer | Catalog rows | Known tracked capacity | Runtime prior basis |
|---|---:|---:|---|
| Cecotec | 2 | 0 | 2 generic |
| Commodore | 1 | 0 | 1 generic |
| Dreame | 22 | 15 | 9 class, 13 generic |
| Ecovacs | 7 | 6 | 3 class, 4 generic |
| eufy | 7 | 4 | 5 class, 2 generic |
| Eureka | 6 | 2 | 1 class, 5 generic |
| IKOHS | 1 | 0 | 1 generic |
| iRobot | 7 | 5 | 7 generic |
| MOVA | 7 | 6 | 5 class, 2 generic |
| Proscenic | 1 | 0 | 1 generic |
| Roborock | 42 | 15 | 39 class, 1 family-transfer, 1 generic, 1 owner-device |
| Samsung | 2 | 1 | 2 generic |
| SwitchBot | 2 | 0 | 2 class |
| Tapo | 9 | 9 | 9 class |
| Viomi | 2 | 0 | 2 generic |
| Xiaomi | 15 | 10 | 4 class, 11 generic |

Counts come from `model_profiles.json` resolved through `profiles._resolved` and
`estimation.estimate_for_record`, including runtime reservoir inference. The
raw catalog's `manual_only`/`calibration_required` fields and empty empirical
rates therefore must not be read as the final runtime estimate classification.
The runtime uncertainty labels describe the prior basis; they are not measured
accuracy bounds for every listed model. The prior band is retained until at least
three accepted complete cycles. After that, the displayed calibration spread
describes agreement between cycles, not verified physical accuracy. Direct volume
sensors and authored rates do not inherit catalog-prior uncertainty. Invalid cycle
factors outside 0.25–4, nonfinite factors and nonpositive factors are rejected
instead of clipped into plausible training data.

There are zero approved shared consumption profiles in the bundled snapshot.
The independent per-model coverage gates remain incomplete for all catalog
rows. Synthetic adapter and accounting tests verify behavior, not physical
volume accuracy. Universal out-of-the-box accuracy remains an open requirement;
it cannot be accepted from recognition, a green test suite or a generic prior.

| Model row status | Detection | Data available | Estimate scope | Limits and calibration |
|---|---|---|---|---|
| Recognized candidate | Catalog identifier or a source names the model | Identity and possibly capacity/options | None by identity alone | Confirm the exact integration, firmware, reservoir and settings. A capacity is not consumption. |
| Labelled catalog estimate | Mopping model plus usable mop/exposure signals | Class or explicit model prior, with basis and uncertainty label | Provisional per-area floor use and observed dock washes; remaining percentage also needs a refill baseline and capacity | A prior is not a measured device rate. An unmapped water-output level or accounting gap makes the current balance incomplete. |
| Integration mapped | Same-device Home Assistant roles resolve without ambiguity | Area, duration, state or settings only when actually exposed | A local/user calibration may use its matching exposure | Missing or changed signals keep accounting unknown; an ID match never fills gaps. |
| Physical volume available | Explicit same-reservoir mL/L sensor | Current measured volume and unit | Direct remaining/used volume for that reservoir | Unit, range and reservoir must match. A percent or generic tank enum is not volume. |
| Local calibration | User's complete, measured refill cycles | Measured refill, area or duration, context and validation history | Only the recorded device/context and declared scope | It stays private; changing firmware, settings, reservoir or exposure invalidates applicability. |
| Shared dataset record | Imported versioned contract | Evidence, context, scope and source tier supplied by the dataset | Only the exact model/SKU/firmware/integration/reservoir/action/settings match | The app rejects incompatible or incomplete records rather than choosing a nearby model. |

## Evidence tiers

| Tier | Meaning in the UI and documentation | Can it produce a number? |
|---|---|---|
| Measured | Physical volume or a repeatable user measurement with known context | Yes, within the stated device, reservoir and scope. |
| Manufacturer data | A dated manufacturer claim such as capacity, supported mode or declared action quantity | Only for the exact stated claim; it is not silently converted into a per-cycle rate. |
| Derived estimate | A clearly labelled catalog prior or calculation from disclosed assumptions and inputs | Yes when the live signal path supports it, with its source and limits. It is never presented as measured. |
| Unknown | Identity, signal, unit, context or evidence is missing | No. The card keeps the value unknown instead of inventing a fallback. |

The shipped v0.2.0 snapshot contains two **Manufacturer data** entries for Xiaomi H50 Pro:
180 ml for an explicitly identified first-time mop wash and 120 ml for an explicitly
identified mid-task mop wash. They retain the manufacturer basis and limitations in
Diagnostics. Their HA completion binding, SKU and firmware are unknown, so they do not
increment automatic consumption or a completion counter. The snapshot contains no
approved shared rates.
The coverage table's source counts and option counts show what is available for each model;
they do not imply the other columns are supported.

## Current Roborock evidence

The private read-only shadow review established that Water Monitor can inspect local event
history without operating the household robots. It did **not** contain a physical measured
water volume, an approved shared profile or a hardware-verified live source contract.
Therefore the Roborock evidence is useful for discovery and replay diagnostics. The
catalog's labelled priors may produce a provisional estimate for a mapped robot; this
review does not validate their physical accuracy or turn them into a universal Roborock
rate. Device calibration still needs a real full-to-empty tracked tank cycle.

## Contributing a partial session

Partial data is useful. Send only the fields you have; mark every missing field as
`unknown` instead of filling it from a similar model:

```text
model: public model/SKU and region, if known
integration: name and version
firmware: version, if shown
reservoir: robot clean / dock clean / dock dirty / detergent / unknown
settings: mop mode, water level, route, passes, wash mode/frequency/temperature, if exposed
area: m² or unknown
duration: active or cleaning duration with unit, or unknown
mop washes: completed count or unknown
water used: measured mL/L, manufacturer-declared quantity, derived estimate, or unknown
evidence tier: Measured / Manufacturer data / Derived estimate / Unknown
relative sequence: start +0, wash +18 min, finish +42 min (no absolute timestamps)
```

Before posting, replace all entity/device/config-entry/unique IDs with stable sample aliases
such as `vacuum.sample` and `sensor.sample_area`. Remove tokens, accounts, serials, MAC/IP
addresses, room names, maps, coordinates and absolute times. Preserve units, canonical
property/translation key and the relative event order so a maintainer can reconstruct the
session without receiving private household data.

## Runtime handoff points

The frozen tier contract is integrated at these boundaries:

| Boundary | Current responsibility | Required tests before activation |
|---|---|---|
| `profiles.resolve_consumption_profile` | exact context match and source selection | tier preserves source/limits; incompatible context stays unknown |
| `tick.tick_device` | applies selected area/time/action/volume accounting and records diagnostics | manufacturer labels survive without charging when completion binding is unknown; no double counting |
| `sensor_calculations` and card diagnostics | expose resolution and reason to the user | labels are escaped, readable and never reported as physical measurement when derived |
| `scripts/import_consumption_data.py` | validates, diffs and atomically installs snapshot | unknown/derived records obey the frozen contract; rollback remains exact |

The v2 importer stores estimates separately from empirical profiles and rejects an estimate
without its basis. Context mismatch remains `Unknown`; a capacity or model-family match
does not select an estimate.
