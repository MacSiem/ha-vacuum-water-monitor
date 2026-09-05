# Frozen dataset handoff — 2026-09-05

Owner: Codex dataset session, followed by independent review when a host slot exists.
Exact execution cwd: `/Users/maciej/repos/vacuum-consumption-data`.
Class/profile: `implement` / `hub-eng`; needs_local_models=false. This session must not
run from the application cwd or from an automatically created scratch directory.

Scheduling state: supervisor confirmed no free host slot and prohibited additional tasks
or children. Do not start until a fresh global-slot readback permits a sequential session.
The application session has not edited the dataset repository. Public release remains a
separate `ALLOW_RELEASE=1` turn. The dataset needs its own saved canonical project entry.

Input revision from replacement: dataset `49c90777b289e78cf232be34a8e7ea1abf0bfabc`;
application base `66594c40d05aa5dce7472184a6525640da6bdb75` plus preserved local sprint patch.
The app is the owner of `docs/app-sprint-ledger.json` and `docs/consumption-roadmap.json`.
Return a frozen result and proposed ledger changes; do not edit the app from the data task.

## Required work and acceptance

1. **DATA-02 inventory:** reconcile every one of the 356 public MIoT protocol IDs with
   retail model/SKU, non-mopping, non-retail/unreleased, or unknown; include source/date,
   confidence, owner and next step. Expand manufacturer/region inventory beyond the 134
   records. A released protocol ID is not proof of a marketed mopping model. Test alias
   deduplication without inheriting rates or tank equivalence.
2. **DATA-03 settings/bindings:** retain the 6 pinned Roborock and 3 Ecovacs contracts;
   expand canonical role/domain/unit/enum/firmware contracts with positive and negative
   registry-shaped fixtures. Distinguish absent, unsupported, not applicable and unknown.
   Map actual completion counters/events for wash/tray clean/flush/refill/detergent; a
   command, return-to-dock state or phase disappearance is not completion evidence.
   Preserve all 13 settings and conditional combinations, not a blind Cartesian product.
3. **DATA-04 evidence:** resolve conditions of the 4 H50 Pro/Concept VR4050 action
   quantities, then expand primary sources. Keep declaration, measurement and approved
   profile separate. No rate may be inferred from capacity, marketed area or elapsed time.
4. **CAL-02 + schema v2:** specify whether exposure_domain describes an increment, a
   process, or a complete cycle. App private area-based whole-cycle calibration is not
   legal dataset-v1 `whole_cycle` (currently ml/cycle only); introduce an explicit,
   versioned representation and migration tests before portable import. Fit hybrid only
   with identifiable independent components and sufficient measured data. Area/time for
   the same floor process are alternatives, never additive. Reject rank-deficient data,
   one total refill fitting multiple free coefficients and training/holdout leakage.
5. **APP-02 dependency contract:** model five reservoirs, completed action identity,
   partial/aborted operations, setting segments, transfer edges and external flow for
   plumbed stations. Transfers count once at system level; dirty volume is not inferred
   from clean volume, and detergent mass is not ml without verified conversion. Supply
   frozen synthetic replay fixtures for restart/unavailable/reset/refill/profile change
   and multi-vacuum identities, with hand-derived expected balances and reason codes.
6. **DATA-05/06:** preserve license/provenance checks and explicit contribution review.
   Bundle only eligible records; corruption, rollback, revoked profiles, unsupported
   schema, offline use and compatibility failures must be tested. No publication here.
7. **QA-01:** return numerator AND identified denominator per SKU/firmware/integration/
   setting/action, unknown combinations and unsearched brands/regions. An unknown
   denominator cannot be reported as 100% coverage. Include commit/status, commands and
   results; empirical accuracy needs independent measured cycles/devices.

Return: immutable bundle + SHA-256 + schema revision; source-contract fixtures;
validation/coverage report; remaining criterion dispositions and next owners. Do not
promote synthetic test data or manufacturer declarations just to make the profile count
positive. This handoff does not make the global goal complete.
