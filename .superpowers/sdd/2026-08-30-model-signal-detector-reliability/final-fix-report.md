# Final whole-branch fix report

Date: 2026-08-30
Branch: `fix/model-signal-detector-v5.2`
Starting commit: `c11cf0bf5e36aac24735cef47bcf5e10fdb1460e`
Scope: final whole-branch fix for Vacuum Water Monitor v5.2
Remote actions: none

## Status

Implemented all items from `final-fix-brief.md` without push, tag, release, GitHub comment, private-HA deployment, branch switch, or subagent use. Version remains `5.2.0`; Home Assistant floor remains `2024.7.0`; the root and packaged cards are byte-identical.

## Implementation

### Authored configuration provenance and legacy Store migration

- New frontend writes persist raw device fields with `config_provenance.authored_fields`.
- `setConfig`, `devices`, single-device YAML conversion, `_configuredDevicesFromConfig`, and `_addUserDevice` no longer persist a spread of `BRAND_PROFILES`.
- Provenance covers behavior-binding capacity/reservoir fields, nested `signals`, every direct signal role, usage/wash/intensity rates, accounting evidence, and profile-lock fields.
- The card may still decorate a device in memory with legacy profile defaults for an old-backend display fallback, but those values are marked generated and never become authored Store configuration.
- Existing rows without provenance are migrated at read/merge time. Values exactly equal to the selected pre-5.2 card profile or canonical legacy calibration are generated/unlocked. Divergent values are explicit. Nested `signals`, including `{}`, are always explicit because the legacy card never generated that object.
- Generated behavior fields are removed before registry decoration, allowing the backend descriptor to replace stale capacity, profile metadata, and same-device signal roles. Divergent authored values and an authored empty-signals opt-out remain authoritative.
- Exact migration defaults live beside the existing profile resolver in `profiles.py`; no second model resolver was introduced.

### Profile and calibration precedence

- `resolve_profile()` now accepts an already-resolved backend `profile_key` before falling back to legacy `brand_profile` or entity aliases; explicit locked overrides still have the highest precedence.
- Python custom-calibration layers are now exactly `default -> resolved-or-locked profile -> entity`.
- A stale, different, unlocked `brand_profile` can no longer override calibration for a registry-resolved device (regression fixture: resolved a170 with stale S8).
- Frontend descriptor merge and profile selection honor a profile lock only when `profile_locked` is present in authored provenance.

### Generic accounting safety

- The generic record retains its complete `legacy_calibration` for card/catalog compatibility.
- Its backend catalog accounting is empty and `manual_only`.
- Effective generic resolution returns no capacity, no reservoir, no wash rate, and no area rates, so generic/unknown devices cannot consume water without explicit user calibration.

### Runtime initialization and unavailable signals

- Frontend initialization accepts a finite positive legacy `last_reset_ts` in seconds or milliseconds, matching backend parsing, and exposes it as the effective last refill when ISO is absent.
- Missing/unavailable configured status signals persist `status_unavailable`; missing/unavailable configured area signals persist `area_unavailable` even before an area baseline.
- A transient status never clears the wash latch. `status_unavailable` has diagnostic priority over a simultaneous baseline event, preventing a false “ready” card state.
- An unavailable pre-baseline area signal creates a gap; the first subsequent finite sample re-baselines and clears the gap without consuming water.
- Card guidance maps status and area unavailability to the visible “Unavailable signal” state.

### Diagnostics hardening

- `tracked_reservoir` is converted to text before `.replace()`.
- JSDOM hostile diagnostics now cover numeric and object reservoir values and verify that they neither crash nor create raw markup.

## Files changed

- `.github/smoke.cjs`
- `custom_components/ha_vacuum_water_monitor/model_profiles.json`
- `custom_components/ha_vacuum_water_monitor/profiles.py`
- `custom_components/ha_vacuum_water_monitor/sensor_calculations.py`
- `custom_components/ha_vacuum_water_monitor/tick.py`
- `ha-vacuum-water-monitor.js`
- `custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js`
- `tests/test_profiles.py`
- `tests/test_sensor_calculations.py`
- `tests/test_tick.py`
- this report

## Behavior-first TDD evidence

Tests were written before production changes. The first focused run was:

```text
python3 -m unittest tests.test_profiles tests.test_sensor_calculations tests.test_tick -v
node .github/smoke.cjs
```

Observed RED (exit 1), with failures caused by the missing requested behavior:

```text
FAILED (failures=4, errors=1)

generic profile:
AssertionError: 'automatic_estimate' != 'manual_only'

legacy expanded Store:
AssertionError: 'water_total_ml' unexpectedly found

stale calibration layer:
AssertionError: 9.0 != 2

pre-baseline unavailable area:
AssertionError: False is not true

unavailable configured status:
KeyError: 'last_accounting_reason'

smoke: 2 element(s) | PASS 10 | FAIL 2
FAIL ... final-fix-contracts ... -> single-device YAML persisted legacy profile expansion
(same failure for root and packaged card)
```

After the minimal implementation, the focused GREEN run was:

```text
Ran 51 tests in 0.066s
OK
smoke: 2 element(s) | PASS 12 | FAIL 0
card copies: identical
```

## Final pristine verification matrix

The complete matrix was rerun after implementation and self-review. Final command group exited `0`.

