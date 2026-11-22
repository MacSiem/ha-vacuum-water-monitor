# Check your robot's consumption data

The public [Vacuum Consumption Data repository](https://github.com/MacSiem/vacuum-consumption-data)
contains the separate versioned research dataset. For the bundled source snapshot, inspect [model-by-model public-data coverage](consumption-model-coverage.md),
[published action evidence](consumption-evidence.json), and the
[implementation plan](superpowers/plans/2026-09-05-universal-vacuum-consumption.md).

The documented initial research collection has 134 researched models, 23 integration inventory records,
four manufacturer declarations and five partial settings catalogues. None of these declarations
is an approved runtime profile. A positive local test result does not establish real-world
accuracy or worldwide model completeness.

In that repository, look up your exact public model ID, regional SKU,
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

## Model-specific source notes (2026-11-04)

The [versioned research inventory](https://github.com/MacSiem/vacuum-consumption-data/blob/6a15bb320a499d15bec2b8d65913c70098ca809f/data/inventory/research-2026-11-04.json) preserves source links and explicit gaps for the 134 catalogued models. The consumer snapshot contains no approved measured profiles; a model's listed tank capacity is not a consumption rate. Available Home Assistant entities and exact regional SKU equivalence still depend on the installed hardware and integration.

- **Xiaomi H50 Pro:** the manufacturer distinguishes 180 ml for the first mop wash and 120 ml for a mid-task wash. These are source-limited estimates for distinct actions. Final-wash quantity and a verified Home Assistant completion binding remain unknown; neither value becomes a universal per-wash dose.
- **Roborock Qrevo 5AE (`a170`):** the manufacturer describes rotating pads and thirty selected water levels. A published review reports approximately 150–160 ml for a deep wash without instrument resolution or sample count. This is reference information, not an automatically selected measured rate.
- **Roborock Qrevo Curv 2 Flow (`a245`):** a roller system with different operation from the 5AE's rotating pads and the original Qrevo. Identity and reservoir information remain separately scoped; no wash or floor rate is inferred from another model.
- **Roborock Q8 Max+:** one public weighing report states approximately 0.4 g/ft² at high output (approximately 4.3 ml/m² if water density is treated as 1 g/ml). Instrument resolution, sample count and an independent validation run are unknown. It is a reported observation, not an adopted coefficient.
- **Concept VR4050:** the manual gives 130 ml for standard and 215 ml for deep dock programmes. These remain source-limited calibration references; an applicable Home Assistant action binding and separation from transfer are unverified.

After an automatic lid-close or cleared-empty signal, the absolute remaining volume is unknown unless the user has confirmed a full-refill practice or confirms a full tank. A real compatible water-volume sensor remains authoritative. An unobserved partial top-up cannot be detected from an unchanged signal.
