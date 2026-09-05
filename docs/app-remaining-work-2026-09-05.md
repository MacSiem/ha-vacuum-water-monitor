# Vacuum Water Monitor — per-action continuation audit V4

Date: 2026-09-05
Canonical app repo: `/Users/maciej/repos/ha-vacuum-water-monitor`
Branch: `main` at `66594c4` with the pre-existing dirty sprint patch preserved.
Class/profile: `implement` / `hub-eng`; zero children; no production HA, release, push or dataset-repo mutation.

## Completed in this continuation

- **DATA-06 importer review and rollback:** the offline importer now emits a deterministic diff for added/removed profiles and changed method, coefficient, unit and evidence lineage. A failed post-write readback restores the exact previous bytes. Corrupt, incompatible, unproven and revoked inputs remain fail closed.
- **CAL-02 identifiability contract:** `check_identifiability` checks area, time, action and three-component hybrid exposure matrices before fitting. It returns rank and reason only. Synthetic tests reject a single combined total, collinear hybrid exposures, booleans, non-finite values and incomplete designs; no synthetic rate becomes a profile.

Fresh evidence: 272 Python tests PASS; smoke 12/12; sprint UI, catalog validation, frontend parity, compileall, JavaScript syntax and `git diff --check` PASS. Ledger gate PASS with 1023 explicit unresolved dispositions. Coverage gate intentionally exits 2 with `goal_complete=false` for 133 dated model records.

## Remaining work dispositions

| Action | Status | Evidence | Resume when |
|---|---|---|---|
| DATA-06 app importer diff and exact rollback | complete | `scripts/import_consumption_data.py`; `tests/test_consumption_import.py`; full checks PASS | Reopen only for a versioned importer contract change. |
| CAL-02 pre-fit identifiability gate | complete | `calibration.py`; `tests/test_local_measurements.py`; full checks PASS | Reopen when adding a measured fitter with a different design. |
| Hardware source registry | blocked | `SOURCE_CONTRACTS` and `SOURCE_BINDINGS` are empty; source-only V3 candidates have no hardware verification. | A frozen hardware-verified source contract and exact same-device HA entity binding are returned. |
| Standalone wash/tray completion | blocked | No verified monotonic completion counter or terminal event exists for the five source-only candidates; state changes alone cannot prove completed physical actions. | A frozen fixture from real hardware proves completion identity and reservoir edges. |
| Approved shared consumption profiles and accuracy | blocked | Frozen dataset contains zero approved profiles; synthetic tests and estimates are ineligible. | Independent physical train/holdout cycles across the required devices and contexts pass empirical gates. |
| Retail SKU, mode and integration coverage | blocked | The dated app catalog has 133 records and the protocol index has 356 identifiers, but neither is a verified worldwide retail SKU/action matrix. | The canonical dataset owner returns a frozen audited retail mapping and complete setting/action applicability records. |
| App activation of automatic physical accounting | blocked | Fail-closed runtime has no trusted live source or approved rate to activate. | Either the verified source/binding stream or applicable approved measured profiles are imported and pass app replay tests. |
| Publication/release | blocked | No `ALLOW_RELEASE=1` turn exists; version 5.4.0 and production remain untouched. | Maciej starts a separate release turn with `ALLOW_RELEASE=1` after acceptance evidence exists. |

No remaining action in this app repo and `implement` class is ready. Public data research was handed to the coordinator for a separate canonical session in `/Users/maciej/repos/vacuum-consumption-data`, using the frozen dataset handoff and V3 hashes. The global goal remains in progress.
