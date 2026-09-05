# Dataset V3 integration receipt — 2026-09-05

The application owner read the complete V3 result, protocol, schemas, validator,
source fixture and replay fixture from the read-only dataset repository. The V1
bundle is unchanged: file SHA-256
`20b38e7bd7ad909aaebc12ba717c16706344b287c1d85aa60af631c93ab9a6f2`, payload
SHA-256 `90c8cff505012ffaecf0b00c4913056367c986df4e6d2a8b4ecfc07b64a4e9d7`,
166 records and zero approved profiles.

Frozen V3 inputs used for review:

- RESULT-V3 SHA-256 `d791e747e368f8c2ab33c6e581844359f97eef3b8392b11a502c7f796c932772`;
- protocol SHA-256 `0ce50e620b5bf1d8f6745f451cce39b72228404bcc1661f3f90023c2dfa7cac5`;
- portable import schema SHA-256 `1c0a55488ba99cb974926e61b6c0491d6d667a42e03fc23da7720ae1841e803f`;
- source schema SHA-256 `89ae86209096887126faa2c67cb773f4252c9388efdd86c5df7a7f9cc1d66717`;
- replay schema SHA-256 `2529ed71f28b04ca6ea88fdbcfcb875cf8556c102c3f31c6d29bef3752fd763d`;
- replay fixture SHA-256 `291c5ef2fd0204a04eb7e3579a5d7f3fa17e0e17077fc8de272b2de0df3eee0d`;
- source fixture SHA-256 `5b3ad929613753ae6a13ca3ff1b937799eddc5b696a36c180ac31a921d77e556`;
- validator SHA-256 `f7fef03c678a573a478340b2fabdf1e388bba784b58c76cbb8efbdf1d244dde6`.

The app accepts a portable V2 projection only when it is bound to the exact
verified V1 source payload. V1 profiles remain evidence-only. V2 profiles must
also pass complete record/reference/settings/integration validation, empirical
measurement lineage, disjoint device holdout and validation-metric checks before
an atomic snapshot write. Personal calibration remains independent.

Native physical streams use V3 epoch milliseconds, a measured baseline,
contiguous half-open setting segments, strictly increasing sequence/timestamps,
physical-mL provenance and exact source-contract identity. The app checks a
120-second freshness window and 5-second future-clock allowance. Immutable event
hashes prevent rebilling after restart or accepting a rewritten/truncated log.
Five reservoir balances, partial operations and external supply/drain remain
separate. Unknown, stale or foreign sources hide both diagnostics and the main
tank percentage.

Two code-owned registries gate live use: a full hardware-verified source contract
with nonempty evidence, and an exact entity/contract/device binding. Both are
empty. YAML, entity attributes and the shipped source-only fixture cannot approve
themselves. The six Roborock plus three Ecovacs rows therefore remain capability
documentation, not live bindings.

Remaining blockers are evidence, not safe application implementation: exact
hardware-verified per-model/SKU/firmware bindings; completed action counters or
terminal events; real timestamped physical-mL streams; regional retail/mopping
verification; physical measured cycles; and independent holdout devices. No
synthetic or declared quantity was promoted.
