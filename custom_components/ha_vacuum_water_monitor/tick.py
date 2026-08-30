"""Server-side water accounting for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from homeassistant.core import HomeAssistant

from .sensor_calculations import apply_custom_calibration
from .storage import VacuumWaterStorage

MOP_WASH_STATES = {
    "washing_the_mop",
    "washing_the_mop_2",
    "going_to_wash_the_mop",
    "back_to_dock_washing_duster",
    "clean_mop_cleaning",
    "segment_clean_mop_cleaning",
    "zoned_clean_mop_cleaning",
}

AREA_MIN_DELTA = 0.1
DEFAULT_AREA_ANOMALY_CEILING_M2 = 25
RESET_COOLDOWN_SEC = 60


async def async_tick_water_state(
    hass: HomeAssistant, storage: VacuumWaterStorage
) -> dict[str, dict[str, Any]]:
    """Tick every known vacuum and persist changed states."""
    stored = await storage.async_get_state()
    devices = _devices_to_tick(hass, stored["settings"])
    previous = stored["tank_states"]
    changed: dict[str, dict[str, Any]] = {}

    for device in devices:
        vacuum_entity = device.get("vacuum_entity")
        if not vacuum_entity:
            continue
        # Respect user's pre-existing DIY automations: if the device config
        # points at an input_number/input_datetime for water tracking AND that
        # entity is registered in HA, the user already has automation/template
        # accounting in place. Skip our own tick to avoid double-counting.
        if _has_user_priv_helpers(hass, device):
            continue
        state = VacuumWaterStorage.default_tank_state()
        state.update(previous.get(vacuum_entity) or {})
        new_state, dirty = tick_device(hass, device, state)
        if dirty:
            changed[vacuum_entity] = new_state

    if changed:
        await storage.async_set_tank_states(changed)
    return changed


def tick_device(
    hass: HomeAssistant, device: dict[str, Any], state: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Translate one v4 `_tickWaterState` pass into Python."""
    vacuum_entity = device.get("vacuum_entity")
    vac = hass.states.get(vacuum_entity) if vacuum_entity else None
    if vac is None:
        return state, False

    dirty = False
    status_sensor = device.get("status_sensor")
    status_state = hass.states.get(status_sensor) if status_sensor else None
    curr_status = (
        status_state.state
        if status_state is not None
        else vac.attributes.get("status") or vac.state
    )

    curr_area = _float_or_none(_state_value(hass, device.get("area_sensor")))
    curr_dock_err = _state_value(hass, device.get("dock_error_sensor"))
    curr_door = (
        _state_value(hass, device.get("reset_door_sensor"))
        if device.get("reset_door_sensor")
        else None
    )

    vac_state = vac.state
    mop_mode_raw = (
        _state_value(hass, device.get("mop_mode_entity"))
        if device.get("mop_mode_entity")
        else None
    )
    mop_intensity_raw = (
        _state_value(hass, device.get("mop_intensity_entity"))
        if device.get("mop_intensity_entity")
        else None
    )
    mop_mode = _normalized_signal(mop_mode_raw)
    mop_intensity = _normalized_signal(mop_intensity_raw)
    mop_off = mop_mode == "off"
    usage_per_m2 = _mapping_number(device.get("usage_ml_per_m2"), mop_mode)
    intensity_factor = _mapping_number(device.get("intensity_factor"), mop_intensity)
    wash_volume = _positive_number(device.get("wash_volume_ml"))
    evidence = device.get("accounting_evidence")

    previous_status = state.get("last_status")
    if curr_status in MOP_WASH_STATES:
        if previous_status in MOP_WASH_STATES:
            dirty |= _record_accounting(
                state, "wash", wash_volume, evidence, "wash_already_active"
            )
        elif previous_status is None:
            dirty |= _record_accounting(
                state, "wash", wash_volume, evidence, "wash_initial_observation"
            )
        elif wash_volume is None:
            dirty |= _record_accounting(state, "wash", None, evidence, "missing_wash_rate")
        else:
            state["used_ml"] = round(_number(state.get("used_ml"), 0) + wash_volume, 2)
            dirty = True
            dirty |= _record_accounting(state, "wash", wash_volume, evidence, None)

    last_area = _float_or_none(state.get("last_area"))
    if curr_area is None:
        if last_area is not None:
            if not state.get("area_gap"):
                state["area_gap"] = True
                dirty = True
            dirty |= _record_accounting(state, "area", None, evidence, "area_unavailable")
    elif last_area is None:
        dirty |= _record_accounting(state, "area", None, evidence, "area_baseline_initialized")
    elif state.get("area_gap"):
        if state.get("area_gap"):
            state["area_gap"] = False
            dirty = True
        dirty |= _record_accounting(state, "area", None, evidence, "area_gap")
    else:
        delta = curr_area - last_area
        ceiling = _positive_number(device.get("area_anomaly_ceiling_m2")) or DEFAULT_AREA_ANOMALY_CEILING_M2
        if delta < 0:
            dirty |= _record_accounting(state, "area", None, evidence, "area_reset")
        elif delta > ceiling:
            dirty |= _record_accounting(state, "area", None, evidence, "area_anomaly")
        elif delta < AREA_MIN_DELTA:
            dirty |= _record_accounting(state, "area", None, evidence, "area_delta_below_minimum")
        elif not (vac_state == "cleaning" or curr_status == "cleaning"):
            dirty |= _record_accounting(state, "area", None, evidence, "not_cleaning")
        elif mop_off:
            dirty |= _record_accounting(state, "area", None, evidence, "mop_off")
        elif usage_per_m2 is None:
            dirty |= _record_accounting(state, "area", None, evidence, "missing_area_rate")
        elif isinstance(device.get("intensity_factor"), dict) and intensity_factor is None:
            dirty |= _record_accounting(state, "area", None, evidence, "missing_intensity_factor")
        else:
            added = delta * usage_per_m2 * (intensity_factor if intensity_factor is not None else 1)
            state["used_ml"] = round(_number(state.get("used_ml"), 0) + added, 2)
            dirty = True
            dirty |= _record_accounting(state, "area", usage_per_m2, evidence, None)

    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    cooldown_ok = (
        (now_ts - int(state.get("last_reset_ts") or 0)) / 1000
        > RESET_COOLDOWN_SEC
    )
    do_reset = False
    if curr_door and state.get("last_door") == "on" and curr_door == "off":
        do_reset = True
    if (
        state.get("last_dock_err") == "water_empty"
        and curr_dock_err
        and curr_dock_err != "water_empty"
    ):
        do_reset = True

    if do_reset and cooldown_ok:
        state["used_ml"] = 0
        state["initialized"] = True
        state["last_reset_iso"] = datetime.now(timezone.utc).isoformat()
        state["last_reset_ts"] = now_ts
        dirty = True
        dirty |= _record_accounting(state, "refill", None, evidence, "refill_detected")

    if state.get("last_status") != curr_status:
        state["last_status"] = curr_status
        dirty = True
    if curr_area is not None and state.get("last_area") != curr_area:
        state["last_area"] = curr_area
        dirty = True
    if state.get("last_dock_err") != curr_dock_err:
        state["last_dock_err"] = curr_dock_err
        dirty = True
    if state.get("last_door") != curr_door:
        state["last_door"] = curr_door
        dirty = True

    return state, dirty


