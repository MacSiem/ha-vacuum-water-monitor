# Vacuum Water Monitor

![Preview](banner.png)

Track how much water is left in your robot vacuum's mop water tank — and get refill
reminders — without any extra hardware. The integration estimates water usage from what
your vacuum already reports to Home Assistant (machine states, cleaned area, duration,
mode and tank alerts) and exposes
it as sensors plus a bundled dashboard card.

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.7+-blue.svg?logo=homeassistant)](https://www.home-assistant.io/) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Version](https://img.shields.io/github/v/release/MacSiem/ha-vacuum-water-monitor)](https://github.com/MacSiem/ha-vacuum-water-monitor/releases)

## How it works

**Short version: the card reports an estimate, never a measured tank level.** After you
install the integration and add the card, press **💧 Refilled** while the tracked reservoir
is full. Until that refill baseline exists, remaining water and water used intentionally
stay **unknown** rather than displaying a fabricated 100% full tank.

What happens under the hood:

1. **Auto-discovery.** The integration finds every `vacuum.*` entity in your Home Assistant
   and creates a device with water sensors for each robot. No YAML, no entity picking.
2. **Water accounting runs server-side every 60 seconds.** It prefers cleaned-area deltas,
   then a duration counter, then a bounded active-time interval. Mode, intensity, mop/tank
   attachment and dock-wash signals are applied only when their integration exposes a
   canonical machine key. There is no friendly-name or translated-label guessing.
3. **Tank capacity and signals come from the Home Assistant device descriptor.** The
   integration resolves the canonical model profile from registry identifiers and only
   discovers status/area/time/mop signals belonging to that same device. A separate
   Roborock dock is linked only when manufacturer, model prefix and config entry match one
   unambiguous registry device. If capacity is
   unknown, the sensor shows "unknown capacity" instead of a misleading percentage — you
   can set it in the card's ⚙️ Settings tab.
4. **Refills and calibration anchors.** Press **Refilled** after filling the tracked
   reservoir. Exact machine-readable `empty` states may close a calibration cycle.
   Threshold-style low-water alerts require repeated observations and plausible prior
   usage; an early or unavailable alert never rewrites the counter. The default low-water
   reserve is 10% and can be tuned per device.
5. **Everything is stored by Home Assistant** (Store, included in backups) — counters
   survive restarts and work across all your devices and browsers.

### What is automatic vs. manual

| Automatic | Manual (optional) |
|---|---|
| Discovering vacuums | Pressing **Refilled** after you fill the tank |
| Water usage estimation when same-device signals and a model/user rate exist | Calibrating tank size, low-water reserve or active-time conversion |
| Tank capacity for known models | Wiring extra sensors (dock errors, tank door) |
| Sensors + card registration | Maintenance schedule entries |

> **Estimates, not measurements.** Most robot vacuums do not report actual water volume.
> Published tank capacities and integration signals are kept separate from empirical
> ml/m² and mop-wash estimates. Every time-derived fallback is labelled with high initial
> uncertainty and can learn a bounded per-device correction from valid refill-to-low-water
> cycles.

### Manual-only models and the refill baseline

Some models expose a trustworthy clean-water capacity but no usable consumption profile.
They remain **Manual-only** until you add a calibration. Models with an empirical ml/m²
profile can fall back to active time at a conservative 0.8 m²/min when their integration
does not expose area. This conversion is deliberately visible and editable. The
Diagnostics section shows the adapter, resolved profile, signal roles, estimate source,
uncertainty and calibration anchor.

### Integration signal compatibility

Automatic discovery uses versioned, per-integration machine contracts. The complete
status, entity-key, unit and fail-closed matrix is documented in
[Integration signal contracts](docs/integration-signal-contracts.md).

| Integration | Signals used when available | Important limitation |
|---|---|---|
| Roborock | status, in-cleaning, area, duration, mop mode/intensity, attachments, shortage and dock state | Binary clean-box alerts are not treated as exact volume because they can also mean missing/transient refill state. |
| Xiaomi Miio | current clean area/time, mop/tank attachment and no-water/shortage | HA Core's generic Xiaomi `water_level` sensor is not a vacuum entity and is deliberately excluded. |
| Ecovacs | stats area/time, water amount, work mode, mop attached and station state | Generic error text is diagnostic only, never a water-volume anchor. |
| Matter RVC | vacuum activity, clean mode and operational error when Home Assistant exposes them | No area is required: supported model profiles use bounded active time, but only while `clean_mode` explicitly proves mopping. Missing or vacuum-only mode fails closed. |
| iRobot Roomba/Braava | mission area/time attributes, tank-present and spray mode; tank percentages are discovered | Generic tank percentages are not used as clean water until a model profile confirms their semantics. |
| SmartThings | water-spray level and cleaning type | Spray level is an intensity, not liters or percent. |
| TP-Link | clean area/time | Current HA Core does not expose the vacuum mop features, so an explicit mop gate/calibration or usable Matter clean mode is still required. Generic TP-Link leak alerts are ignored. |
| Dreame Vacuum (custom) | preferred `state`, area/time, water volume, cleaning mode, mop/tank and self-wash base state | `state` distinguishes washing from ordinary cleaning; temporarily unavailable dynamic entities keep their exact registry binding but are never consumed while unavailable. |
| Valetudo MQTT | retained area/time, mode/water, attachments and clean/dirty tank enums | Area is normalized from cm². `empty` is an exact anchor; `missing` means absent hardware and never means consumed water. |
| SwitchBot, Shark IQ, Miele, generic MQTT | only explicitly exposed/configured machine signals | No water telemetry is inferred from a generic `cleaning` state or entity name. |

## Screenshots

| Light | Dark |
|---|---|
| ![Water tab, light theme](docs/screenshots/card-water-light.png) | ![Water tab, dark theme](docs/screenshots/card-water-dark.png) |

*The Water tab: estimated tank level, usage since refill, and the Refilled button. Dark
mode follows your Home Assistant theme automatically.*

![Settings tab](docs/screenshots/card-settings.png)

*Vacuums are auto-discovered — the ⚙️ Settings tab lets you add discovered robots, tune
calibration, and manage the maintenance schedule.*

## Installation

1. Open HACS → Custom repositories.
2. Add `https://github.com/MacSiem/ha-vacuum-water-monitor` as category **Integration**.
3. Install **Vacuum Water Monitor**.
4. Restart Home Assistant.
5. Go to Settings → Devices & services → Add integration, then search for
   **Vacuum Water Monitor**.

The integration registers the bundled Lovelace card automatically — you do not need to add
a Lovelace resource manually.

## Quick start

Add the card to any dashboard:

```yaml
type: custom:ha-vacuum-water-monitor
```

That's it. The card lists every discovered vacuum. When the tracked reservoir is full,
press **💧 Refilled** once to set the baseline. Before that, water remaining and used are
unknown by design.

> **Tip:** add the card (or press Refilled) when the tank is actually full, so tracking is
> accurate from the start.

## Entities for automations

Each discovered vacuum gets its own device with these sensors:

| Sensor | Unit | Entity category | Meaning |
|---|---:|---|---|
| Water remaining | `%` | normal | Estimated water left in the tank |
| Water used since refill | `mL` | normal | Usage accumulated since the last refill |
| Last refill | timestamp | diagnostic | When you last pressed Refilled (or auto-reset fired) |
| Next maintenance due | `d` | diagnostic | Days until the next custom maintenance item |

Use them like any other sensor — dashboards, template sensors, and automations.

**Low-water phone notification:**

```yaml
alias: Vacuum water below 15 percent
trigger:
  - platform: numeric_state
    entity_id: sensor.roborock_s8_maxv_ultra_water_remaining
    below: 15
action:
  - service: notify.mobile_app_phone
    data:
      title: Vacuum water low
      message: >-
        {{ state_attr(trigger.entity_id, 'vacuum_entity') }} has
        {{ states(trigger.entity_id) }}% water remaining
        ({{ state_attr(trigger.entity_id, 'remaining_ml') }} mL).
mode: single
```

**Maintenance reminder:**

```yaml
alias: Vacuum maintenance due tomorrow
trigger:
  - platform: numeric_state
    entity_id: sensor.roborock_s8_maxv_ultra_next_maintenance_due
    below: 2
action:
  - service: notify.mobile_app_phone
    data:
      title: Vacuum maintenance
      message: >-
        {{ state_attr(trigger.entity_id, 'next_item') }} is due in
        {{ states(trigger.entity_id) }} day(s).
mode: single
```

## Configuration (optional)

Everything below is optional — the defaults work out of the box.

```yaml
type: custom:ha-vacuum-water-monitor
title: Roborock
vacuum_entity: vacuum.roborock_s8_maxv_ultra
area_sensor: sensor.roborock_s8_maxv_ultra_cleaning_area
dock_error_sensor: sensor.roborock_s8_maxv_ultra_dock_error
warning_threshold: 20
critical_threshold: 10
```

### Extra sensor hooks

These optional keys let you wire additional entities into the water accounting
(used by both the card and the server-side integration):

| Option | Example | What it does |
|---|---|---|
| `status_sensor` | `sensor.roborock_..._status` | Dedicated status entity used instead of the vacuum's `status` attribute (or its state). Drives mop-wash detection only when the resolved model or user calibration provides a wash volume, and the "cleaning" check for area-based dosing. |
| `cleaning_active_sensor` | `binary_sensor.robot_..._in_cleaning` | Canonical activity flag used when the vacuum state lags. |
| `area_sensor` | `sensor.robot_..._cleaning_area` | Cumulative current-session area. Resets and implausible jumps are rejected. |
| `duration_sensor` | `sensor.robot_..._cleaning_time` | Cumulative session duration used only when area is unavailable. Units from Home Assistant are normalized. |
| `mop_mode_entity` | `select.roborock_..._mop_mode` | Current mop mode (`fast` / `standard` / `deep`). Selects a resolved per-m² model/user calibration rate. Mode `off` disables area-based dosing entirely; an unavailable mode cannot manufacture a rate. |
| `mop_intensity_entity` | `select.roborock_..._mop_intensity` | Current mop intensity / water level. Documented three- and five-level option tokens are mapped to/interpolated between the profile's low/medium/high bands. Ranged number entities use their own HA min/max, so model-specific scales are not guessed. Unknown options use only an explicit profile default. |
| `cleaning_mode_entity` | `select.robot_..._cleaning_mode` | Prevents water accounting during canonical vacuum-only/dry modes. |
| `mop_attached_sensor` / `water_box_attached_sensor` | `binary_sensor.robot_..._mop_attached` | Stops automatic dosing when the mop or tank is absent. Inverted detached signals are handled separately. |
| `water_shortage_sensor` | `binary_sensor.robot_..._water_shortage` | Debounced low-water threshold used as an estimated calibration anchor after plausible prior usage. |
| `dock_clean_water_sensor` / `dock_dirty_water_sensor` | `sensor.robot_..._water_tank_clean` | Uses canonical enum semantics. `missing` is never treated as consumption. |
| `dock_status_sensor` | `sensor.robot_..._station_state` | Detects one dock mop-wash cycle without confusing robot cleaning with dock cleaning. |
| `water_error_sensor` | `sensor.robot_..._operational_error` | Accepts only exact machine-readable clean-water-empty states. |
| `reset_door_sensor` | `binary_sensor.roborock_..._water_tank` | Tank-lid / door binary sensor. An `on` → `off` transition counts as "tank refilled" and resets the used-water counter automatically (60 s debounce between auto-resets). |

### Advanced — bring your own counter

If you already maintain your own water counter (DIY template sensor or automation updating
an `input_number`), wire it in and the integration will skip its own accounting and only
display your data:

```yaml
type: custom:ha-vacuum-water-monitor
vacuum_entity: vacuum.roborock_s8_maxv_ultra
water_used_input: input_number.roborock_water_used_ml
water_sensor: sensor.roborock_water_remaining              # optional template
last_session_sensor: sensor.roborock_water_used_last_session  # optional
last_reset_entity: input_datetime.roborock_last_water_reset   # optional
```

## FAQ

**Do I have to configure anything?**
No. Install → add integration → add card → press Refilled when the tank is full.

**Why is "Water remaining" unknown?**
First press **Refilled** with the tracked reservoir full. Before that baseline, both water
sensors intentionally stay unknown even when the model and its capacity were detected.
If Diagnostics says `unknown_capacity`, set the tank size in ⚙️ Settings → calibration
(and feel free to open an issue with your model + tank size so we can add it). If it says
`awaiting_refill`, the model is already recognized and only the baseline is missing.

**Why is "Next maintenance due" unknown?**
That diagnostic sensor has no truthful numeric value until at least one maintenance item
has been scheduled. Add a maintenance interval in the card settings; `unknown` before
that means “no schedule”, not a failed vacuum detector.

**I see two devices but I only have one vacuum.**
Either your robot is exposed by two integrations at once (e.g. the vendor integration and
Matter — each creates its own `vacuum.*` entity), or you hit a bug fixed in v5.1.7 where a
ghost "Vacuum" device could be created by the card's default config. Update and restart —
the ghost is removed automatically. If it persists, remove it in Settings →
Devices & services.

**The dock shows as a separate device in Home Assistant — does it affect this?**
A separate Roborock dock can be used when the device registry gives one unambiguous match:
same manufacturer, matching robot-model prefix and a shared config entry. Otherwise the
link fails closed and the dock is ignored instead of borrowing signals from another robot.

**How accurate is it?**
Accuracy depends on the integration and model. Area + a device-calibrated rate is the best
estimate; duration/active-time fallback starts with higher uncertainty. Exact tank enum
states and debounced low-water thresholds can refine the correction factor over complete
cycles. You can tune mL/m², cleaning speed, low-water reserve and wash volume per vacuum.

## Upgrading from v4

v4 was a HACS Lovelace plugin. v5 is a HACS integration.

1. In HACS, remove the old frontend/plugin installation if it is still present.
2. Remove any manual Lovelace resource pointing at
   `/local/community/ha-vacuum-water-monitor/ha-vacuum-water-monitor.js`.
3. Add this repository back to HACS as category **Integration**.
4. Restart Home Assistant and add the integration from Devices & services.
5. Keep the same Lovelace card YAML: `type: custom:ha-vacuum-water-monitor`.

Browser-only v4 tank counters are not automatically imported. After installing v5, press
**Refilled** once when the tank is full to establish the server-side baseline.

## Privacy

- No telemetry, analytics, or tracking.
- No CDN-hosted assets.
- No maps, room names, entity states, registry identifiers or calibration history leave
  Home Assistant.
- Tank state is stored locally by Home Assistant in its normal storage area and is included
  in Home Assistant backups.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Support

- [Buy Me a Coffee](https://buymeacoffee.com/macsiem)
- [PayPal](https://www.paypal.com/donate/?hosted_button_id=Y967H4PLRBN8W)

## License

MIT, see [LICENSE](LICENSE).
