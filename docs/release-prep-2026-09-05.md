# Vacuum Water Monitor v5.5.0 — release preparation

This is a local release-preparation record. It does not publish, push, tag or create a
GitHub release.

## Verdict

The app has a coherent **v5.5.0 candidate** ready for a local freeze and public-release
review. Unknown values remain unknown, a real same-reservoir volume sensor wins, gaps and
context changes rebaseline, and private calibration stays local. The imported dataset v0.2.0
adds two Xiaomi H50 Pro manufacturer-declared, display-only estimates: 180 ml for an
explicitly identified first-time mop wash and 120 ml for an explicitly identified mid-task
mop wash. They retain their basis and limitations, and never charge automatic accounting or
a completion counter because the Home Assistant action binding is unknown.

Public-release conditions:

1. `ALLOW_RELEASE=1` is absent, so push, tag, GitHub release and HACS publication are
   prohibited.
2. The published dataset is verified before its links are used in README or issue replies.

The exact local candidate is frozen by the release receipt. The data repository is now
published at [MacSiem/vacuum-consumption-data](https://github.com/MacSiem/vacuum-consumption-data),
with its [contribution guide](https://github.com/MacSiem/vacuum-consumption-data/blob/main/CONTRIBUTING.md)
and [v0.2.0 release](https://github.com/MacSiem/vacuum-consumption-data/releases/tag/v0.2.0).
This authorized release turn will push the final documentation commit, create/tag v5.5.0,
confirm HACS metadata/distribution, then post issue replies with verified URLs.

## Candidate scope

- Evidence-gated catalog and exact-context resolver; no approved shared consumption profile.
- Dataset v0.2.0 importer and H50 Pro manufacturer-data labels; estimates stay display-only
  until a trusted completion binding is supplied.
- Five-reservoir accounting, source/binding fail-closed behavior, event identity and
  bounded automatic history.
- Private measured calibration and a pre-fit identifiability gate; no synthetic profile
  promotion.
- Reprofile action preserving authored settings, calibration and history.
- Import diff/rollback and sanitized Diagnostics intake.
- README no longer claims an unconfigured area-to-time fallback.

Version surfaces are aligned to `5.5.0`: integration manifest, Python cache-bust
constant, both bundled card copies, package metadata and lockfile. The data repository
is published and linked from the README.

## GitHub issue readback and reply drafts

These are drafts only. Do not post them before the v5.5.0 release exists. Replace the two
placeholders with verified public URLs during the authorized release turn.

### #10 — Tapo RV50 Pro

Latest reporter message is a thank-you and promise to report back. There is no unanswered
question. Keep the issue open for their real-device result; do not add a redundant reply.

### #11 — Xiaomi H50 Pri

The latest report says the `vacuum` entity disappeared after Home Assistant 2026.9.0 while
other Xiaomi MIoT entities remain. This blocks app discovery before Water Monitor can
diagnose accounting.

> Thank you for the update. If the `vacuum.*` entity is no longer present, Vacuum Water
> Monitor cannot discover or bind the robot, so this is first an upstream Xiaomi MIoT / Home
> Assistant entity-availability problem rather than a water-accounting result. Please restore
> the vacuum entity or report that regression to the Xiaomi MIoT integration first.
>
> Once it is back, please update to [v5.5.0](RELEASE_URL), use **Refresh detected profile**
> in the card, and share the compact sanitized intake from [the contribution guide](DATASET_URL).
> Include integration version, model/SKU and region, firmware, tracked reservoir, entity
> domain plus canonical property/translation key, and only the relevant sanitized attributes
> and state transitions. Partial session fields (area, duration, completed washes and water
> used) are welcome when available; label each number Measured, Manufacturer data, Derived
> estimate or Unknown. Please remove tokens, account IDs, serials, MAC/IP addresses, unique
> IDs, room names, maps and absolute timestamps.

### #12 — Roborock Qrevo Curv 2 Flow X

The latest reporter asks whether History records automatic cleaning sessions. The candidate
adds bounded automatic session history, but a session is kept only when the accounting path
has continuous, attributable evidence; incomplete/unknown sessions are not fabricated.

> Thank you — automatic session history is included in [v5.5.0](RELEASE_URL). It records
> completed automatic cycles when the accounting evidence is continuous and attributable;
> incomplete or unknown cycles are intentionally not converted into a misleading numeric
> history entry. After updating, please run one complete mop cycle and check **History**.
>
> If it is still missing, please share the compact sanitized intake from
> [the contribution guide](DATASET_URL): integration version, model/SKU and region,
> firmware, tracked reservoir, entity domain plus canonical property/translation key, and
> relevant sanitized attributes/state transitions. Partial session fields are welcome; label
> each number Measured, Manufacturer data, Derived estimate or Unknown. Do not include raw
> Diagnostics, tokens, account IDs, serials, MAC/IP addresses, unique IDs, room names, maps
> or absolute timestamps.

### #13 — re-profiling single action

The issue has no maintainer response. The candidate supplies a one-action **Refresh detected
profile** workflow that releases generated locks and preserves user-authored settings,
calibration and history.

> Thanks for the feature request. [v5.5.0](RELEASE_URL) adds **Refresh detected profile**
> under Maintenance → Custom calibration. It refreshes generated discovery without requiring
> delete and re-add, while preserving your authored capacities, signal assignments,
> calibration and history. Please update, try it once, and report any unexpected result using
> the compact sanitized intake in [the contribution guide](DATASET_URL). Do not post raw
> Diagnostics or private identifiers.

## Read-only source evidence

- App repository: public `MacSiem/ha-vacuum-water-monitor`; latest published release
  `v5.4.0` on 2026-09-02; no open PRs; latest HACS validation and hassfest runs passed.
- Dataset local repo: no git remote. `gh repo view MacSiem/vacuum-consumption-data` returns
  NOTFOUND.
- Frozen dataset payload SHA-256:
  `5444b736ceb6e84e5b16b7bc0716dac65211970ba1e68ac9e914f296dd84880e`.
- V4 app receipt SHA-256:
  `abfed0d6f60a4a87e5f7af681a7993594a7f450ca39b23112b8357c52c439be3`.
- Public research V2 receipt SHA-256:
  `f6e217103785d9a30244590ddc0ad068b25bd402ab07800a169bc006ac7c462f`.
  It covers all 356 unresolved records in 43 groups, still with zero approved profiles and
  no exact retail/protocol crosswalk claim.
