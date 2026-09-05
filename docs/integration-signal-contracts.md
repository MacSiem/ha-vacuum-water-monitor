# Integration signal contracts

Vacuum Water Monitor does not infer telemetry from localized entity names. Each automatic
adapter is a versioned contract over Home Assistant entity-registry `translation_key`
values, documented vacuum attributes, or Valetudo's canonical MQTT discovery keys. Signals
must belong to the same Home Assistant device as the vacuum; the only cross-device link is
one unambiguous Roborock dock with the same manufacturer, model prefix and config entry.

The accounting gate is deliberately strict:

1. Home Assistant must report an active cleaning state.
2. The adapter must provide affirmative mop evidence: a mop/combined cleaning mode, an
   active mop control, or an attached mop/water tank.
3. A model or user calibration must provide a rate for the signal axis actually exposed.
4. An explicit same-reservoir mL/L volume sensor is authoritative. Otherwise area is
   preferred and separately calibrated duration/active time is second. An unavailable
   configured duration counter never becomes wall time. Explicit unknown units fail closed.

## Implemented adapters

| Adapter | Activity/status contract | Area and duration | Mop gate and rate axis | Water/tank anchors | Behaviour when incomplete |
|---|---|---|---|---|---|
| Roborock | `vacuum` activity plus `status`/`a01_status`/`q7_status` and `in_cleaning`. Raw mopping, zoned/segment and mop-wash states are classified separately. | `cleaning_area` in m²; `cleaning_time` in seconds. | `cleaning_mode`, `mop_mode`/`cleaning_route`, `mop_intensity`/`water_box_mode`/`water_flow`, `mop_attached`, `water_box_attached`. | `water_shortage` is a debounced threshold. `clean_box_empty` and `clean_fluid_empty` are diagnostic only because Core may conflate empty and not-installed/transient states. | No automatic dose without mop evidence and an explicit model/user rate. |
| Matter RVC | `operational_state`: stopped, running, paused, error, seeking charger, charging or docked. | Matter RVC does not expose a standard cleaning-area or duration counter. | `clean_mode`; a supported model profile may use bounded active time only after the mode explicitly proves mopping. Tapo's water-flow level is not exposed by Matter, so its mode-gated seed does not pretend to select an intensity. | `operational_error`: exact `water_tank_empty`; missing/lid-open/dirty-tank states never mean consumed clean water. | Supported models can use a high-uncertainty cross-model seed and learn from low-water/refill anchors. Missing or vacuum-only `clean_mode`, unknown models, and capacity-only records fail closed/manual-only. |
| Ecovacs | Normalized `vacuum` activity. `station_state` is kept separate from robot activity. | `stats_area` in m²; `stats_time` in seconds. | `work_mode`, `water_amount` (select or model-specific number), `water_mop_attached`. | `station_state` is not a volume reading; only an explicit mop-wash state can trigger one profile-estimated wash cycle. Generic error remains diagnostic. | Numeric water controls are normalized from their own HA min/max, not a global scale. |
| iRobot Roomba/Braava | Normalized `vacuum` activity derived from the mission phase. | `cleaned_area` vacuum attribute: m² on metric HA and ft² on imperial HA; `cleaning_time` in minutes. | `fan_speed` contains Braava behaviour and spray amount; `tank_present` is an attachment gate. | `tank_level` and `dock_tank_level` are discovered percentages but remain non-authoritative until a model profile confirms clean/dirty semantics. | Unknown tank semantics never overwrite the estimate. |
| SmartThings | Normalized `vacuum` activity. | No standard same-device area/duration contract used by this adapter. | `robot_cleaner_cleaning_type` and `robot_cleaner_water_spray_level`; low through high spray values are intensity bands, not volume or percent. | None considered authoritative. | Needs a calibrated/model time rate and affirmative mop/combined mode. |
| Xiaomi Miio | Normalized `vacuum` activity. | `clean_area` in m²; `clean_time` in seconds. | `is_water_box_carriage_attached`, `is_water_box_attached`, `water_tank_detached`. | `is_water_shortage`/`no_water` are debounced threshold signals. | The generic Xiaomi Miio `water_level` sensor is intentionally excluded: in HA Core it belongs to non-vacuum device families such as humidifiers. |
| TP-Link | Normalized `vacuum` activity. | `clean_area` uses the entity's HA area unit; `clean_time` is normalized from the entity unit (native seconds). | Current HA Core does not publish python-kasa's mop attachment/water-level features as vacuum entities. | Generic TP-Link `water_alert` belongs to leak sensors and is never reused as vacuum telemetry. | Area/time can be used only with an explicit user-provided mop gate and rate, or when the same robot is exposed through Matter with a usable clean mode. |
| Dreame Vacuum (custom) | `state` is preferred over `status`, then `task_status`; `state` uniquely includes washing and returning-to-wash. Sweeping, mopping and combined states are distinct. | `cleaned_area` in m²; `cleaning_time` in minutes in the custom integration. | `cleaning_mode`, `water_volume`/`mop_pad_humidity`, `mop_pad`, `water_tank`. `sweeping` explicitly disables dosing even with a tank installed. | `self_wash_base_status`; exact `washing` is a wash sequence. Adding-water/drying/returning are not mop-wash volume by themselves. | Exact registry bindings survive temporary `unavailable`, because Dreame dynamically disables controls during some operations. Runtime use still fails closed while unavailable. |
| Valetudo MQTT | Canonical retained `status`/`robot_state`; dock status is separate. | `current_statistics_area` is cm² and is divided by 10,000; `current_statistics_time` is seconds. | `mode`/`operation_mode`, `water`/`water_grade`/`water_usage_control`, `mop`, `watertank`. | Fresh-water `empty` is exact; `missing` means absent hardware. Waste-water full is not clean-water consumption. | Only canonical Valetudo MQTT discovery names may use the documented original-name fallback. |

