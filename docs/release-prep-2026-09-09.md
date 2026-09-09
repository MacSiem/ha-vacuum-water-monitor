# Release dossier — 5.6.0 candidate (2026-09-09)

Supersedes `docs/release-prep-2026-09-05.md`, which describes the 5.5.0 candidate
and was written before that release was published.

## Baseline

| Item | Value |
|---|---|
| Repository | `MacSiem/ha-vacuum-water-monitor`, branch `main` |
| Baseline commit | `6ae70541dcff30b3cdb754362fc37ca345d0b8f8` (v5.5.0, released 2026-09-05T19:42Z) |
| Candidate version | `5.6.0` |
| Candidate commit | not yet created — working tree, frozen for review |
| Untracked, deliberately preserved | `.playwright-cli/` (unrelated, left out of the patch) |
| Data repository | `MacSiem/vacuum-consumption-data`, public, `main` @ `f73bd20f4db990e689943b9ed7a7fee48d1663c6`, clean |

## What this release fixes

### 1. Registry manufacturer forms no longer discard an exact model match

5.5.0 introduced a catalogue filter comparing the Home Assistant device-registry
`manufacturer` for whole-string equality. There was no such filter in 5.4.0.
Home Assistant reports vendor-formatted values, so any form other than the bare
brand narrowed the catalogue to nothing, and the subsequent `model_id` lookup had
nothing left to match. The vacuum then reported as unrecognised even though its
model was present in the 133-record catalogue.

Reproduced against the real resolver:

| Device | 5.5.0 | 5.6.0 |
|---|---|---|
| `roborock.vacuum.a245` + `Roborock` | resolved | resolved |
| `roborock.vacuum.a245` + `Beijing Roborock Technology Co., Ltd.` | **unresolved** | resolved |
| Matter `1797` + `TP-Link` | resolved | resolved |
| Matter `1797` + `TP-Link Corporation Limited` | **unresolved** | resolved |
| Matter `1797` + `Unrelated manufacturer` | unresolved | unresolved (intended) |

A known manufacturer is now matched on token boundaries. A stated but unknown
manufacturer still scopes the catalogue, so a Matter product id that is not
unique across vendors cannot match another brand. That property is enforced by
the pre-existing `test_matter_product_id_is_not_global_across_manufacturers`,
which was allowed to keep passing throughout.

Relates to the reports in issues #12 (Qrevo Curv 2 Flow X, and Qrevo 5AE in a
comment) and #10 (Tapo RV50 Pro Omni, Matter).

### 2. The shipped consumption snapshot is reproducible

5.5.0 shipped `consumption_snapshot.json` with
`source_revision: 49c90777b289e78cf232be34a8e7ea1abf0bfabc-dirty` — compiled from
an uncommitted working tree of the data repository. Nobody, including us, could
rebuild that artefact. Provenance is this product's central claim, so this is a
release-integrity defect even though the record content was unchanged.

The snapshot is now compiled from the committed data-repository revision:

```
source_revision       f73bd20f4db990e689943b9ed7a7fee48d1663c6
source_payload_sha256 d6daec2b462c52ab8cdd34a366940ef73a50b66fe85f460db51a20b7ce0580fd
schema_version        2
dataset_version       0.2.0
profiles              0
estimates             2
```

Reproduction (`dist/` is gitignored in the data repository, so the bundle is
rebuilt rather than fetched):

```bash
cd vacuum-consumption-data && git checkout f73bd20
.venv/bin/python -m tools.validate        # {"validation":"PASS","records":168,"approved_profiles":0}
.venv/bin/python -m tools.build_bundle    # payload_sha256 d6daec2b...
cd ../ha-vacuum-water-monitor
python3 scripts/import_consumption_data.py \
  --data-repo ../vacuum-consumption-data \
  --bundle ../vacuum-consumption-data/dist/consumption-data.json --check
```

### 3. Documentation that no longer matched reality

- `docs/consumption-roadmap.json` still declared
  `repository_state: local_git_created_not_public` and `local_revision: 49c9077`
  while the repository had been public for several releases and `HEAD` was
  `6ae7054`.
- `CHANGELOG.md` still headed the 5.5.0 content as *Unreleased* and ended it with
  "No production deployment or release", which stopped being true on 2026-09-05.

### 4. New release gates

- A snapshot whose `source_revision` is not a full commit sha now fails the suite.
- The bundled card under `custom_components/.../www/` must be byte-identical to
  the repository card, so a stale copy cannot ship.

## Evidence

All commands run on the frozen tree, 2026-09-09.

