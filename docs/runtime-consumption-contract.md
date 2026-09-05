# Runtime consumption and private calibration — 2026-09-05

The application now has a consumption resolver separate from the capacity/model resolver.
The pinned snapshot still contains **zero approved profiles**. Synthetic tests establish
code behavior, not firmware compatibility, completeness or physical accuracy.

## Applicability and precedence

`profiles.resolve_consumption_profile(context, signals, calibration, dataset)` returns
source, method, coefficient/unit, profile/evidence IDs, dataset revision, validation
metrics and a reason. A configured physical volume sensor remains authoritative across
unavailable samples; a gap never silently selects a model estimate.

Next are compatible per-device measured calibrations, then an approved shared profile.
The shared profile needs its exact context, nonempty provenance, separate training and
validation cycles (at least 3 and 5), at least 3 devices, finite error metrics and an
applicable exposure range. Approved status alone is insufficient. Multiple compatible
profiles fail closed. No equivalence/fallback contract exists in dataset v1, so there is
no guessed nearest-model or middle-mode fallback in this resolver.

Context includes exact dataset model ID, SKU, dock variant, firmware, integration ID and
version, reservoir, action, and all 13 settings from the dataset contract. Null/unknown is
not a wildcard. Registry firmware overrides an older configured context. Bound setting
entities override configured context on every tick. Missing model/firmware/settings are
retained as explicit gaps in historical context, never filled retrospectively.

For v1 floor area/time profiles, the **charged increment**, not the cumulative robot
counter, must fall inside the profile's exposure domain. Unsupported or ambiguous
exposure produces unknown. A profile trained on complete cycles cannot automatically
be treated as an interval profile; dataset v2 must make this observation boundary explicit.

The legacy authored calibration UI remains available. Its manually declared rates do not
become a shared approved profile. New private measurements are stored separately, by
vacuum/history owner and exact context; changing settings does not delete older fits.

## Private measurement flow

History has a separate **Save private measurement** action. It requires measured refill
ml, instrument resolution, instrument, training/validation purpose, full-to-full bounds
and an uninterrupted cycle. The backend reselects the recorded timestamp under the
storage lock. A stale selection or duplicate cycle is rejected. A cycle cannot be both
training and holdout. Up to 200 samples per device are retained without silent eviction.

Only a cycle observed from zero area, with positive complete area and one unchanged
historical context, can fit. Three distinct measured cycles fit one total ml/m² dose.
This is a **private whole-cycle model**: it includes dock washes and is charged once at
completion, never as floor plus wash. A reset, unavailable interval, area anomaly,
firmware/settings change or refill during the cycle invalidates it. The profile applies
only inside the measured area range. Holdout cycles report observed error and never
change training coefficients. No error is a guaranteed bound or 95% confidence interval.

This private `area + whole_cycle` representation is deliberately **not** a dataset-v1
profile (v1 permits whole_cycle only with ml/cycle). It is not exported/imported as an
approved record. The schema-v2 handoff must resolve that distinction before portability.

The contribution preview remains a separate read-only numeric allowlist and download.
It does not upload data or save a calibration. Full public-context export remains gated
on reviewed public enum/model allowlists; private historical entity IDs are not exported.

## Reservoirs and completed actions

`reservoir_volume_sensors` may explicitly bind one numeric `sensor.*` per dock clean,
dock dirty, robot clean, robot dirty and detergent reservoir. Only mL/L is accepted.
A sensor assigned to two reservoirs is ambiguous. Missing values, unknown units, negative
values and measurements exceeding known capacity return unknown. These independent levels
are not summed into invented system consumption: dock-to-robot transfer is not two uses.
Plumbed installations have no fictional finite tank capacity or percentage.

A v1 approved wash-only profile additionally needs an explicitly bound
`wash_completed_sensor`: a monotonic **completed-action** counter. The increment must
be exactly one after observed actual washing, with continuous state and matching context.
Navigation to wash, a command, initial observation or ending a phase alone does not prove
completion. No integration has yet been automatically bound to this new counter role;
source/firmware contracts are required first. Tests use synthetic counters explicitly.
Tray cleaning, flush, internal refill and detergent actions require their own completed
contracts and reservoir semantics. They are not inferred from generic dock cleaning.

After an unaccounted interval, the aggregate remains unknown until a new full-refill
baseline or an authoritative physical volume reading. Numeric internal counters and
historical calibration are preserved, but are not presented as a complete water balance.

## Verification and remaining dependencies

Runtime regressions: `test_profile_selection.py`, `test_consumption_runtime.py`,
`test_local_measurements.py`, `test_measurement_websocket.py`, `test_reservoir_balance.py`
and the expanded discovery/calculation/storage tests. Both card copies are exercised by
`.github/sprint.cjs`. The synthetic harness covers phone width, themes, keyboard, readiness,
confirmation, success and failed acknowledgement. This is not a production HA deployment.

The frozen [dataset handoff](dataset-handoff-2026-09-05.md) owns full SKU/options/bindings,
profile observation boundaries, hybrid/component balance contracts and real evidence.
The shared [sprint ledger](app-sprint-ledger.json) retains unresolved criteria and owners.

## Portable v2 integration, 2026-09-05

V1 bundles remain importable as evidence-only snapshots; a v1 profile cannot
become an active shared rate. V2 shared profiles must pass empirical eligibility,
full record validation and measurement lineage checks. Personal calibration and
physical sensors do not depend on a supported shared dataset version.

The app's `accounting_v2.py` separates synthetic replay from live physical streams.
It preserves event identity across storage, rejects conflicting repeats, negative
intermediate volumes and unsupported detergent conversions, and records distinct
setting segments. Explicit external supply/drain never creates an inferred tank
percentage. Unknown or stale sources hide the balance, retaining a private
immutable journal for recovery from a complete source log. Raw journal and device
identity are omitted from public sensor attributes.

No live event source is approved: the source registry is empty. The received
fixture cannot activate this path. The exact app extension and required dataset
corrections are in `dataset-v2-followup-2026-09-05.md`. No physical accuracy claim
or synthetic rate promotion is implied by replay tests.

When an event stream is configured, its unavailable/unknown state also hides the main tank value. A known stream supplies the tracked physical volume but no inferred consumed volume or percentage; a direct volume sensor retains priority.

The reviewed V3 contract replaces the earlier provisional time representation
with Unix epoch milliseconds. Native live consumption also requires a second,
code-owned binding from the exact HA entity to the reviewed contract and complete
device identity. Both live registries remain empty. Full hashes, compatibility
rules and remaining evidence blockers are recorded in
`dataset-v3-integration-2026-09-05.md`.