## Home Assistant vacuum integrations without an automatic water contract

Home Assistant also ships vacuum platforms such as LG ThinQ, Miele, Neato, Shark IQ,
SwitchBot/Cloud, Tuya, generic MQTT and Template. Their normalized vacuum activity is useful
for a dashboard, but it is not proof that water is being consumed. Unless the user explicitly
maps a same-device mop mode/attachment signal and supplies a calibrated rate, these platforms
remain manual-only. A generic `cleaning` state, manufacturer name, leak sensor, coffee-machine
water warning, or a similarly named entity on another device is never accepted.

Dock status follows the same rule: only explicit mop-wash states count a wash cycle.
Generic station `cleaning` is deliberately excluded because it can describe dust emptying or
station maintenance. Likewise, a dock `water_shortage` error is a debounced low-water threshold,
not an exact-empty measurement.

## Units and reset handling

- Area values are normalized from the current HA entity unit: m², cm² and ft² are supported.
- Duration values are normalized from seconds, minutes or hours.
- Counter decreases start a new baseline; they never create a negative dose.
- Missing/unavailable samples create a gap. The first sample after a gap only re-establishes
  the baseline, preventing a catch-up spike.
- A large one-minute area jump is rejected by the configurable anomaly ceiling.

## Primary sources

- [Home Assistant Roborock sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/roborock/sensor.py), [selects](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/roborock/select.py), and [binary sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/roborock/binary_sensor.py)
- [python-roborock state codes](https://github.com/Python-roborock/python-roborock/blob/main/roborock/data/v1/v1_code_mappings.py)
- [Home Assistant Matter RVC vacuum](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/matter/vacuum.py), [sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/matter/sensor.py), and [clean-mode select](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/matter/select.py)
- [Home Assistant Ecovacs sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/ecovacs/sensor.py), [selects](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/ecovacs/select.py), [numbers](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/ecovacs/number.py), and [binary sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/ecovacs/binary_sensor.py)
- [Home Assistant Roomba/Braava vacuum attributes](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/roomba/vacuum.py) and [tank sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/roomba/sensor.py)
- [Home Assistant SmartThings vacuum selects](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/smartthings/select.py)
- [Home Assistant Xiaomi Miio vacuum sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/xiaomi_miio/sensor.py) and [binary sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/xiaomi_miio/binary_sensor.py)
- [Home Assistant TP-Link vacuum sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/tplink/sensor.py) and [generic binary sensors](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/components/tplink/binary_sensor.py)
- [Dreame Vacuum entity reference](https://github.com/Tasshack/dreame-vacuum/blob/master/docs/entities.md) and [state enums](https://github.com/Tasshack/dreame-vacuum/blob/master/custom_components/dreame_vacuum/dreame/types.py)
- [Valetudo MQTT integration](https://valetudo.cloud/pages/integrations/mqtt/)

When an upstream integration changes one of these contracts, update the adapter and add a
registry-shaped regression fixture before enabling the new signal in automatic accounting.

## Dated verification boundary

[Machine-readable integration coverage](integration-coverage.json) inventories all 19
HA Core 2026.9.0 vacuum platforms plus the four reviewed custom surfaces. Eleven automatic
adapters have synthetic registry-shaped fixtures; zero have privately captured Diagnostics
committed here. Xiaomi Home is manufacturer-maintained custom code, Xiaomi Miio is HA Core,
Xiaomi MIoT and Dreame Vacuum are community custom code, and Valetudo is an optional local
MQTT surface. Prefer Core whenever it supplies equivalent data; custom surfaces are for
otherwise absent canonical properties/capabilities. Minimum-version and firmware coverage
remain unknown where not established by a source; mutable custom upstreams need rechecking.

Refill semantics are explicit: a cleared empty/shortage sensor is not full volume. A
same-reservoir anchor and measured threshold are required for learned correction;
`refill_on_clear` is opt-in only with a verified full-refill contract. `calibration_scope`
separates whole-cycle measurements from floor-only plus independent wash measurement.
# Additional setting contracts reviewed 2026-09-05

Source revision: Home Assistant Core `93ecba49bd35ee65d12596d3d7f28863a63dd8fe`.
This development snapshot does not certify an installed HA version or every model.

- Roborock B01/Q7 `select.cleaning_route` uses the device clean-path mapping;
  V1 `mop_mode` is a separate route selector. Discovery now binds the former as
  `route_entity`, preserving the existing V1 binding. [Source](https://github.com/home-assistant/core/blob/93ecba49bd35ee65d12596d3d7f28863a63dd8fe/homeassistant/components/roborock/select.py).
- Ecovacs `number.clean_count` is a capability-dependent 1–4 repeat setting,
  disabled by default. Discovery binds an enabled same-device entity as `passes_entity`.
  It is a requested count, not proof of completed passes. [Source](https://github.com/home-assistant/core/blob/93ecba49bd35ee65d12596d3d7f28863a63dd8fe/homeassistant/components/ecovacs/number.py).
- Both new roles require the expected entity domain and exact adapter key; changes
  enter the accounting context and rebaseline the crossing interval. Synthetic tests
  cover foreign/disabled/wrong-domain records. No setting is converted to water volume.