| Gate | Result |
|---|---|
| `python3 -m tests` | **286 passed**, exit 0 (280 at baseline, +6 new) |
| `npm run test:smoke` | **PASS 12 / FAIL 0**, exit 0 |
| `node .github/sprint.cjs` | PASS, both card copies, exit 0 |
| `python3 scripts/validate_catalog.py` | `catalog valid: 133 profiles; no shipped consumption rates`, exit 0 |
| `python3 scripts/generate_frontend_catalog.py --check` | `Frontend catalog parity PASS`, exit 0 |
| `git diff --check` | clean, exit 0 |
| Secret scan over the diff | no key, token, credential, address or e-mail introduced |
| Version surfaces | `manifest.json`, `const.py`, `package.json`, both card banners all `5.6.0` |
| Card copy parity | both `43c175800058194cebde7568ff2186c4b74253552e35b0c790aa518865e84337` |
| `scripts/check_consumption_coverage.py --require-complete` | **exit 2 by design**, `goal_complete: false`, 1023 unresolved criteria, 133 models |

### Negative test (the fix is load-bearing)

The three new profile tests were run against the unmodified 5.5.0 `profiles.py`:
`FAILED (failures=2, errors=1)`, failing precisely on
`Beijing Roborock Technology Co., Ltd.` + `roborock.vacuum.a245` and on
`TP-Link Corporation Limited` + `1797`. They pass on the fixed tree.

## Known limitations, unchanged and deliberate

- **Zero approved consumption profiles.** `data/consumption_profiles/` in the data
  repository is empty. The dataset carries 4 observations and 2 manufacturer
  declarations (Xiaomi H50 Pro: 180 ml first mop wash, 120 ml mid-task wash),
  shipped **display-only**. No `ml/m²`, `ml/min` or `ml/wash` is shipped for any
  model. A model without a measured rate reports `unknown` with a reason.
- **Coverage is not complete and must not be described as complete.** 1023
  unresolved criteria across 133 models; "all" means the dated catalogue, never
  100% of the market.
- **`xiaomi.vacuum.h50pro` does not resolve.** The catalogue holds
  `xiaomi_h50_pro` under its retail identifiers only. No MIoT model id for the
  H50/H50 Pro appears in the 354 vacuum ids of the local MIoT research, so no
  identifier was added — inventing one is exactly the failure mode this product
  forbids. Needs the reporter's exact Model ID.
- **Issue #11 is upstream.** The reporter's `vacuum.*` entity disappeared after
  Home Assistant 2026.9.0 in Xiaomi MIoT. No local profile can bind an entity
  that does not exist.
- No physical measurement was taken in this session, so predicted-vs-observed
  accuracy is still unproven.

## Blocker map

| Branch | State | Resume condition |
|---|---|---|
| Code, tests, local gates | **complete** | — |
| Documentation, changelog, dossier | **complete** | — |
| Commit / push / tag / GitHub release | **blocked** | separate turn with `ALLOW_RELEASE=1` and Maciej's approval |
| hassfest + HACS Validation | **blocked** | both run as GitHub Actions; they need the push above |
| Live Home Assistant deploy, cache-bust, restart | **blocked** | production HA is read-only/shadow by standing rule; deploy is permitted only inside an authorised release turn, with a backup and a shown rollback plan |
| Visual QA screenshots on live HA | **blocked** | depends on the deploy above; only sanitized demo/fixture captures are permitted |
| Replies to issues #10, #12, #13 | **blocked** | must carry the verified release URL, so they follow publication |
| Accuracy validation | **blocked** | needs one physical refill measurement after a normal full-tank mop cycle |

## Parallel work completed while blocked

Regression reproduction and fix, three new profile regression tests plus a proven
negative run, two new release-integrity gates, snapshot re-import from a committed
revision, roadmap and changelog corrections, version bump across all five
surfaces, full local gate run, secret scan, and this dossier.

## Rollback

Nothing has been published, so rollback is local.

```bash
cd /Users/maciej/repos/ha-vacuum-water-monitor
git checkout -- CHANGELOG.md docs/consumption-roadmap.json package.json \
  ha-vacuum-water-monitor.js custom_components tests
# .playwright-cli/ is untracked and unaffected
```

After publication, rollback is to re-point HACS at the previous tag `v5.5.0`
(`6ae7054`) and delete the `v5.6.0` release and tag. The 5.5.0 artefacts are
unchanged by this work.

## Next steps

1. Maciej reviews this dossier and the diff.
2. Separate turn with `ALLOW_RELEASE=1`: commit, push, confirm the four workflows
   (tests, validate, hassfest, HACS Validation) are green on the exact SHA, tag
   `v5.6.0`, publish the release.
3. Read GitHub back, then reply to #12 (regression fixed, plus the Qrevo 5AE
   comment), #10 (Matter manufacturer form), and #13 if anything changed. #11
   stays upstream-owned.
4. Optional, separately authorised: deploy to live Home Assistant with a backup
   and rollback plan, cache-bust, and capture sanitized screenshots.