### Python suite

Command: `python3 -m tests`

```text
Ran 63 tests in 0.075s
OK
```

### JSDOM runtime smoke

Command: `npm run test:smoke`

```text
smoke: 2 element(s) | PASS 12 | FAIL 0
```

The smoke includes raw single-device YAML persistence/provenance, manual add persistence, legacy timestamp-only initialization, unavailable-signal guidance, numeric/object reservoir diagnostics, no raw hostile markup, registry descriptors, custom calibration, truthful accounting, and both card copies.

### Python compilation

Command: `python3 -m compileall -q custom_components tests`

```text
exit 0; no output
```

### JavaScript syntax

Commands:

```text
node --check ha-vacuum-water-monitor.js
node --check custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js
```

```text
both exit 0; no output
```

### Card byte comparison

Command: `cmp ha-vacuum-water-monitor.js custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js`

```text
exit 0; no output (byte-identical)
```

### JSON and profile catalog

Commands: parse every repository `*.json`; import and validate `profiles.py` catalog.

```text
JSON parse: OK
Catalog validation: OK (34 profiles)
```

### Diff hygiene

Command: `git diff --check`

```text
exit 0; no output
```

### Targeted secret and signing-material scan

The added diff was scanned for common high-confidence API/private-key signatures; changed filenames were scanned for `.p8`, `.p12`, `.pem`, `.key`, `.keystore`, and `.jks`.

```text
Targeted secret scan: OK
Signing-material filename scan: OK
```

### HA/HACS metadata and version

Command: `python3 -m unittest tests.test_frontend_registration -v` plus deterministic metadata readback.

```text
Ran 3 tests in 0.002s
OK
HA/HACS metadata/version: OK (5.2.0, HA floor 2024.7.0, cards identical)
```

Note: the first matrix attempt reached the final auxiliary metadata script after every earlier check passed, but that script incorrectly assumed `manifest.json` contains a `homeassistant` key. The repository correctly declares the HA floor in `hacs.json`. The verifier was corrected to the repository contract and the entire matrix above was rerun from the beginning with exit `0`.

## Migration and provenance reasoning

The safe distinction is value plus provenance, not value alone:

1. New YAML/UI writes carry an authored-field list, so even a value equal to a profile default remains explicitly authored and wins.
2. Old rows have no provenance. Only exact matches to known historical generated defaults are unlocked; a one-value divergence is preserved.
3. `signals: {}` is never inferred as generated, preserving the explicit discovery opt-out.
4. Generated legacy fields are discarded only in the effective merge, not rewritten destructively in Store. Migration is additive/lossless and rollback-safe.
5. Registry descriptor data replaces only generated/unlocked values. Explicit fields remain authoritative.
6. A profile lock is effective only when its lock field is authored; this prevents an old generated `brand_profile` from becoming a stronger calibration layer.

## Self-review

Reviewed the entire fix diff against all eight brief items and the plan global constraints.

- No second profile resolver was added; the migration helper is colocated with and uses the canonical catalog/index.
- No generic rate remains in backend-effective resolution or catalog accounting.
- Explicit YAML, divergent legacy values, and empty signals retain precedence in both Python and JS.
- Registry-resolved a170 defeats stale unlocked S8 calibration; locked override precedence remains intact.
- Missing status/area signals persist an observable reason and do not clear the wash latch.
- Timestamp-only runtime state is initialized without manufacturing initialization from zero/invalid timestamps.
- Hostile reservoir types are string-coerced and escaped.
- Root and packaged cards are mechanically synchronized and byte-identical.
- No version bump, HA-floor change, unrelated documentation change, remote mutation, deployment, or signing/secret material was introduced.

Self-review found and corrected before the final matrix:

- one wrong Unicode icon in exact legacy migration defaults, which would have made that icon look divergent;
- status-unavailable diagnostic priority, which otherwise could have been overwritten by area-baseline initialization;
- raw generic catalog metadata, aligning it with effective `manual_only`/no-rate behavior;
- derived single-device display name was removed from configured-device persistence so the Store row remains raw authored config plus provenance.

## Concerns

- No known correctness blockers.
- Legacy classification is intentionally conservative: only exact historical defaults are unlocked. Unrecognized or divergent legacy values remain explicit, which may retain stale user data rather than risk overwriting a genuine customization.
- No private HA deployment/live registry test was performed because the brief explicitly prohibited it; coverage is unit/JSDOM/metadata based.

## Closeout state

```yaml
persistent_closeout:
  obsidian: "not_required_with_reason: task restricted work to this repo and required this repo-local report"
  notion: "not_required_with_reason: no external writes authorized"
  live_artifact: "not_required_with_reason: no dashboard requested"
  status_artifact: "updated: .superpowers/sdd/2026-08-30-model-signal-detector-reliability/final-fix-report.md"
  telegram: "not_required_with_reason: worker return is to the active orchestrator; no external communication authorized"
  communication_trace: "not_required_with_reason: no Telegram call made"
  hardware_state: "AMBER: internal free 31 GB, SSD free 80 GB; zero swap/pageout pressure and activity GREEN"
  source_levels: "local_readback"
  evidence:
    - "final full matrix exit 0"
    - "63 Python tests; JSDOM PASS 12 FAIL 0"
    - "card byte comparison exit 0"
```
