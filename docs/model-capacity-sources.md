# Model evidence and provenance

The canonical dataset is `custom_components/ha_vacuum_water_monitor/model_profiles.json`.
Its cutoff is 2026-09-05. Each record separates manufacturer/model/SKU identifiers, HA
observations, integration candidates, five reservoir capacities, dated provenance,
confidence and explicit unknowns. See the [complete dated coverage table](coverage-report-2026-09-05.md).

`capacity_verified` means at least one capacity was checked against its primary source.
It does not mean every reservoir, regional SKU, firmware or HA signal is verified.
`researched` means a named model was found in the reviewed source but useful capacity
information remains unknown. Null does not mean absent hardware.

No model supplies ml/m², ml/min or ml/wash. Published floor coverage, suction, tank size,
detergent dilution containers and a waste reservoir cannot establish consumption.
The frontend catalogue is generated from this JSON, including its unknown values.

Issue-confirmed aliases such as a170/a245/1797 are a separate HA observation layer.
A model identifier is manufacturer-scoped; a generic number is not a universal identity.
Regional equivalence is false until evidence explicitly confirms it. Flow/FlowX clean
capacity and H50 Pro dirty capacity remain unknown where source review did not substantiate
an exact default. Earlier docs listing approximate values or cross-model rates are superseded.

To add a profile, identify its exact source/model/region, record the claim and access date,
keep all unknowns explicit, then run the validator, JSON Schema and generator check.
Do not copy a model's rate or reservoir to a similarly named product.

```
python3 scripts/validate_catalog.py
python3 scripts/generate_frontend_catalog.py --check
python3 -m tests
```

For telemetry semantics see [integration contracts](integration-signal-contracts.md).
For measurements see [Diagnostics and calibration](diagnostics-and-calibration.md).