def list_vacuums(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return enriched, registry-backed vacuum descriptors for the card."""
    from .discovery import descriptors_from_hass

    return descriptors_from_hass(hass)


def _devices_to_tick(
    hass: HomeAssistant, settings: dict[str, Any]
) -> list[dict[str, Any]]:
    from .sensor_calculations import build_vacuum_devices

    devices = build_vacuum_devices(settings, {}, list_vacuums(hass))
    return [apply_custom_calibration(device, settings) for device in devices]


def _has_user_priv_helpers(
    hass: HomeAssistant, device: dict[str, Any]
) -> bool:
    """Return True if the device config references a user-owned helper that
    already tracks water usage server-side (input_number / input_datetime /
    template sensor created by a DIY automation). In that case the integration
    must defer accounting to the user's existing setup and only display state.

    The card mirror (`www/ha-vacuum-water-monitor.js::_hasPrivHelpers`) is kept
    in sync — it queries the same key (`water_used_input`) against `hass.states`.
    """
    input_id = device.get("water_used_input")
    if not input_id:
        return False
    return hass.states.get(input_id) is not None


def _state_value(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return state.state if state is not None else None


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _positive_number(value: Any) -> float | None:
    parsed = _float_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def _normalized_signal(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized and normalized not in {"unknown", "unavailable"} else None


def _mapping_number(value: Any, key: str | None) -> float | None:
    """Read a rate only from an explicit mapping and its declared fallback."""
    if not isinstance(value, dict):
        return None
    if key is not None:
        direct = _positive_number(value.get(key))
        if direct is not None:
            return direct
    return _positive_number(value.get("default"))


def _record_accounting(
    state: dict[str, Any],
    source: str,
    rate: float | None,
    evidence: Any,
    reason: str | None,
) -> bool:
    """Persist the last accounting decision for diagnostics and sensor attrs."""
    payload = {
        "last_accounting_source": source,
        "last_accounting_rate_ml": rate,
        "last_accounting_evidence": evidence,
        "last_accounting_reason": reason,
    }
    changed = False
    for key, value in payload.items():
        if state.get(key) != value:
            state[key] = value
            changed = True
    return changed
