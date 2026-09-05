# Consumption research — 2026-09-05

The user goal remains automatic correct consumption across all existing mopping models, integrations, settings and actions. **Not complete.** The 133 runtime profiles are a partial inventory. Capacity coverage and passing local tests do not establish consumption coverage.

| Model | Published action | Quantity | Remaining applicability gaps |
|---|---|---:|---|
| Xiaomi H50 Pro | First-time mop cleaning | 180 ml | Meaning of first-time, wash setting, firmware, HA action binding |
| Xiaomi H50 Pro | Mid-task mop cleaning | 120 ml | Wash setting, concurrent refill scope, firmware, HA action binding |
| Concept VR4050 | Standard fabric cleaning | 130 ml | HA integration/setting binding, concurrent refill scope, firmware |
| Concept VR4050 | Deep fabric cleaning | 215 ml | HA integration/setting binding, concurrent refill scope, firmware |

Sources: [Xiaomi manufacturer FAQ Q61–62](https://www.mi.com/global/support/faq/details/KA-673648/) and [Concept manufacturer manual, PDF page 51 / printed 100–101](https://www.my-concept.sk/img.asp?attid=56409021). Concept lists 91/145 seconds respectively, three floor-water levels and 10/15/20-minute return intervals. Those durations are wash-program durations, not pump runtime. Neither source provides a complete validated per-setting consumption model. Action observations are preserved separately in `consumption-evidence.json`; not promoted to an unconditional `wash_volume_ml`.

[Roborock support](https://support.roborock.com/hc/en-us/articles/31037465640089-How-many-washing-modes-are-there-and-what-s-the-difference-between-them) says Smart wash changes water and duration with dirt. This requires observing the changing inputs or learning an uncertainty range; one constant per mode cannot establish exact use. [S7 MaxV Ultra support](https://support.roborock.com/hc/en-us/articles/6568621037081-How-often-do-I-need-to-refill-Clean-Water-Tank-of-S7-MaxV-Ultra) gives a whole-home scenario, not a measured ml/m² coefficient.

## Public MIoT inventory

`miot-signal-inventory.json` extracts the latest **released** spec per model at the cutoff from the [public API](https://miot-spec.org/miot-spec-v2/instances?status=all): 356 model IDs. These are protocol declarations, not verified retail products, mopping capabilities, active firmware features or HA entities. Marketing names remain unknown. SIID/PIID, enum settings, actions, source URLs and source hashes are retained.

All declared property units were audited: none uses ml/L. This does **not** prove no device can report volume: unitless values, custom payloads, vendor cloud endpoints and integration-specific decoders remain to investigate. Keyword extraction is not a complete inventory of every possible action. Writable enum intensity is never automatically a volume sensor. Xiaomi ov42gl/ov42cn specs include wash/output settings, but their retail equivalence and live HA bindings have not been established.

## Acceptance

`python3 scripts/check_consumption_coverage.py` checks that each runtime profile has a coverage record and that the stored goal verdict matches outstanding gates. `--require-complete` exits 2 while any gate remains. Local CI validates truthful reporting without claiming the global objective has passed. New discoveries outside the runtime catalogue remain explicit acceptance blockers.

Next work belongs to Codex: extend manufacturer manuals and model/SKU inventory, verify marketing-to-protocol IDs, inspect relevant integration decoding/filtering, obtain action-specific rates and independent accuracy evidence. A physical cycle on Maciej's Roborock cannot close these cross-model gaps. Production remains read-only. No release.
