"""Server-side water accounting for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any
import unicodedata

from homeassistant.core import HomeAssistant

from .sensor_calculations import apply_custom_calibration
from .storage import VacuumWaterStorage

MOP_WASH_STATES = {
    "washing",
    "washing_the_mop",
    "washing_the_mop_2",
    "going_to_wash_the_mop",
    "back_to_dock_washing_duster",
    "clean_mop_cleaning",
    "segment_clean_mop_cleaning",
    "zoned_clean_mop_cleaning",
    "lavage_de_la_serpillere",
    "lavage_des_serpilleres",
    "mop_washing",
    "washing_mop",
}
# Dock state vocabularies are not interchangeable with a robot's activity
# state.  In particular, generic ``cleaning`` can describe station self-care,
# dust emptying, or another maintenance task.  Count only explicit mop-wash
# states that are already part of the canonical wash contract above.
DOCK_WASH_STATES = frozenset(MOP_WASH_STATES)

AREA_MIN_DELTA = 0.1
DEFAULT_AREA_ANOMALY_CEILING_M2 = 25
RESET_COOLDOWN_SEC = 60
MAX_ACTIVE_INTERVAL_SECONDS = 180
WATER_ANCHOR_CONFIRMATION_SECONDS = 60
DEFAULT_LOW_WATER_REMAINING_PERCENT = 10
MIN_CALIBRATION_USAGE_FRACTION = 0.05
MIN_SHORTAGE_ANCHOR_USAGE_FRACTION = 0.25
MIN_CALIBRATION_FACTOR = 0.25
MAX_CALIBRATION_FACTOR = 4.0

_ACTIVE_CLEANING_STATES = {
    "auto_cleaning",
    "cleaning",
    "clean_mop_mopping",
    "running",
    "part_cleaning",
    "robot_status_mopping",
    "segment_mopping",
    "segment_clean_mop_mopping",
    "sweeping",
    "sweeping_and_mopping",
    "mopping",
    "spot_cleaning",
    "vacuuming",
    "vacuum_and_mop",
    "auto_vacuum_and_mop",
    "segment_cleaning",
    "zone_cleaning",
    "zone_mopping",
    "zoned_cleaning",
    "zoned_mopping",
    "zoned_clean_mop_mopping",
    "room_cleaning",
    "mop_cleaning",
}
_MOP_DISABLED_MODES = {
    "off",
    "vacuum",
    "vacuum_only",
    "auto_vacuum_only",
    "sweep",
    "sweep_only",
    "sweeping",
    "dry",
}


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
    hass: HomeAssistant,
    device: dict[str, Any],
    state: dict[str, Any],
    *,
    now_ts: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Translate one v4 `_tickWaterState` pass into Python."""
    state = dict(state)
    vacuum_entity = device.get("vacuum_entity")
    vac = hass.states.get(vacuum_entity) if vacuum_entity else None
    if vac is None:
        return state, False

    dirty = False
    status_sensor = device.get("status_sensor")
    status_state = hass.states.get(status_sensor) if status_sensor else None
    if status_sensor:
        curr_status_raw = status_state.state if status_state is not None else None
    else:
        curr_status_raw = vac.attributes.get("status") or vac.state
    curr_status = _normalized_signal(curr_status_raw)

    curr_area = _area_square_meters(hass, device.get("area_sensor"))
    if curr_area is None and device.get("area_attribute"):
        curr_area = _area_value_square_meters(
            vac.attributes.get(device["area_attribute"]),
            device.get("area_attribute_unit"),
            hass,
        )
    curr_dock_err = _normalized_signal(
        _state_value(hass, device.get("dock_error_sensor"))
    )
    curr_dock_status = _normalized_signal(
        _state_value(hass, device.get("dock_status_sensor"))
    )
    curr_door = (
        _state_value(hass, device.get("reset_door_sensor"))
        if device.get("reset_door_sensor")
        else None
    )

    vac_state = _normalized_signal(vac.state)
    mop_mode_raw = (
        _state_value(hass, device.get("mop_mode_entity"))
        if device.get("mop_mode_entity")
        else None
    )
    mop_intensity_raw = _entity_or_vacuum_attribute(
        hass,
        device.get("mop_intensity_entity"),
        vac,
        device.get("mop_intensity_attribute"),
    )
    mop_mode = _normalized_signal(mop_mode_raw)
    mop_intensity = _normalized_signal(mop_intensity_raw)
    cleaning_mode = _normalized_signal(
        _state_value(hass, device.get("cleaning_mode_entity"))
    )
    mop_attached = _binary_active(
        _state_value(hass, device.get("mop_attached_sensor"))
    )
    water_box_attached = _attachment_present(
        _entity_or_vacuum_attribute(
            hass,
            device.get("water_box_attached_sensor"),
            vac,
            device.get("water_box_attached_attribute"),
        )
    )
    water_box_detached = _binary_active(
        _state_value(hass, device.get("water_box_detached_sensor"))
    )
    if water_box_detached is not None:
        water_box_attached = not water_box_detached
    mop_active = _is_mop_active(
        cleaning_mode,
        mop_mode,
        mop_attached,
        water_box_attached,
        require_evidence=bool(device.get("mop_evidence_required")),
    )
    cleaning_active = _binary_active(
        _state_value(hass, device.get("cleaning_active_sensor"))
    )
    curr_duration_seconds = _duration_seconds(
        hass, device.get("duration_sensor")
    )
    if curr_duration_seconds is None and device.get("duration_attribute"):
        curr_duration_seconds = _duration_value_seconds(
            vac.attributes.get(device["duration_attribute"]),
            device.get("duration_attribute_unit"),
        )
    rate_signal = str(device.get("rate_signal") or "mop_mode")
    rate_key = mop_intensity if rate_signal == "mop_intensity" else mop_mode
    if rate_signal == "mop_intensity":
        rate_key = _intensity_rate_key(
            hass,
            device.get("mop_intensity_entity"),
            mop_intensity_raw,
            mop_intensity,
        )
    if rate_signal == "cleaning_mode":
        rate_key = cleaning_mode
    usage_per_m2 = _mapping_number(device.get("usage_ml_per_m2"), rate_key)
    intensity_factor = _mapping_number(device.get("intensity_factor"), mop_intensity)
    calibration_factor = _clamp(
        _positive_number(state.get("calibration_factor")) or 1,
        MIN_CALIBRATION_FACTOR,
        MAX_CALIBRATION_FACTOR,
    )
    usage_per_minute = _mapping_number(
        device.get("usage_ml_per_active_minute"), rate_key
    )
    wash_volume_base = _positive_number(device.get("wash_volume_ml"))
    wash_volume = (
        wash_volume_base * calibration_factor
        if wash_volume_base is not None
        else None
    )
    evidence = device.get("accounting_evidence")
    time_evidence = device.get("time_accounting_evidence") or evidence
    if int(state.get("calibration_samples") or 0) > 0:
        evidence = "device_calibrated"
        time_evidence = "device_calibrated"

    if now_ts is None:
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    previous_status = state.get("last_status")
    previous_dock_status = state.get("last_dock_status")
    wash_active = bool(state.get("wash_sequence_active")) or (
        previous_status in MOP_WASH_STATES
        or previous_dock_status in DOCK_WASH_STATES
    )
    wash_now = (
        curr_status in MOP_WASH_STATES
        or curr_dock_status in DOCK_WASH_STATES
    )
    if wash_now:
        if wash_active:
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
        if not state.get("wash_sequence_active"):
            state["wash_sequence_active"] = True
            dirty = True
    elif (
        not _is_transient_status(curr_status)
        and (
            not device.get("dock_status_sensor")
            or not _is_transient_status(curr_dock_status)
        )
    ):
        if state.get("wash_sequence_active"):
            state["wash_sequence_active"] = False
            dirty = True

    last_area = _float_or_none(state.get("last_area"))
    if curr_area is None:
        if device.get("area_sensor"):
            if not state.get("area_gap"):
                state["area_gap"] = True
                dirty = True
            dirty |= _record_accounting(state, "area", None, evidence, "area_unavailable")
    elif last_area is None:
        if state.get("area_gap"):
            state["area_gap"] = False
            dirty = True
            dirty |= _record_accounting(state, "area", None, evidence, "area_gap")
        else:
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
        elif delta < AREA_MIN_DELTA and not math.isclose(
            delta, AREA_MIN_DELTA, rel_tol=0, abs_tol=1e-9
        ):
            dirty |= _record_accounting(state, "area", None, evidence, "area_delta_below_minimum")
        elif not _is_cleaning(vac_state, curr_status, cleaning_active):
            dirty |= _record_accounting(state, "area", None, evidence, "not_cleaning")
        elif not mop_active:
            dirty |= _record_accounting(state, "area", None, evidence, "mop_off")
        elif usage_per_m2 is None:
            dirty |= _record_accounting(state, "area", None, evidence, "missing_area_rate")
        elif isinstance(device.get("intensity_factor"), dict) and intensity_factor is None:
            dirty |= _record_accounting(state, "area", None, evidence, "missing_intensity_factor")
        else:
            effective_area_rate = usage_per_m2 * calibration_factor
            added = delta * effective_area_rate * (
                intensity_factor if intensity_factor is not None else 1
            )
            state["used_ml"] = round(_number(state.get("used_ml"), 0) + added, 2)
            dirty = True
            dirty |= _record_accounting(
                state, "area", effective_area_rate, evidence, None
            )

    # Matter and some vendor integrations expose only operational state and
    # cleaning mode.  When no trustworthy area sample is available, estimate
    # consumption from bounded active time instead of leaving the counter stuck.
    previous_tick_ts = _positive_number(state.get("last_tick_ts"))
    last_duration_seconds = _float_or_none(state.get("last_duration_seconds"))
    should_use_time = curr_area is None
    elapsed_seconds: float | None = None
    if should_use_time and curr_duration_seconds is not None:
        if last_duration_seconds is None:
            dirty |= _record_accounting(
                state,
                "active_time",
                None,
                time_evidence,
                "duration_baseline_initialized",
            )
        else:
            elapsed_seconds = curr_duration_seconds - last_duration_seconds
    elif should_use_time and previous_tick_ts is not None:
        elapsed_seconds = (now_ts - previous_tick_ts) / 1000

    if should_use_time and elapsed_seconds is not None:
        if elapsed_seconds <= 0 or elapsed_seconds > MAX_ACTIVE_INTERVAL_SECONDS:
            dirty |= _record_accounting(
                state, "active_time", None, time_evidence, "active_time_gap"
            )
        elif not _is_cleaning(vac_state, curr_status, cleaning_active):
            dirty |= _record_accounting(
                state, "active_time", None, time_evidence, "not_cleaning"
            )
        elif not mop_active:
            dirty |= _record_accounting(
                state, "active_time", None, time_evidence, "mop_inactive"
            )
        elif usage_per_minute is None:
            dirty |= _record_accounting(
                state, "active_time", None, time_evidence, "missing_time_rate"
            )
        else:
            effective_minute_rate = usage_per_minute * calibration_factor
            added = (elapsed_seconds / 60) * effective_minute_rate
            state["used_ml"] = round(
                _number(state.get("used_ml"), 0) + added, 2
            )
            dirty = True
            dirty |= _record_accounting(
                state, "active_time", effective_minute_rate, time_evidence, None
            )

    # A configured status signal that is temporarily absent/unavailable is the
    # most actionable diagnostic for this pass, even when an area baseline was
    # also initialized.  Recording this last keeps the UI from claiming ready.
    if status_sensor and _is_transient_status(curr_status):
        dirty |= _record_accounting(
            state, "wash", None, evidence, "status_unavailable"
        )

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

    water_anchor_states = _water_anchor_states(hass, device, curr_dock_err)
    active_anchors = [
        (source, kind)
        for source, (is_empty, kind) in water_anchor_states.items()
        if is_empty is True
    ]
    active_anchor = next(
        (anchor for anchor in active_anchors if anchor[1] == "empty"),
        active_anchors[0] if active_anchors else None,
    )
    water_empty_now = active_anchor is not None
    water_empty_before = bool(state.get("water_empty_active"))

    # A low-water binary signal is a threshold alert, not a direct volume
    # measurement.  Require it to survive two scheduled observations before it
    # can close a calibration cycle.  Exact machine-readable ``empty`` states
    # (Valetudo enum / Matter RVC error) are accepted immediately.
    if active_anchor is not None and active_anchor[1] == "shortage" and not water_empty_before:
        anchor_source = active_anchor[0]
        candidate_source = state.get("water_anchor_candidate_source")
        candidate_since = _positive_number(state.get("water_anchor_candidate_since_ts"))
        if candidate_source != anchor_source or candidate_since is None:
            state["water_anchor_candidate_source"] = anchor_source
            state["water_anchor_candidate_since_ts"] = now_ts
            dirty = True
            dirty |= _record_accounting(
                state,
                "low_water",
                None,
                evidence,
                "low_water_confirmation_pending",
            )
            active_anchor = None
            water_empty_now = False
        elif (now_ts - candidate_since) / 1000 < WATER_ANCHOR_CONFIRMATION_SECONDS:
            active_anchor = None
            water_empty_now = False
    elif active_anchor is None and state.get("water_anchor_candidate_source"):
        state["water_anchor_candidate_source"] = None
        state["water_anchor_candidate_since_ts"] = 0
        dirty = True

    # Vendor shortage signals are threshold alarms and can be raised by an
    # incorrectly seated tank or unsuitable water conductivity.  Even after
    # debounce, do not let an implausibly early alert rewrite a healthy
    # estimate or teach a destructive calibration factor.  Exact enum/error
    # states remain authoritative and are handled below without this guard.
    if (
        water_empty_now
        and active_anchor is not None
        and active_anchor[1] == "shortage"
    ):
        shortage_capacity = _device_capacity_ml(device)
        shortage_predicted = _positive_number(state.get("used_ml"))
        shortage_initialized = bool(
            state.get("initialized") or state.get("last_reset_iso")
        )
        if (
            shortage_capacity is not None
            and shortage_initialized
            and (
                shortage_predicted is None
                or shortage_predicted
                < shortage_capacity * MIN_SHORTAGE_ANCHOR_USAGE_FRACTION
            )
        ):
            state["water_anchor_candidate_source"] = None
            state["water_anchor_candidate_since_ts"] = 0
            state["last_low_water_ts"] = now_ts
            dirty = True
            dirty |= _record_accounting(
                state,
                "low_water",
                None,
                evidence,
                "low_water_rejected_insufficient_usage",
            )
            active_anchor = None
            water_empty_now = False

    if water_empty_now and not water_empty_before:
        assert active_anchor is not None
        anchor_source, anchor_kind = active_anchor
        state["water_empty_active"] = True
        state["water_anchor_source"] = anchor_source
        state["water_anchor_kind"] = anchor_kind
        state["water_anchor_confidence"] = (
            "exact" if anchor_kind == "empty" else "estimated"
        )
        state["water_anchor_candidate_source"] = None
        state["water_anchor_candidate_since_ts"] = 0
        state["last_low_water_ts"] = now_ts
        dirty = True
        capacity = _device_capacity_ml(device)
        predicted_used = _positive_number(state.get("used_ml"))
        initialized = bool(state.get("initialized") or state.get("last_reset_iso"))
        if capacity is not None and initialized:
            remaining_percent = (
                0.0
                if anchor_kind == "empty"
                else _clamp(
                    _number(
                        device.get("low_water_anchor_remaining_percent"),
                        DEFAULT_LOW_WATER_REMAINING_PERCENT,
                    ),
                    0,
                    50,
                )
            )
            calibration_target = capacity * (1 - remaining_percent / 100)
            if (
                predicted_used is not None
                and predicted_used >= capacity * MIN_CALIBRATION_USAGE_FRACTION
            ):
                samples = max(0, int(state.get("calibration_samples") or 0))
                observed_factor = _clamp(
                    calibration_factor * calibration_target / predicted_used,
                    MIN_CALIBRATION_FACTOR,
                    MAX_CALIBRATION_FACTOR,
                )
                learned_factor = (
                    calibration_factor * samples + observed_factor
                ) / (samples + 1)
                state["calibration_factor"] = round(
                    _clamp(
                        learned_factor,
                        MIN_CALIBRATION_FACTOR,
                        MAX_CALIBRATION_FACTOR,
                    ),
                    4,
                )
                state["calibration_samples"] = samples + 1
                state["last_calibration_predicted_ml"] = round(
                    predicted_used, 2
                )
                state["last_calibration_target_ml"] = round(
                    calibration_target, 2
                )
                state["used_ml"] = round(calibration_target, 2)
                dirty |= _record_accounting(
                    state,
                    "low_water",
                    state["calibration_factor"],
                    "device_calibrated",
                    "low_water_calibrated",
                )
            else:
                state["used_ml"] = round(calibration_target, 2)
                dirty |= _record_accounting(
                    state,
                    "low_water",
                    None,
                    evidence,
                    "low_water_detected_without_sample",
                )
        else:
            dirty |= _record_accounting(
                state,
                "low_water",
                None,
                evidence,
                "low_water_detected",
            )
    elif water_empty_before and not water_empty_now:
        previous_anchor_source = state.get("water_anchor_source")
        if previous_anchor_source in water_anchor_states:
            do_reset = (
                water_anchor_states[previous_anchor_source][0] is False
            )
        elif len(water_anchor_states) == 1:
            # Additive migration for v5.2 records written before anchor source
            # was persisted.  Unknown/unavailable never counts as a refill.
            do_reset = next(iter(water_anchor_states.values()))[0] is False

    if do_reset and cooldown_ok:
        state["used_ml"] = 0
        state["initialized"] = True
        state["last_reset_iso"] = datetime.fromtimestamp(
            now_ts / 1000, tz=timezone.utc
        ).isoformat()
        state["last_reset_ts"] = now_ts
        state["water_empty_active"] = False
        state["water_anchor_candidate_source"] = None
        state["water_anchor_candidate_since_ts"] = 0
        dirty = True
        dirty |= _record_accounting(state, "refill", None, evidence, "refill_detected")

    if state.get("last_status") != curr_status:
        state["last_status"] = curr_status
        dirty = True
    if curr_area is not None and state.get("last_area") != curr_area:
        state["last_area"] = curr_area
        dirty = True
    if (
        curr_duration_seconds is not None
        and state.get("last_duration_seconds") != curr_duration_seconds
    ):
        state["last_duration_seconds"] = curr_duration_seconds
        dirty = True
    if state.get("last_dock_err") != curr_dock_err:
        state["last_dock_err"] = curr_dock_err
        dirty = True
    if state.get("last_dock_status") != curr_dock_status:
        state["last_dock_status"] = curr_dock_status
        dirty = True
    if state.get("last_door") != curr_door:
        state["last_door"] = curr_door
        dirty = True
    if state.get("last_tick_ts") != now_ts:
        state["last_tick_ts"] = now_ts
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


