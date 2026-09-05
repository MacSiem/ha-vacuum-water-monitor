# Dataset v2 semantic followup — 2026-09-05

Application owner read the full result, portable protocol, receipt, both schemas,
source/replay fixtures and tools/contracts_v2.py. Verified actual dist bundle file
SHA256 `20b38e7bd7ad909aaebc12ba717c16706344b287c1d85aa60af631c93ab9a6f2`
and canonical payload SHA256
`90c8cff505012ffaecf0b00c4913056367c986df4e6d2a8b4ecfc07b64a4e9d7`.
The bundle is v1 with 166 evidence records and zero approved profiles. No accuracy
or complete coverage follows from 356 dispositions or 39 reported dataset tests.
Dataset repo has remained read-only in this application session.

## Required corrections for dataset owner

1. `validate_import` accepts a profile containing only kind/review/confidence,
   evidence_class and accounting_contract. Require the full versioned profile,
   measurement, reference, settings and integration validation. Test missing
   id/context/coefficient/units/evidence, fabricated metrics, repeated cycles,
   training/holdout device overlap, malformed record collections and bool schemas.
   The application retains the trusted v1 record validator on a v2 projection,
   plus its own strict v2 eligibility gate before atomic write.
2. `validate_replay` permits completed=true and aborted=true if evidence is a
   counter/terminal event. It permits a negative intermediate tank if a later
   refill repairs the final value. Add negative, nonfinite, boolean quantity,
   self-edge and detergent-conversion regressions. Do not use expected_final as
   the only validity check. Application regressions now reject these cases.
3. Frozen replay events have no timestamp, sequence, segment assignment, quantity
   provenance or source binding. Preserve the fixture as synthetic-only. Supply
   a versioned live envelope and migration fixtures; define restart/epoch,
   reconciliation/reset, partial operations, retention and cross-integration
   action identity. A command with physical partial transfer may change a measured
   balance; it must not increment completed actions or apply a completed dose.
4. Bind each source to installation/vacuum, model/SKU/firmware/integration version,
   domain/key/unit, and documented counter or terminal identity. The current
   source fixture contains nine rows, but is not the original six Roborock plus
   three Ecovacs verified setting contracts (for example route is absent).
   Reconcile identities rather than replace earlier contracts by row count.
   Its global absent/not_applicable labels are not per-device evidence.
5. The protocol says v2 profiles but the bundle builder and record schemas remain
   v1. Publish a complete v2 envelope/profile schema and deterministic migration
   before calling the portable contract complete. The application accepts v1
   evidence, never promotes a v1 profile, and imports no new real rates.

## Implemented app boundary to review against proposed dataset schema

`accounting_v2.py` replays frozen synthetic transfers and separately consumes an
app-defined physical event-stream envelope. This extension is not claimed to be
already standardized by dataset v2. Registry `SOURCE_CONTRACTS` is empty; neither
entity attributes nor user configuration can approve a source contract.

The envelope includes schema_version=2, fixture_class=physical_event_stream,
source_contract_id, device_identity, exact context, baseline_id/baseline_at_ms,
observed_at_ms, complete_since_baseline, initial_reservoirs, setting_segments and
events. Segments use seconds from baseline. Each event wrapper includes contiguous
sequence, timestamp_ms, settings_id, quantity_evidence=physical_ml and the frozen
core event. Streams must be fresh within 120 seconds; no future timestamps.

A complete immutable log replays from its measured baseline. Duplicate delivery
is idempotent; rewrite/truncation/foreign identity is rejected. An unavailable
source hides balances but retains the private journal. Returning to the same
setting creates a distinct segment. Event history caps at 2000 and fails closed;
no eviction can permit duplicate billing. New baseline/source reconciliation is
currently rejected pending a standardized source contract, not guessed from the
manual refill button. Internal transfers are not counted as external consumption;
external supply/drain are shown separately with no invented tank percentage.

Next owner: dataset session via coordinator. Return frozen source contracts,
schema, fixtures and receipt to this app ledger. Real SKU coverage, physical
measurements and independent accuracy remain separately open acceptance criteria.
