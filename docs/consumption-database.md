# Check your robot's consumption data

Vacuum Consumption Data is being prepared as a separate open GitHub data source, intended
name `MacSiem/vacuum-consumption-data`. It exists locally but is not public yet. Until
publication, inspect [model-by-model public-data coverage](consumption-model-coverage.md),
[published action evidence](consumption-evidence.json), and the
[implementation plan](superpowers/plans/2026-09-05-universal-vacuum-consumption.md).

The separate dataset currently has 134 researched models, 23 integration inventory records,
four manufacturer declarations and five partial settings catalogues. None of these declarations
is an approved runtime profile. A positive local test result does not establish real-world
accuracy or worldwide model completeness.

When the public repository is available, look up your exact public model ID, regional SKU,
dock, firmware and integration version in its coverage report. Inspect the per-setting
sources, missing signals and empirical validation. Unknown means the evidence is incomplete.

## What to contribute

- Missing model/SKU or an incorrect identity/capacity, with a primary source.
- All exposed cleaning modes, routes, water levels, wash modes/intervals/temperatures and
  their allowed/forbidden combinations, with canonical API enum meanings if available.
- Consented measurements for a particular combination, including mopping-only versus
  simultaneous or sequential vacuuming/mopping, actual mopping area, active time and washes.
- A correction to published consumption data or evidence that a firmware change invalidates it.

One useful sample is welcome; it does not need to cover every mode. A shared profile needs
independent cycles and devices. Your private calibration stays separate from community data.
See [LLM-assisted contribution guidance](llm-assisted-contribution.md). An LLM-generated
coefficient is a proposal, not a measurement.

## Developer import

The application imports an offline bundle with `scripts/import_consumption_data.py`.
Pass `--data-repo` pointing to a **trusted local checkout** and `--bundle` pointing to the
built JSON package. The script executes that checkout's validator locally, verifies the
manifest and writes the snapshot atomically. `--check` compares without changing files.
This is a developer tool; it does not download or execute database code inside Home Assistant.
The current snapshot contains zero approved profiles. The [runtime resolver and private calibration](runtime-consumption-contract.md) now implement
strict context selection and tested local accounting paths. Complete source-backed signal
bindings and real approved profiles remain open; the empty snapshot enables no model rates.