def _entity_or_vacuum_attribute(
    hass: HomeAssistant,
    entity_id: str | None,
    vacuum_state: Any,
    attribute: str | None,
) -> Any:
    """Prefer a configured entity and fall back to a canonical vacuum attribute."""
    value = _state_value(hass, entity_id)
    if _normalized_signal(value) is not None:
        return value
    if attribute and vacuum_state is not None:
        attributes = getattr(vacuum_state, "attributes", {})
        if isinstance(attributes, dict):
            return attributes.get(attribute)
    return value


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
    normalized = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    return normalized if normalized and normalized not in {"unknown", "unavailable"} else None


def _is_transient_status(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or value.strip().lower() in {
        "unknown",
        "unavailable",
    }


def _is_cleaning(
    vacuum_state: str | None,
    status: str | None,
    cleaning_active: bool | None = None,
) -> bool:
    return (
        cleaning_active is True
        or vacuum_state in _ACTIVE_CLEANING_STATES
        or status in _ACTIVE_CLEANING_STATES
    )


def _is_mop_active(
    cleaning_mode: str | None,
    mop_mode: str | None,
    mop_attached: bool | None,
    water_box_attached: bool | None = None,
    *,
    require_evidence: bool = False,
) -> bool:
    if mop_attached is False or water_box_attached is False:
        return False
    for value in (cleaning_mode, mop_mode):
        if value in _MOP_DISABLED_MODES:
            return False
        if value and "vacuum_only" in value:
            return False
    if cleaning_mode and "mop" in cleaning_mode:
        return True
    if mop_mode is not None:
        return mop_mode not in _MOP_DISABLED_MODES
    if mop_attached is True or water_box_attached is True:
        return True
    if require_evidence:
        return False
    return True


def _binary_active(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalized_signal(value)
    if normalized in {"on", "true", "yes", "active", "1", "empty", "shortage"}:
        return True
    if normalized in {"off", "false", "no", "inactive", "0", "ok", "normal"}:
        return False
    return None


def _attachment_present(value: Any) -> bool | None:
    """Interpret binary and enum attachment signals without parsing prose."""
    if isinstance(value, bool):
        return value
    normalized = _normalized_signal(value)
    if normalized in {
        "on",
        "true",
        "yes",
        "1",
        "attached",
        "installed",
        "mop_installed",
        "present",
        "ok",
    }:
        return True
    if normalized in {
        "off",
        "false",
        "no",
        "0",
        "detached",
        "missing",
        "not_installed",
        "not_present",
    }:
        return False
    return None


def _duration_seconds(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Return a duration sensor in seconds using its HA unit metadata."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    value = _float_or_none(state.state)
    if value is None or value < 0:
        return None
    unit = _normalized_signal(state.attributes.get("unit_of_measurement"))
    if unit is None or unit in {"s", "sec", "second", "seconds"}:
        return value
    if unit in {"min", "minute", "minutes"}:
        return value * 60
    if unit in {"h", "hr", "hour", "hours"}:
        return value * 3600
    return None


def _area_square_meters(
    hass: HomeAssistant, entity_id: str | None
) -> float | None:
    """Return an area sensor normalized to square metres.

    HA integrations do not share one native unit: Valetudo publishes cm²,
    while Roborock/Ecovacs/Dreame commonly expose m² and TP-Link can follow the
    device's m²/ft² area setting.  The entity's current HA unit is authoritative
    because users may also change its display unit.
    """
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return _area_value_square_meters(
        state.state, state.attributes.get("unit_of_measurement"), hass
    )


def _area_value_square_meters(
    value: Any, unit_value: Any, hass: HomeAssistant | None = None
) -> float | None:
    """Normalize a finite, non-negative area value to square metres."""
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return None
    if unit_value == "ha_unit_system":
        units = getattr(getattr(hass, "config", None), "units", None)
        length_unit = str(getattr(units, "length_unit", "")).casefold()
        unit_value = "ft2" if length_unit in {"mi", "mile", "miles"} else "m2"
    if unit_value is None or str(unit_value).strip() == "":
        # Existing custom sensors historically supplied m² without metadata.
        return parsed
    unit = (
        unicodedata.normalize("NFKC", str(unit_value))
        .casefold()
        .replace("²", "2")
        .replace("^2", "2")
        .replace(" ", "")
        .replace("_", "")
    )
    if unit in {"m2", "sqm", "squaremeter", "squaremeters", "squaremetre", "squaremetres"}:
        return parsed
    if unit in {"cm2", "sqcm", "squarecentimeter", "squarecentimeters", "squarecentimetre", "squarecentimetres"}:
        return parsed / 10_000
    if unit in {"ft2", "sqft", "squarefoot", "squarefeet"}:
        return parsed * 0.09290304
    # An explicit but unknown unit must not silently become m².
    return None


def _duration_value_seconds(value: Any, unit_value: Any) -> float | None:
    """Normalize a documented vacuum duration attribute to seconds."""
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return None
    unit = _normalized_signal(unit_value)
    if unit is None or unit in {"s", "sec", "second", "seconds"}:
        return parsed
    if unit in {"min", "minute", "minutes"}:
        return parsed * 60
    if unit in {"h", "hr", "hour", "hours"}:
        return parsed * 3600
    return None


def _intensity_rate_key(
    hass: HomeAssistant,
    entity_id: str | None,
    raw_value: Any,
    normalized_value: str | None,
) -> str | None:
    """Normalize select tokens and ranged number entities to rate bands.

    Ecovacs can expose ``water_amount`` as a model-specific number rather than
    a fixed select.  Home Assistant publishes the number's supported min/max
    on the entity, so the value can be placed in a low/medium/high band without
    assuming that every model uses the same numeric scale.
    """
    if not entity_id:
        return normalized_value
    state = hass.states.get(entity_id)
    if state is None:
        return normalized_value
    value = _float_or_none(raw_value)
    minimum = _float_or_none(state.attributes.get("min"))
    maximum = _float_or_none(state.attributes.get("max"))
    if (
        value is None
        or minimum is None
        or maximum is None
        or maximum <= minimum
    ):
        return normalized_value
    ratio = _clamp((value - minimum) / (maximum - minimum), 0, 1)
    if ratio <= 1 / 3:
        return "low"
    if ratio <= 2 / 3:
        return "medium"
    return "high"


def _water_anchor_states(
    hass: HomeAssistant,
    device: dict[str, Any],
    dock_error: str | None,
) -> dict[str, tuple[bool | None, str]]:
    """Classify only canonical machine states suitable for calibration.

    ``missing`` is never consumption, and unavailable signals remain unknown.
    Roborock's binary ``clean_box_empty`` is deliberately not interpreted here:
    it conflates out-of-water and box-not-installed and can pulse during an
    internal robot refill.  Enum ``empty`` (for example Valetudo MQTT) is safe.
    """
    result: dict[str, tuple[bool | None, str]] = {}

    shortage_entity = device.get("water_shortage_sensor")
    if shortage_entity:
        result["water_shortage"] = (
            _binary_active(_state_value(hass, shortage_entity)),
            "shortage",
        )

    clean_tank_entity = device.get("dock_clean_water_sensor")
    if clean_tank_entity:
        clean_tank = _normalized_signal(_state_value(hass, clean_tank_entity))
        if clean_tank == "empty":
            clean_state: bool | None = True
        elif clean_tank in {"ok", "full", "normal"}:
            clean_state = False
        else:
            clean_state = None
        result["dock_clean_water"] = (clean_state, "empty")

    if device.get("water_error_sensor"):
        water_error = _normalized_signal(
            _state_value(hass, device.get("water_error_sensor"))
        )
        if water_error in {
            "water_tank_empty",
            "clean_water_tank_empty",
            "clean_water_empty",
        }:
            water_error_state: bool | None = True
        elif water_error in {"ok", "no_error", "no_error_detected", "none"}:
            water_error_state = False
        else:
            water_error_state = None
        result["water_error"] = (water_error_state, "empty")

    if device.get("dock_error_sensor"):
        dock_error_kind = "empty"
        if dock_error == "water_shortage":
            # A shortage alarm is a low-water threshold, not proof that the
            # tracked reservoir is exactly empty.  It must use the same
            # debounce and plausibility checks as a binary shortage sensor.
            dock_error_state = True
            dock_error_kind = "shortage"
        elif dock_error in {
            "water_empty",
            "clean_water_empty",
            "clean_water_tank_empty",
            "water_tank_empty",
        }:
            dock_error_state: bool | None = True
        elif dock_error in {"ok", "none", "no_error", "no_error_detected"}:
            dock_error_state = False
        else:
            dock_error_state = None
        result["dock_error"] = (dock_error_state, dock_error_kind)

    return result


def _device_capacity_ml(device: dict[str, Any]) -> float | None:
    for key in ("tracked_capacity_ml", "water_total_ml", "tank_ml"):
        if (value := _positive_number(device.get(key))) is not None:
            return value
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _mapping_number(value: Any, key: str | None) -> float | None:
    """Read a rate only from an explicit mapping and its declared fallback."""
    if not isinstance(value, dict):
        return None
    if key is not None:
        for candidate in _rate_key_candidates(key):
            direct = _positive_number(value.get(candidate))
            if direct is not None:
                return direct
        if key in {"moderate_low", "medium_low"}:
            low = _positive_number(value.get("low"))
            medium = _positive_number(value.get("medium"))
            if low is not None and medium is not None:
                return (low + medium) / 2
        if key in {"moderate_high", "medium_high"}:
            medium = _positive_number(value.get("medium"))
            high = _positive_number(value.get("high"))
            if medium is not None and high is not None:
                return (medium + high) / 2
    return _positive_number(value.get("default"))


def _rate_key_candidates(key: str) -> tuple[str, ...]:
    """Translate documented integration option tokens to model rate bands."""
    candidates = [key]
    groups = {
        "low": {"low", "light", "mild", "fast", "level_1", "standard_1"},
        "medium": {
            "medium",
            "moderate",
            "balanced",
            "standard",
            "normal",
            "level_2",
            "standard_2",
        },
        "high": {
            "high",
            "intense",
            "deep",
            "max",
            "maximum",
            "level_3",
            "standard_3",
        },
    }
    # Braava/Roomba exposes compound tokens such as ``Standard-2`` or
    # ``Deep-3``.  The suffix is the spray amount, while the prefix describes
    # the cleaning pattern.  Water accounting must therefore select its band
    # from the suffix regardless of the pattern name.
    spray_suffix = re.search(r"(?:^|_)([123])$", key)
    if spray_suffix:
        candidates.append({"1": "low", "2": "medium", "3": "high"}[spray_suffix.group(1)])
    for canonical, aliases in groups.items():
        if key in aliases:
            candidates.extend((canonical, *sorted(aliases)))
            break
    return tuple(dict.fromkeys(candidates))


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
