"""Server-side water accounting for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

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

DEFAULT_USAGE_PER_M2 = {"fast": 4, "standard": 6, "deep": 9}
DEFAULT_INTENSITY_FACTOR = {
    "low": 0.8,
    "medium": 1.0,
    "high": 1.2,
    "max": 1.3,
    "custom": 1.0,
    "smart_mode": 1.0,
    "custom_water_flow": 1.0,
}
DEFAULT_WASH_VOLUME_ML = 150
AREA_MIN_DELTA = 0.1
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
    mop_mode = (
        mop_mode_raw
        if mop_mode_raw and mop_mode_raw not in {"off", "unavailable"}
        else "standard"
    )
    mop_intensity = (
        mop_intensity_raw
        if mop_intensity_raw and mop_intensity_raw != "unavailable"
        else "medium"
    )
    mop_off = mop_mode_raw == "off"

    usage_per_m2 = _mapping_number(
        device.get("usage_ml_per_m2"),
        mop_mode,
        DEFAULT_USAGE_PER_M2.get(mop_mode, 6),
    )
    intensity_factor = _mapping_number(
        device.get("intensity_factor"),
        mop_intensity,
        DEFAULT_INTENSITY_FACTOR.get(mop_intensity, 1.0),
    )
    wash_volume = _number(device.get("wash_volume_ml"), DEFAULT_WASH_VOLUME_ML)

    if (
        state.get("last_status") is not None
        and curr_status != state.get("last_status")
        and curr_status in MOP_WASH_STATES
    ):
        state["used_ml"] = round(_number(state.get("used_ml"), 0) + wash_volume)
        dirty = True

    last_area = _float_or_none(state.get("last_area"))
    if last_area is not None and curr_area is not None and curr_area > last_area:
        delta = curr_area - last_area
        is_cleaning = vac_state == "cleaning" or curr_status == "cleaning"
        can_dose = not mop_off and is_cleaning and delta >= AREA_MIN_DELTA
        if can_dose:
            added = delta * usage_per_m2 * intensity_factor
            state["used_ml"] = round(_number(state.get("used_ml"), 0) + added)
            dirty = True

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
        state["last_reset_iso"] = datetime.now(timezone.utc).isoformat()
        state["last_reset_ts"] = now_ts
        dirty = True

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
    """Return HA-known vacuum entities for the card."""
    vacuums = []
    for entity_id in sorted(hass.states.async_entity_ids("vacuum")):
        state = hass.states.get(entity_id)
        if state is None:
            continue
        vacuums.append(
            {
                "entity_id": entity_id,
                "name": state.attributes.get("friendly_name") or entity_id,
                "state": state.state,
                "battery": state.attributes.get("battery_level"),
            }
        )
    return vacuums


def _devices_to_tick(
    hass: HomeAssistant, settings: dict[str, Any]
) -> list[dict[str, Any]]:
    devices: dict[str, dict[str, Any]] = {}
    for item in settings.get("configured_devices") or []:
        if isinstance(item, dict) and item.get("vacuum_entity"):
            devices[item["vacuum_entity"]] = dict(item)
    for item in settings.get("user_devices") or []:
        if isinstance(item, dict) and item.get("vacuum_entity"):
            devices[item["vacuum_entity"]] = dict(item)
    for vacuum in list_vacuums(hass):
        devices.setdefault(
            vacuum["entity_id"],
            {
                "vacuum_entity": vacuum["entity_id"],
                "name": vacuum["name"],
            },
        )
    return list(devices.values())


def _state_value(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return state.state if state is not None else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mapping_number(value: Any, key: str, default: float) -> float:
    if isinstance(value, dict):
        return _number(value.get(key), default)
    return default
