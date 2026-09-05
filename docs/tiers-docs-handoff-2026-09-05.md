# Tiers documentation handoff — 2026-09-05

The app documentation is ready for four public evidence tiers: **Measured** for physical
volume or repeatable user measurement; **Manufacturer data** for the exact dated claim;
**Derived estimate** for an explicit calculation with assumptions and limits; and
**Unknown** when identity, context, source or unit is incomplete. Capacity and a recognized
model ID are not consumption.

[model-support-matrix.md](model-support-matrix.md) explains detection, data, estimate scope
and limitations per model row. It includes the supported Roborock evidence boundary and a
sanitized partial-session template for mopping and mop washing. README, Diagnostics guidance
and pending issue-reply drafts reference the same intake. No public data URL is claimed.

## Runtime integration receipt

The received schema-v2 bundle has payload SHA-256
`5444b736ceb6e84e5b16b7bc0716dac65211970ba1e68ac9e914f296dd84880e`. The app now
imports its two Xiaomi H50 Pro labelled estimates separately from empirical profiles:

1. `profiles.resolve_consumption_profile`: exact context retains tier, basis, source and
   limits; capacity/family/incomplete basis resolves `unknown`.
2. `tick.tick_device`: a labelled manufacturer estimate remains visible but cannot charge
   usage or a completion counter because the HA action binding is unknown.
3. `sensor_calculations` and the card: tier/limitations stay readable and escaped.
4. `scripts/import_consumption_data.py`: delivered schema validates tier fields, diff shows
   tier/basis changes and rollback remains exact.

The implementation has failing-first coverage for valid and basis-less estimates, exact and
wrong-context selection, no automatic charge, and diagnostics labels. Derived estimates
remain `Unknown` until the dataset provides one that meets the same explicit contract.
