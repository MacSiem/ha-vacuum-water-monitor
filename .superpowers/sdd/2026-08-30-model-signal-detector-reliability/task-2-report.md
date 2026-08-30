# Task 2 — Safe accounting, initialization, and calibration migration

## Implementation

- Removed generic wash and area-consumption fallbacks from `tick.py`. Accounting now consumes only an explicit user calibration or a resolved profile rate; missing rates persist a diagnostic skip reason and never add water.
- Kept wash accounting entry-based: only a transition from outside the verified wash-state set consumes. In-sequence status changes and an integration start while washing are recorded without a second charge.
- Hardened area accounting: finite values only; a 0.1 m² lower bound; cleaning/mop checks; an explicit mapping-only `default` fallback; configurable `area_anomaly_ceiling_m2` (25 m² conservative default); and safe rebaselining for decreases, unavailable gaps, and anomalous jumps.
- Added additive calibration merging. Default/profile/entity layers merge mappings; entity calibration overrides profile-derived descriptor rates, capacity, wash volume, and accounting evidence while explicit device/YAML values remain authoritative. Supports `tracked_capacity_ml`/`tank_ml`, `usage_ml_per_m2`/`water_per_m2`, and `wash_volume_ml`/`mop_wash_ml`. Legacy `robot_tank_ml` remains `legacy_robot_tank_ml` metadata only.
- Added initialization semantics. A state remains unknown until a refill; a valid legacy refill timestamp keeps it initialized. Manual and detected refills set `initialized`, zero used water, and preserve historic fields.
- Added persisted accounting diagnostics and exposed initialization, reason, capability, profile-resolution fields, evidence, source, rate, and reason through the water sensors.

## Files

- `custom_components/ha_vacuum_water_monitor/tick.py`
- `custom_components/ha_vacuum_water_monitor/sensor_calculations.py`
- `custom_components/ha_vacuum_water_monitor/sensor.py`
- `custom_components/ha_vacuum_water_monitor/storage.py`
- `tests/test_tick.py`
- `tests/test_sensor_calculations.py`
- `tests/test_user_device_removal.py`

## RED evidence

1. `python3 -m unittest tests.test_tick tests.test_sensor_calculations -v`
   - 30 tests ran: 4 failures and 4 errors.
   - Expected failures demonstrated generic consumption without rates (160 instead of 10 for wash; 22 instead of 10 for area), missing accounting metadata, no initialization state, and non-additive calibration.
2. `python3 -m unittest tests.test_user_device_removal.UserDeviceRemovalTest.test_refill_reset_initializes_a_legacy_tank_record -v`
   - Failed as expected: manual reset returned `initialized == False`.
3. `python3 -m unittest tests.test_sensor_calculations.VacuumSensorCalculationTests.test_entity_calibration_overrides_profile_rates_discovered_for_that_entity -v`
   - Failed as expected: discovery-derived profile rate `6.0` overrode entity calibration `7.5`.
4. The same focused test then failed as expected for evidence: `maintainer_estimate` remained instead of `user_calibration`.
5. `test_explicit_yaml_rate_keeps_precedence_even_when_it_matches_profile` failed as expected: entity calibration replaced a YAML rate merely because its mapping matched the profile. Provenance tracking now keeps direct settings authoritative.

## GREEN and verification evidence

- `python3 -m py_compile custom_components/ha_vacuum_water_monitor/tick.py custom_components/ha_vacuum_water_monitor/sensor_calculations.py custom_components/ha_vacuum_water_monitor/sensor.py custom_components/ha_vacuum_water_monitor/storage.py` — exit 0.
- `python3 -m unittest tests.test_tick tests.test_sensor_calculations tests.test_user_device_removal -v` — 36 tests passed.
- `python3 -m unittest discover -s tests -v` — 50 tests passed.
- `git diff --check` — exit 0.
- `python3 -m json.tool custom_components/ha_vacuum_water_monitor/model_profiles.json >/dev/null` — exit 0.
- `ruff check custom_components/ha_vacuum_water_monitor tests` was not run because `ruff` is unavailable in this checkout.

## Self-review

- No generic water-rate fallback remains in the server tick; unknown and manual-only profiles therefore cannot create water use without a user-supplied rate.
- The effective profile resolver is reused rather than recreated. Discovery-provided profile values are recognized as inherited so entity calibration can override them; explicit non-profile device values retain precedence.
- Old tank records remain valid: their existing timestamp initializes them, and newly added state keys are additive defaults. `robot_tank_ml` never becomes a clean-water capacity.
- DIY helper suppression remains unchanged.

## Concerns

- The 25 m² anomaly ceiling is intentionally conservative but is a per-tick default; installations with large reporting intervals or unusually large homes may need `area_anomaly_ceiling_m2` configured explicitly.
- `ruff` is not installed in the current environment, so lint verification is limited to compilation, test suite, JSON parsing, and diff checks.

## Review fix round 1

### Fixes

- Normalized calibration aliases inside each default/profile/entity layer before precedence merging. Thus an entity `water_per_m2`/`mop_wash_ml`/`tank_ml` record correctly overrides canonical keys from a lower-precedence layer.
- Added persisted `wash_sequence_active` state. Transient status values (`unknown`, `unavailable`, empty, or missing) retain an active wash sequence; only a verified non-wash status closes it. Existing records whose last status is a wash state are also protected even if their new latch field is false/defaulted.
- Made the inclusive 0.1 m² threshold robust to ordinary binary floating-point representation with a narrowly bounded absolute tolerance.
- Made `tick_device` operate on a shallow state copy and return that new object, leaving its caller-owned input untouched.

### RED evidence

`python3 -m unittest tests.test_sensor_calculations.VacuumSensorCalculationTests.test_entity_alias_calibration_overrides_canonical_default_layer tests.test_tick.WaterAccountingTransitionTests.test_transient_status_does_not_end_persisted_wash_sequence tests.test_tick.WaterAccountingTransitionTests.test_literal_tenth_square_meter_doses_but_smaller_delta_does_not tests.test_tick.WaterAccountingTransitionTests.test_tick_device_returns_new_state_without_mutating_caller_state -v`

- 4 tests failed as expected before implementation: entity alias calibration yielded 4 instead of 9; transient wash sequence recharged; literal 10.0→10.1 did not dose; and the returned state was the same mutated object.
- `test_legacy_wash_status_without_latch_does_not_charge_after_restart` then failed as expected before the compatibility adjustment: it charged 300 instead of retaining 150.
- `test_missing_configured_status_signal_keeps_wash_latch_active` then failed as expected: a missing configured raw-status entity incorrectly used the vacuum fallback state and cleared the latch.

### GREEN and verification evidence

- `python3 -m py_compile custom_components/ha_vacuum_water_monitor/tick.py custom_components/ha_vacuum_water_monitor/sensor_calculations.py custom_components/ha_vacuum_water_monitor/storage.py` — exit 0.
- `python3 -m unittest tests.test_tick tests.test_sensor_calculations tests.test_user_device_removal -v` — 42 tests passed.
- `python3 -m unittest discover -s tests -v` — 56 tests passed.
- `git diff --check`, full `py_compile`, and `python3 -m json.tool custom_components/ha_vacuum_water_monitor/model_profiles.json >/dev/null` — exit 0.

### Self-review

- The latch is per persisted device state and falls back to the legacy last status, so neither restarts nor transient observations create a second wash charge.
- Alias canonicalization occurs before layers are combined; no lower-layer canonical key can mask a more-specific legacy alias.
- No frontend files were changed; the reviewer’s zero/100 observation remains reserved for Task 3.
