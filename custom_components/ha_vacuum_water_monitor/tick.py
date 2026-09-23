"""Server-side water accounting for Vacuum Water Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from copy import deepcopy
import hashlib
import json
import re
from typing import Any
import unicodedata

from homeassistant.core import HomeAssistant

from .sensor_calculations import apply_custom_calibration
from .storage import VacuumWaterStorage
from .profiles import resolve_consumption_profile, CONSUMPTION_SETTINGS, _compatible_context
from . import profiles as consumption_profiles
from . import accounting_v2
from . import estimation
from .refill import apply_refill

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
# A mop-wash sequence can pass through non-wash transit states (docking,
# returning_home) between going_to_wash_the_mop and washing_the_mop.  It ends
# when the robot resumes cleaning or after this quiet period.
WASH_SEQUENCE_GAP_SECONDS = 240
# Area change across an observation gap below this is counter noise, not a session.
GAP_AREA_TOLERANCE_M2 = 0.5
_PASS_REASONS_KEY = "_pass_reasons"
# Reasons that prove water was dispensed without an applicable rate.
_MISSING_RATE_REASONS = frozenset({"missing_area_rate", "missing_time_rate", "missing_intensity_factor"})
# Reasons that only mean an exposure baseline was lost; they make the balance
# incomplete only when water could have been dispensed in that interval.
_GAP_REASONS = frozenset({"area_gap", "active_time_gap", "area_reset", "area_anomaly"})
_DOCK_OK_STATES = frozenset({"ok", "none", "no_error", "no_error_detected"})
_SESSION_END_STATES = frozenset({"docked", "idle", "charging", "completed", "charging_complete"})
_ANCHOR_SOURCE_SCOPE = {"dock_error": "dock_clean", "dock_clean_water": "dock_clean"}
# Changing any of these makes a learned device scale meaningless.
_CALIBRATION_IDENTITY_KEYS = (
    "profile_key", "model_id", "integration_adapter", "tracked_reservoir", "tracked_capacity_ml",
    "rate_signal", "usage_ml_per_m2", "usage_ml_per_active_minute", "wash_volume_ml",
    "calibration_scope",
)
DEFAULT_AREA_ANOMALY_CEILING_M2 = 25
RESET_COOLDOWN_SEC = 60
# An observation gap this short, with the same mop settings on both sides and a
# continuous cumulative area counter, is bridged instead of invalidating the tank.
BRIDGE_GAP_MAX_SECONDS = 300
AREA_COUNTER_JITTER_M2 = 0.05
# A gap longer than a mop wash sequence is bridged only when the cleaned area
# kept pace with the robot's recent cleaning rate, so a hidden wash (no area,
# 150 ml of water) is not silently skipped.
BRIDGE_UNCHECKED_SECONDS = 60
BRIDGE_MIN_AREA_PACE = 0.8
AREA_RATE_SMOOTHING = 0.3
# Two refill reports this close together describe one physical refill (a lid
# closed after the dock already cleared, a button pressed as confirmation).
USER_REFILL_DEDUPE_SECONDS = 600
# An empty error first seen this soon after a refill the user reported is the
# error that preceded that refill, not a tank emptied in minutes.
REFILL_ACK_WINDOW_SECONDS = 600
# A dock that reports empty during a wash could not finish it. Half of that
# wash is the expected water it still drew.
FAILED_WASH_WINDOW_SECONDS = 300
FAILED_WASH_REFUND_FRACTION = 0.5
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

# Water-output levels that mean no water is dispensed.  MIoT models publish
# this as an enum ("Close" on several Xiaomi devices) or as level 0.
_MOP_INTENSITY_OFF = {
    "off",
    "0",
    "none",
    "close",
    "closed",
    "no_water",
}

# Documented level tokens that positively mean water is being dispensed.  An
# unrecognized token is never read as evidence: ``ha_xiaomi_home`` renders enum
# options from localized MIoT descriptions, so matching arbitrary text would
# turn a translated "off" into "mopping".
_MOP_INTENSITY_ON = {
    "low",
    "mild",
    "light",
    "medium",
    "moderate",
    "standard",
    "normal",
    "high",
    "intense",
    "strong",
    "max",
    "maximum",
    "ultrahigh",
    "ultra_high",
    "custom",
}


def _intensity_water_state(value: str | None) -> bool | None:
    """Return True when a level dispenses water, False for off, None if unknown.

    Numeric levels are authoritative; ``_normalized_signal`` turns ``0.0`` into
    ``0_0``, so the decimal form is restored before parsing.
    """
    if value is None or value == "":
        return None
    numeric = _float_or_none(value.replace("_", ".") if "_" in value else value)
    if numeric is not None:
        return numeric > 0
    if value in _MOP_INTENSITY_OFF:
        return False
    if value in _MOP_INTENSITY_ON:
        return True
    return None


async def async_tick_water_state(
    hass: HomeAssistant,
    storage: VacuumWaterStorage,
    *,
    vacuum_entities: set[str] | None = None,
    delay_save_seconds: float | None = None,
    on_devices: Any = None,
) -> dict[str, dict[str, Any]]:
    """Tick known vacuums (all, or the given ones) and persist changed states."""
    stored = await storage.async_get_state()
    devices = _devices_to_tick(hass, stored["settings"], stored["tank_states"])
    if callable(on_devices):
        on_devices(devices)
    previous = stored["tank_states"]
    changed: dict[str, dict[str, Any]] = {}
    expected_reset_ts: dict[str, Any] = {}
    substantive = False

    for device in devices:
        vacuum_entity = device.get("vacuum_entity")
        if not vacuum_entity:
            continue
        if vacuum_entities is not None and vacuum_entity not in vacuum_entities:
            continue
        # Respect user's pre-existing DIY automations: if the device config
        # points at an input_number/input_datetime for water tracking AND that
        # entity is registered in HA, the user already has automation/template
        # accounting in place. Skip our own tick to avoid double-counting.
        if _has_user_priv_helpers(hass, device):
            continue
        state = VacuumWaterStorage.default_tank_state()
        state.update(previous.get(vacuum_entity) or {})
        expected_reset_ts[vacuum_entity] = state.get("last_reset_ts")
        before = deepcopy(state)
        new_state, dirty = tick_device(hass, device, state)
        if dirty:
            changed[vacuum_entity] = new_state
            if not _only_tick_timestamp_changed(before, new_state):
                substantive = True

    if not changed:
        return changed
    # A refill recorded by this pass (button, lid, dock) is written at once.
    refilled = any(state.get("last_reset_ts") != expected_reset_ts.get(vacuum) for vacuum, state in changed.items())
    # An idle heartbeat changes only last_tick_ts: keep it in memory instead of
    # rewriting the whole Store every minute.
    written = await storage.async_set_tank_states(
        changed, expected_reset_ts=expected_reset_ts, delay_seconds=None if refilled else delay_save_seconds,
        persist=substantive or refilled)
    return written if isinstance(written, dict) else changed


def _only_tick_timestamp_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = (set(before) | set(after)) - {"last_tick_ts", _PASS_REASONS_KEY}
    return all(before.get(key) == after.get(key) for key in keys)


def _digest(values: Any) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def tick_device(
    hass: HomeAssistant,
    device: dict[str, Any],
    state: dict[str, Any],
    *,
    now_ts: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Run one accounting pass and strip pass-local bookkeeping from the result."""
    new_state, dirty = _tick_device_pass(hass, device, state, now_ts=now_ts)
    new_state.pop(_PASS_REASONS_KEY, None)
    return new_state, dirty


def _tick_device_pass(
    hass: HomeAssistant,
    device: dict[str, Any],
    state: dict[str, Any],
    *,
    now_ts: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Translate one v4 `_tickWaterState` pass into Python."""
    state = dict(state)
    state[_PASS_REASONS_KEY] = []
    if now_ts is None:
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    # A refill the user reports through a bound button or tank-lid sensor is
    # independent of the robot being reachable or the dock's own signals.
    user_refill_dirty = False
    user_refill_source = _observe_user_refill_signals(hass, device, state)
    if user_refill_source is not None:
        user_refill_dirty = True
        if (now_ts - int(state.get("last_reset_ts") or 0)) / 1000 > USER_REFILL_DEDUPE_SECONDS:
            apply_refill(state, now_ts, user_refill_source, rebaseline=False)
            _record_accounting(state, "refill", None, None, f"refill_{user_refill_source}")
        else:
            _record_accounting(state, "refill", None, None, "refill_already_recorded")
    vacuum_entity = device.get("vacuum_entity")
    vac = hass.states.get(vacuum_entity) if vacuum_entity else None
    event_sensor = device.get("accounting_event_sensor")
    if event_sensor or state.get("accounting_v2"):
        event_state = hass.states.get(event_sensor) if isinstance(event_sensor, str) and event_sensor.startswith("sensor.") else None
        stream = None
        if (vac is not None and _normalized_signal(vac.state) is not None
                and event_state is not None and _normalized_signal(event_state.state) is not None):
            stream = event_state.attributes.get("accounting_stream")
        state["accounting_v2"] = accounting_v2.consume_dataset_live(
            state.get("accounting_v2"), stream,
            contracts=accounting_v2.SOURCE_CONTRACTS,
            source_bindings=accounting_v2.SOURCE_BINDINGS,
            source_entity=event_sensor,
            now_ms=now_ts)
    if vac is None or _normalized_signal(vac.state) in {None, "unknown", "unavailable"}:
        _open_observation_gap(state, int(_positive_number(state.get("last_tick_ts")) or now_ts))
        # The last area is kept so that a change observed after the gap proves
        # unobserved exposure (or bridges it) instead of silently starting a new baseline.
        state.update(last_duration_seconds=None, last_tick_ts=0,
                     area_gap=True, duration_gap=True, last_water_volume_ml=None, session_exposure_complete=False,
                     verified_wash_active=False, last_completed_wash_count=None)
        state["reservoir_levels"] = {key: {"volume_ml": None, "source": "unknown", "reason": "vacuum_unavailable"}
                                     for key in ("dock_clean", "dock_dirty", "robot_clean", "robot_dirty", "detergent")}
        state["consumption_resolution"] = {"source": "unknown", "reason": "vacuum_unavailable", "profile_id": None}
        _record_accounting(state, "unknown", None, None, "vacuum_unavailable")
        return state, True

    dirty = bool(event_sensor or state.get("accounting_v2")) or user_refill_dirty
    levels = _read_reservoir_levels(hass, device)
    if state.get("reservoir_levels") != levels:
        state["reservoir_levels"] = levels
        dirty = True
    status_sensor = device.get("status_sensor")
    status_state = hass.states.get(status_sensor) if status_sensor else None
    if status_sensor:
        curr_status_raw = status_state.state if status_state is not None else None
    else:
        curr_status_raw = vac.attributes.get("status") or vac.state
    curr_status = _normalized_signal(curr_status_raw)

    if status_sensor and _is_transient_status(curr_status):
        _open_observation_gap(state, int(_positive_number(state.get("last_tick_ts")) or now_ts))
        state.update(last_duration_seconds=None, area_gap=True,
                     duration_gap=True, last_tick_ts=0, last_water_volume_ml=None, session_exposure_complete=False,
                     verified_wash_active=False, last_completed_wash_count=None)
        _record_accounting(state, "unknown", None, None, "status_unavailable")
        return state, True

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
        mop_intensity=mop_intensity,
        intensity_is_evidence=bool(device.get("mop_intensity_is_evidence")),
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
    intensity_map = device.get("intensity_factor")
    unmapped_intensity = (
        mop_intensity
        if isinstance(intensity_map, dict) and mop_intensity is not None
        and mop_intensity not in _MOP_INTENSITY_OFF
        and not any(_positive_number(intensity_map.get(key)) is not None for key in _rate_key_candidates(mop_intensity))
        else None
    )
    if state.get("intensity_unmapped") != unmapped_intensity:
        state["intensity_unmapped"] = unmapped_intensity
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
    # A whole-cycle dose already includes dock washes. Separate wash dosing is
    # permitted only when the user confirms the floor dose excludes washes.
    wash_covered_by_cycle_rate = False
    if (usage_per_m2 is not None or usage_per_minute is not None) and device.get("calibration_scope") != "floor_only":
        wash_covered_by_cycle_rate = True
        wash_volume = None

    evidence = device.get("accounting_evidence")
    time_evidence = device.get("time_accounting_evidence") or evidence
    if int(state.get("calibration_samples") or 0) > 0:
        evidence = "device_calibrated"
        time_evidence = "device_calibrated"

    last_tick = _positive_number(state.get("last_tick_ts"))
    if last_tick is not None and (now_ts < last_tick or now_ts - last_tick > MAX_ACTIVE_INTERVAL_SECONDS * 1000):
        _open_observation_gap(state, min(last_tick, now_ts))
        state.update(last_duration_seconds=None, area_gap=True,
                     duration_gap=True, last_water_volume_ml=None, session_exposure_complete=False,
                     verified_wash_active=False, last_completed_wash_count=None)
    if curr_area is None and device.get("area_sensor"):
        _open_observation_gap(state, int(last_tick or now_ts))

    # A short gap with the same settings and a continuous area counter keeps the
    # tank complete: the cumulative counter still carries the cleaned area.
    bridge_area = False
    rate_settings = {"cleaning_mode": cleaning_mode, "mop_mode": mop_mode, "mop_intensity": mop_intensity}
    gap_started = _positive_number(state.get("gap_started_ts"))
    if gap_started is not None and (curr_area is not None or not device.get("area_sensor")):
        gap_exposure = bool(state.get("gap_exposure_possible"))
        last_area_seen = _float_or_none(state.get("last_area"))
        ceiling_m2 = _positive_number(device.get("area_anomaly_ceiling_m2")) or DEFAULT_AREA_ANOMALY_CEILING_M2
        continuous = (curr_area is not None and last_area_seen is not None
                      and -AREA_COUNTER_JITTER_M2 <= curr_area - last_area_seen <= ceiling_m2)
        gap_seconds = (now_ts - gap_started) / 1000
        area_rate = _positive_number(state.get("area_rate_m2_per_s"))
        kept_pace = gap_seconds <= BRIDGE_UNCHECKED_SECONDS or (
            continuous and area_rate is not None
            and curr_area - last_area_seen > BRIDGE_MIN_AREA_PACE * area_rate * gap_seconds)
        if (gap_exposure and continuous and kept_pace and gap_seconds <= BRIDGE_GAP_MAX_SECONDS
                and state.get("last_rate_settings") == rate_settings):
            bridge_area = True
            state["bridged_gaps"] = int(state.get("bridged_gaps") or 0) + 1
            _record_accounting(state, "area", None, evidence, "gap_bridged")
        elif gap_exposure:
            state["accounting_incomplete"] = True
            state.update(session_accounting_valid=False, session_water_broken=True)
            _record_accounting(state, "unknown", None, None, "gap_not_bridged")
        state["gap_started_ts"] = None
        state["gap_exposure_possible"] = False
        dirty = True
    if curr_area is not None or not device.get("area_sensor"):
        state["last_rate_settings"] = rate_settings

    # Rates calibrated for one setting must not charge the interval spanning
    # a change to another mode/route/wash configuration. Only observed canonical
    # settings enter this fingerprint; area/time counters are exposures, not settings.
    live_settings = {"cleaning_mode": cleaning_mode, "mop_mode": mop_mode,
                     "water_level": mop_intensity}
    for role in ("route_entity", "passes_entity", "wash_mode_entity",
                 "wash_frequency_entity", "wash_temperature_entity",
                 "adaptive_mode_entity", "detergent_mode_entity",
                 "task_scope_entity", "suction_level_entity", "carpet_policy_entity"):
        if device.get(role):
            live_settings[role] = _normalized_signal(_state_value(hass, device[role]))
    consumption_context = deepcopy(device.get("consumption_context") or {
        "model_id": device.get("profile_key"), "sku": device.get("sku"),
        "dock_variant": device.get("dock_variant"), "firmware": device.get("firmware"),
        "integration_id": device.get("integration_adapter"),
        "integration_version": device.get("integration_version"),
        "reservoir": device.get("tracked_reservoir"), "action": "floor_mopping",
        "settings": dict.fromkeys(CONSUMPTION_SETTINGS),
    })
    if isinstance(consumption_context, dict) and device.get("observed_firmware") is not None:
        consumption_context["firmware"] = device["observed_firmware"]
    whole_cycle_calibration = None
    if isinstance(consumption_context, dict) and consumption_context:
        settings_context = consumption_context.setdefault("settings", {})
        if isinstance(settings_context, dict):
            for setting, role in (("mop_mode", "mop_mode_entity"),
                                  ("water_level", "mop_intensity_entity"),
                                  ("cleaning_mode", "cleaning_mode_entity")):
                if device.get(role):
                    settings_context[setting] = _normalized_signal(_state_value(hass, device[role]))
            for setting in CONSUMPTION_SETTINGS:
                if device.get(setting + "_entity"):
                    settings_context[setting] = _normalized_signal(_state_value(hass, device[setting + "_entity"]))
        consumption_context["device_id"] = vacuum_entity
        previous_area = _float_or_none(state.get("last_area"))
        previous_duration = _float_or_none(state.get("last_duration_seconds"))
        resolution = resolve_consumption_profile(
            consumption_context,
            {"area_m2": curr_area - previous_area if curr_area is not None and previous_area is not None else None,
             "time_minutes": (curr_duration_seconds - previous_duration) / 60
                 if curr_duration_seconds is not None and previous_duration is not None else None},
            device.get("consumption_calibration"),
        )
        reservoir_matches = not device.get("tracked_reservoir") or device["tracked_reservoir"] == consumption_context.get("reservoir")
        if not reservoir_matches:
            resolution = {**resolution, "source": "unknown", "method": None, "coefficient": None,
                          "scope": None, "reason": "context_reservoir_mismatch"}
        state["consumption_resolution"] = resolution
        personal = device.get("consumption_calibration")
        if isinstance(personal, list):
            matches = [r for r in personal if isinstance(r, dict) and r.get("device_id") == vacuum_entity
                       and _compatible_context(consumption_context, r.get("context", {}))]
            personal = matches[0] if len(matches) == 1 else None
        if (reservoir_matches and isinstance(personal, dict) and personal.get("scope") == "whole_cycle"
                and personal.get("device_id") == vacuum_entity
                and _compatible_context(consumption_context, personal.get("context", {}))):
            whole_cycle_calibration = personal
            usage_per_m2 = usage_per_minute = wash_volume = None
        # Legacy authored calibration remains authoritative. Shared model rates
        # are only used when no authored coefficient is already effective.
        if usage_per_m2 is None and usage_per_minute is None and wash_volume is None:
            if resolution.get("scope") == "floor_only":
                if resolution["method"] == "area":
                    usage_per_m2 = resolution["coefficient"]
                elif resolution["method"] == "time":
                    usage_per_minute = resolution["coefficient"]
                evidence = resolution["source"]
                time_evidence = evidence
                calibration_factor = 1
            elif resolution.get("source") not in {"unknown", "manufacturer_data"} and whole_cycle_calibration is None:
                state["consumption_resolution"] = {**resolution, "source": "unknown", "reason": "action_accounting_required"}
    else:
        consumption_context = None
    context_values = {key: device.get(key) for key in (
        "profile_key", "model_id", "integration_adapter", "tracked_reservoir", "tracked_capacity_ml",
        "firmware", "sw_version", "sku", "dock_variant", "integration_version",
        "area_sensor", "duration_sensor", "water_volume_sensor", "rate_signal",
        "usage_ml_per_m2", "usage_ml_per_active_minute", "wash_volume_ml", "calibration_scope", "water_volume_reservoir"
    )}
    context_values["live_settings"] = live_settings
    context_values["consumption_context"] = consumption_context
    context_values["consumption_calibration"] = device.get("consumption_calibration")
    context_values["dataset_revision"] = (consumption_profiles.CONSUMPTION_SNAPSHOT.get("dataset_version"), consumption_profiles.CONSUMPTION_SNAPSHOT.get("source_payload_sha256"))
    # The dataset revision identifies the shipped catalogue bytes. An upgrade
    # that does not change this device's rates must not break its baseline.
    interval_values = {key: value for key, value in context_values.items() if key != "dataset_revision"}
    context = _digest(interval_values)
    calibration_values = {key: device.get(key) for key in _CALIBRATION_IDENTITY_KEYS}
    calibration_values["intensity_factor"] = device.get("intensity_factor")
    calibration_context = _digest(calibration_values)
    old_interval_context = state.get("accounting_interval_context")
    old_calibration_context = state.get("accounting_calibration_context")
    state["accounting_context"] = _digest(context_values)
    state["accounting_interval_context"] = context
    state["accounting_calibration_context"] = calibration_context
    # 5.6 state has only the legacy hash; the first 5.7 pass adopts it silently.
    if old_interval_context is not None and old_interval_context != context:
        updates: dict[str, Any] = dict(
            last_area=curr_area, last_duration_seconds=curr_duration_seconds,
            last_tick_ts=now_ts, last_water_volume_ml=None, session_accounting_valid=False,
            session_exposure_complete=False, verified_wash_active=False, last_completed_wash_count=None)
        if old_calibration_context is not None and old_calibration_context != calibration_context:
            updates.update(calibration_factor=1, calibration_samples=0, calibration_log_factors=[])
        state.update(updates)
        _record_accounting(state, "unknown", None, None, "accounting_context_changed")
        return state, True


    session_running = _is_cleaning(vac_state, curr_status, cleaning_active)
    had_open_session = bool(state.get("session_start_ts"))
    completed_wash_resolution = None
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
    if (consumption_context and whole_cycle_calibration is None and wash_volume is None
            and not device.get("water_volume_sensor")
            and (not device.get("tracked_reservoir") or device["tracked_reservoir"] == consumption_context.get("reservoir"))):
        wash_context = deepcopy(consumption_context)
        wash_context["action"] = "mop_wash"
        wash_resolution = resolve_consumption_profile(wash_context, {"action_count": 1})
        if wash_resolution.get("scope") == "wash_only" and wash_resolution.get("method") == "action":
            # A phase ending or a command does not prove completion. A bound
            # completed-action counter must advance exactly once without a gap.
            completed = _float_or_none(_state_value(hass, device.get("wash_completed_sensor")))
            before_completed = _float_or_none(state.get("last_completed_wash_count"))
            state["last_completed_wash_count"] = completed
            actual_wash = wash_now and curr_status != "going_to_wash_the_mop"
            if (completed is not None and before_completed is not None
                    and completed >= 0 and completed.is_integer()
                    and completed - before_completed == 1 and state.get("verified_wash_active")):
                amount = wash_resolution["coefficient"]
                state["used_ml"] = round(_number(state.get("used_ml"), 0) + amount, 2)
                state["last_wash_charged_ts"] = now_ts
                state["last_wash_charged_ml"] = round(amount, 2)
                state["wash_resolution"] = wash_resolution
                completed_wash_resolution = wash_resolution
                state["verified_wash_active"] = False
                dirty = True
            if actual_wash and before_completed == completed and completed is not None:
                state["verified_wash_active"] = True
            if completed is None or (before_completed is not None and completed != before_completed):
                state["verified_wash_active"] = False
    if session_running and not state.get("session_start_ts"):
        state.update(session_start_ts=now_ts, session_start_used_ml=_number(state.get("used_ml"),0),
                     session_start_area=curr_area, session_accounting_valid=True, session_water_broken=False,
                     session_context=deepcopy(consumption_context),
                     session_resolution=deepcopy(state.get("consumption_resolution")),
                     session_exposure_complete=curr_area == 0, session_segments=1)
    if wash_now:
        state["last_wash_seen_ts"] = now_ts
        if wash_active:
            dirty |= _record_accounting(
                state, "wash", wash_volume, evidence, "wash_already_active"
            )
        elif previous_status is None:
            dirty |= _record_accounting(
                state, "wash", wash_volume, evidence, "wash_initial_observation"
            )
        elif wash_volume is None and wash_covered_by_cycle_rate:
            # A whole-cycle area/time rate already includes the dock washes.
            dirty |= _record_accounting(state, "wash", None, evidence, "wash_included_in_cycle_rate")
        elif wash_volume is None:
            if whole_cycle_calibration is None and curr_status != "going_to_wash_the_mop" and not state.get("verified_wash_active"):
                state["accounting_incomplete"] = True
            dirty |= _record_accounting(state, "wash", None, evidence, "missing_wash_rate")
        else:
            state["used_ml"] = round(_number(state.get("used_ml"), 0) + wash_volume, 2)
            state["last_wash_charged_ts"] = now_ts
            state["last_wash_charged_ml"] = round(wash_volume, 2)
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
            # A task flag (Roborock binary_sensor.*_cleaning) stays on while the
            # robot washes, empties the bin and flickers back to a wash state at
            # the dock. With a bound status signal only the status proves that
            # floor cleaning resumed.
            resumed = _is_cleaning(vac_state, curr_status, None if status_sensor else cleaning_active)
            quiet_ms = now_ts - int(state.get("last_wash_seen_ts") or 0)
            if resumed or quiet_ms > WASH_SEQUENCE_GAP_SECONDS * 1000:
                state["wash_sequence_active"] = False
                dirty = True

    # A configured real volume sensor is authoritative only for the explicitly
    # declared reservoir. Its missing samples never silently become estimates.
    real_sensor = bool(device.get("water_volume_sensor"))
    if real_sensor:
        state["used_ml"] = _number(state.get("used_ml"), 0) - (
            wash_volume if wash_now and not wash_active and previous_status is not None
            and wash_volume is not None else 0
        )
        volume_state = hass.states.get(device["water_volume_sensor"])
        volume = _float_or_none(volume_state.state) if volume_state else None
        unit = str(volume_state.attributes.get("unit_of_measurement", "")) if volume_state else ""
        capacity = _positive_number(device.get("tracked_capacity_ml"))
        reason = None
        if device.get("water_volume_reservoir") != device.get("tracked_reservoir") or not device.get("tracked_reservoir"):
            reason = "real_sensor_reservoir_unverified"
        elif volume is None:
            reason = "real_sensor_unavailable"
        elif unit not in {"mL", "ml", "L", "l"}:
            reason = "real_sensor_unit_unknown"
        else:
            volume *= 1000 if unit in {"L", "l"} else 1
            if volume < 0 or (capacity is not None and volume > capacity):
                reason = "real_sensor_out_of_range"
        previous_volume = _float_or_none(state.get("last_water_volume_ml"))
        if reason:
            state["last_water_volume_ml"] = None
        else:
            state["last_water_volume_ml"] = volume
            state["water_empty_active"] = volume == 0
            state["water_anchor_source"] = "real_sensor"
            state["water_anchor_kind"] = "empty" if volume == 0 else None
            state["water_anchor_confidence"] = "measured"
            state["last_dock_err"] = curr_dock_err
            if capacity is not None and volume == capacity and previous_volume is not None and previous_volume < volume:
                state["initialized"] = True
                state["last_reset_ts"] = now_ts
                state["last_reset_iso"] = datetime.fromtimestamp(now_ts / 1000, tz=timezone.utc).isoformat()
            if previous_volume is None:
                reason = "real_sensor_baseline"
            elif volume > previous_volume:
                state.update(session_accounting_valid=False, session_water_broken=True)
                reason = "real_sensor_refill_observed"
                # A rise proves added volume, not a completely full reservoir.
                state["used_ml"] = max(0, _number(state.get("used_ml"), 0) - (volume - previous_volume))
            else:
                state["used_ml"] = round(_number(state.get("used_ml"), 0) + previous_volume - volume, 2)
        state["consumption_resolution"] = {"source": "real_sensor", "method": "volume", "reason": reason, "profile_id": None}
        _record_accounting(state, "real_sensor", None, "measured_volume", reason)
        state.update(last_area=curr_area, last_duration_seconds=curr_duration_seconds,
                     last_status=curr_status, last_dock_status=curr_dock_status, last_tick_ts=now_ts)
        _finish_session(state, session_running, curr_status, now_ts, curr_area)
        return state, True

    last_area = _float_or_none(state.get("last_area"))
    if bridge_area:
        state["area_gap"] = False
    hold_area_baseline = False
    unobserved_exposure = False
    area_baseline: float | None = None
    if curr_area is None:
        state["session_exposure_complete"] = False
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
    elif state.get("area_gap") and not bridge_area:
        state["area_gap"] = False
        dirty = True
        moved = curr_area - last_area
        restarted_without_cleaning = moved < 0 and curr_area < AREA_MIN_DELTA
        if abs(moved) <= GAP_AREA_TOLERANCE_M2 or restarted_without_cleaning:
            dirty |= _record_accounting(state, "area", None, evidence, "area_gap_resumed")
        else:
            # The area changed while nothing was observed: water may have been
            # dispensed without a rate being applied.
            unobserved_exposure = True
            dirty |= _record_accounting(state, "area", None, evidence, "area_gap")
    else:
        delta = curr_area - last_area
        ceiling = _positive_number(device.get("area_anomaly_ceiling_m2")) or DEFAULT_AREA_ANOMALY_CEILING_M2
        previously_active = (_is_cleaning(None, state.get("last_status"), None)
                             or bool(state.get("wash_sequence_active")))
        if delta < 0 and not previously_active and not had_open_session:
            # Per-session counters (for example Roborock cleaning_area) restart
            # at zero when a new session starts: the area since restart is new.
            area_baseline = 0.0
            delta = curr_area
        last_area_ts = _positive_number(state.get("last_area_ts"))
        if (delta >= AREA_MIN_DELTA and not bridge_area and last_area_ts is not None
                and _is_cleaning(None, state.get("last_status"), None)
                and _is_cleaning(vac_state, curr_status, cleaning_active)):
            interval_seconds = (now_ts - last_area_ts) / 1000
            if 5 <= interval_seconds <= MAX_ACTIVE_INTERVAL_SECONDS:
                sample_rate = delta / interval_seconds
                previous_rate = _positive_number(state.get("area_rate_m2_per_s"))
                state["area_rate_m2_per_s"] = round(sample_rate if previous_rate is None else
                    (1 - AREA_RATE_SMOOTHING) * previous_rate + AREA_RATE_SMOOTHING * sample_rate, 6)
        if delta < 0:
            state["session_exposure_complete"] = False
            state.update(session_accounting_valid=False, session_water_broken=True)
            dirty |= _record_accounting(state, "area", None, evidence, "area_reset")
        elif delta > ceiling:
            state["session_exposure_complete"] = False
            state.update(session_accounting_valid=False, session_water_broken=True)
            dirty |= _record_accounting(state, "area", None, evidence, "area_anomaly")
        elif delta < AREA_MIN_DELTA and not math.isclose(
            delta, AREA_MIN_DELTA, rel_tol=0, abs_tol=1e-9
        ):
            # Keep the baseline so small increments accumulate instead of
            # being silently discarded.
            hold_area_baseline = True
            dirty |= _record_accounting(state, "area", None, evidence, "area_delta_below_minimum")
        elif not (_is_cleaning(vac_state, curr_status, cleaning_active)
                  or _is_cleaning(None, state.get("last_status"), None)):
            # Area only grows while cleaning. A tick that already sees the robot
            # heading to wash or dock still carries the area cleaned since the
            # previous observation, so it is charged when that one was cleaning.
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
    should_use_time = (curr_area is None or (usage_per_m2 is None and usage_per_minute is not None)) and not wash_now
    elapsed_seconds: float | None = None
    if should_use_time and curr_duration_seconds is not None:
        if last_duration_seconds is None or state.get("duration_gap"):
            dirty |= _record_accounting(
                state,
                "active_time",
                None,
                time_evidence,
                "duration_baseline_initialized",
            )
        else:
            elapsed_seconds = curr_duration_seconds - last_duration_seconds
    elif should_use_time and not (device.get("duration_sensor") or device.get("duration_attribute")) and previous_tick_ts is not None:
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

    if device.get("duration_sensor") or device.get("duration_attribute"):
        state["duration_gap"] = curr_duration_seconds is None
        if should_use_time and curr_duration_seconds is None:
            dirty |= _record_accounting(state, "active_time", None, time_evidence, "duration_unavailable")

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
    exact_empty_reset = False
    if (
        state.get("last_dock_err") == "water_empty"
        and curr_dock_err in _DOCK_OK_STATES
    ):
        do_reset = True
        exact_empty_reset = True

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
    if active_anchor is not None:
        reservoir = device.get("tracked_reservoir")
        declared_reservoir = device.get("water_anchor_reservoir")
        # An inferred anchor reservoir only covers signals scoped to that
        # reservoir (a dock error for the dock tank); a robot-side error needs
        # an explicitly configured contract.
        inferred_scope_mismatch = bool(device.get("water_anchor_reservoir_inferred")) and (
            _ANCHOR_SOURCE_SCOPE.get(active_anchor[0]) != reservoir)
        if not reservoir or declared_reservoir != reservoir or inferred_scope_mismatch:
            _record_accounting(state, "unknown", None, None, "water_anchor_reservoir_unverified")
            active_anchor = None
        elif active_anchor[1] == "shortage" and device.get("low_water_anchor_remaining_percent") is None:
            _record_accounting(state, "unknown", None, None, "shortage_volume_unmeasured")
            active_anchor = None
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

    reset_ts = int(state.get("last_reset_ts") or 0)
    late_error_after_user_refill = (
        water_empty_now and not water_empty_before
        and state.get("last_reset_source") in {"card", "service", "button", "lid"}
        and 0 <= now_ts - reset_ts <= REFILL_ACK_WINDOW_SECONDS * 1000
        # Nothing was cleaned since: the robot has not used this tank yet.
        and _number(state.get("used_ml"), 0) < (_device_capacity_ml(device) or 0) * MIN_CALIBRATION_USAGE_FRACTION
    )
    if late_error_after_user_refill:
        # The dock reported the empty tank the user has just refilled.
        state["water_empty_active"] = True
        state["water_empty_acknowledged"] = True
        state["water_anchor_source"], state["water_anchor_kind"] = active_anchor
        water_empty_before = True
        dirty = True
        dirty |= _record_accounting(state, "low_water", None, evidence, "empty_error_already_refilled")
    if water_empty_now and not water_empty_before:
        assert active_anchor is not None
        anchor_source, anchor_kind = active_anchor
        refilled_since_last_anchor = int(state.get("last_empty_anchor_ts") or 0) <= reset_ts
        state["last_empty_anchor_ts"] = now_ts
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
        wash_refund = 0.0
        charged_ts = _positive_number(state.get("last_wash_charged_ts"))
        if (anchor_kind == "empty" and charged_ts is not None
                and 0 <= now_ts - charged_ts <= FAILED_WASH_WINDOW_SECONDS * 1000):
            wash_refund = _number(state.get("last_wash_charged_ml"), 0) * FAILED_WASH_REFUND_FRACTION
            state["last_wash_charged_ts"] = 0
        predicted_used = _positive_number(_number(state.get("used_ml"), 0) - wash_refund)
        initialized = bool(state.get("initialized") or state.get("last_reset_iso"))
        if capacity is not None and initialized:
            remaining_percent = (
                _empty_residual_percent(device)
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
            cycle_long_enough = (
                predicted_used is not None
                and predicted_used >= capacity * max(
                    MIN_CALIBRATION_USAGE_FRACTION, estimation.MIN_CALIBRATION_CYCLE_FRACTION)
            )
            if cycle_long_enough and not refilled_since_last_anchor:
                # The dock reported empty again without a refill in between (an
                # error that flickered while automatic refill is off): one tank.
                _append_calibration_history(state, now_ts, predicted_used, calibration_target,
                                            calibration_factor, False, "calibration_sample_no_refill_since_empty", wash_refund)
                state["used_ml"] = round(calibration_target, 2)
                dirty |= _record_accounting(state, "low_water", None, evidence,
                                            "calibration_sample_no_refill_since_empty")
            elif cycle_long_enough and state.get("accounting_incomplete"):
                # Water was dispensed while a signal was missing: the tank's
                # prediction is not a fair sample, but the anchor still applies.
                _append_calibration_history(state, now_ts, predicted_used, calibration_target,
                                            calibration_factor, False, "calibration_sample_incomplete_cycle", wash_refund)
                state["used_ml"] = round(calibration_target, 2)
                dirty |= _record_accounting(state, "low_water", None, evidence,
                                            "calibration_sample_incomplete_cycle")
            elif cycle_long_enough:
                assert predicted_used is not None
                log_factors = estimation.seed_log_factors(state)
                observed_factor = _clamp(
                    calibration_factor * calibration_target / predicted_used,
                    MIN_CALIBRATION_FACTOR,
                    MAX_CALIBRATION_FACTOR,
                )
                pending = _float_or_none(state.get("calibration_pending_log_factor"))
                window, learned_factor, accepted, rejection, pending = estimation.update_calibration(
                    log_factors, observed_factor,
                    band_fraction=estimation.band_fraction(device.get("estimate_basis"), device.get("uncertainty_percent")),
                    pending=pending)
                state["calibration_pending_log_factor"] = round(pending, 6) if pending is not None else None
                _append_calibration_history(state, now_ts, predicted_used, calibration_target,
                                            calibration_factor, accepted, rejection, wash_refund)
                state["calibration_log_factors"] = [round(value, 6) for value in window]
                state["calibration_factor"] = round(
                    _clamp(learned_factor, MIN_CALIBRATION_FACTOR, MAX_CALIBRATION_FACTOR), 4)
                state["calibration_samples"] = len(window)
                state["last_calibration_predicted_ml"] = round(predicted_used, 2)
                state["last_calibration_target_ml"] = round(calibration_target, 2)
                state["used_ml"] = round(calibration_target, 2)
                dirty |= _record_accounting(
                    state,
                    "low_water",
                    state["calibration_factor"],
                    "device_calibrated",
                    "low_water_calibrated" if accepted else rejection,
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
        cleared = False
        if previous_anchor_source in water_anchor_states:
            cleared = water_anchor_states[previous_anchor_source][0] is False
        elif len(water_anchor_states) == 1:
            # Additive migration for v5.2 records written before anchor source
            # was persisted.  Unknown/unavailable never counts as a refill.
            cleared = next(iter(water_anchor_states.values()))[0] is False
        if cleared:
            do_reset = True
            exact_empty_reset = exact_empty_reset or state.get("water_anchor_kind") == "empty"

    # Clearing an empty/shortage alarm does not by itself prove a full refill.
    # An exact empty that clears is a refill when the user keeps automatic
    # refill on (default for an inferred dock contract); a threshold alarm needs
    # an explicitly authored contract. A refill the user already reported while
    # the error was showing is not repeated when the error clears.
    if do_reset and state.get("water_empty_acknowledged"):
        do_reset = False
        state["water_empty_active"] = False
        state["water_empty_acknowledged"] = False
        dirty = True
        dirty |= _record_accounting(state, "refill", None, evidence, "refill_already_recorded")
    elif do_reset:
        auto_preference = device.get("refill_on_dock_clear")
        contract = bool(device.get("refill_on_clear", False))
        if auto_preference is False:
            refill_allowed = False
        elif exact_empty_reset:
            refill_allowed = True if auto_preference is True else contract
        else:
            refill_allowed = contract and not device.get("refill_on_clear_inferred")
        if not refill_allowed:
            do_reset = False
            if state.get("water_empty_active"):
                # The empty condition ended; the tank stays at its anchor until
                # the user reports the refill.
                state["water_empty_active"] = False
                dirty = True
            dirty |= _record_accounting(state, "refill", None, evidence, "refill_volume_unmeasured")

    if do_reset and cooldown_ok:
        apply_refill(state, now_ts, "dock_cleared", rebaseline=False)
        dirty = True
        dirty |= _record_accounting(state, "refill", None, evidence, "refill_detected")

    if state.get("last_status") != curr_status:
        state["last_status"] = curr_status
        dirty = True
    if curr_area is not None:
        next_area = curr_area
        if hold_area_baseline:
            next_area = area_baseline if area_baseline is not None else last_area
        if state.get("last_area") != next_area:
            state["last_area"] = next_area
            state["last_area_ts"] = now_ts
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
        dirty = True
    if state.get("last_tick_ts") != now_ts:
        state["last_tick_ts"] = now_ts
        dirty = True

    if whole_cycle_calibration is not None:
        _record_accounting(state, "whole_cycle", None, "device_calibration", "whole_cycle_pending")
        if (not session_running and not wash_now and curr_status in _SESSION_END_STATES
                and state.get("session_start_ts")):
            exposure = curr_area - state.get("session_start_area", 0) if curr_area is not None and state.get("session_start_area") is not None else None
            resolution = resolve_consumption_profile(consumption_context, {"area_m2": exposure}, whole_cycle_calibration)
            state["consumption_resolution"] = resolution
            if (state.get("session_exposure_complete") and state.get("session_accounting_valid")
                    and resolution.get("source") == "device_calibration" and resolution.get("method") == "area"):
                state["used_ml"] = round(_number(state.get("used_ml"), 0) + exposure * resolution["coefficient"], 2)
                state["session_resolution"] = deepcopy(resolution)
                _record_accounting(state, "whole_cycle", resolution["coefficient"], "device_calibration", None)
            else:
                state.update(session_accounting_valid=False, session_water_broken=True)
                state["accounting_incomplete"] = True
                _record_accounting(state, "unknown", None, None, resolution.get("reason") or "incomplete_cycle")
        dirty = True
    pass_reasons = set(state.get(_PASS_REASONS_KEY) or ())
    exposure_possible = bool(session_running or wash_now or state.get("session_start_ts")
                             or state.get("verified_wash_active"))
    if (unobserved_exposure or pass_reasons & _MISSING_RATE_REASONS
            or (exposure_possible and pass_reasons & _GAP_REASONS)):
        state["accounting_incomplete"] = True
    if completed_wash_resolution is not None:
        state["consumption_resolution"] = deepcopy(completed_wash_resolution)
        _record_accounting(state, "wash", completed_wash_resolution["coefficient"],
                           completed_wash_resolution["source"], None)
    _finish_session(state, session_running or wash_now, curr_status, now_ts, curr_area)
    return state, dirty


def _empty_residual_percent(device: dict[str, Any]) -> float:
    """Water a dock cannot draw when it reports empty.

    Only a labelled estimate closes a tank below full capacity: the pump intake
    leaves a small unusable residual (benchmarked default 5%). An authored or
    measured contract keeps its exact empty semantics.
    """
    explicit = _float_or_none(device.get("empty_residual_percent"))
    if explicit is not None:
        return _clamp(explicit, 0, 20)
    if device.get("estimate_basis") and device.get("water_anchor_reservoir_inferred"):
        return estimation.DEFAULT_EMPTY_RESIDUAL_PERCENT
    return 0.0


def _append_calibration_history(state, now_ts, predicted, target, factor_before, accepted, reason, wash_refund=0.0):
    """Keep a prequential record: the prediction was made before learning from this tank."""
    error = (predicted - target) / target * 100 if target else None
    record = {"ts": now_ts, "predicted_ml": round(predicted, 1), "target_ml": round(target, 1),
              "error_percent": round(error, 1) if error is not None else None,
              "factor_before": round(factor_before, 4), "accepted": bool(accepted), "reason": reason}
    if wash_refund:
        record["failed_wash_refund_ml"] = round(wash_refund, 1)
    state["calibration_history"] = [record, *(state.get("calibration_history") or [])][:12]


def _read_reservoir_levels(hass, device):
    """Read distinct physical quantities; a transfer is not system consumption."""
    bindings = device.get("reservoir_volume_sensors")
    bindings = bindings if isinstance(bindings, dict) else {}
    capacities = device.get("reservoirs_ml")
    capacities = capacities if isinstance(capacities, dict) else {}
    result = {}
    for reservoir in ("dock_clean", "dock_dirty", "robot_clean", "robot_dirty", "detergent"):
        entity = bindings.get(reservoir)
        reason, volume = "volume_sensor_unbound", None
        if isinstance(entity, str) and entity:
            if not entity.startswith("sensor."):
                reason = "volume_sensor_domain_invalid"
            elif list(bindings.values()).count(entity) > 1:
                reason = "ambiguous_reservoir_binding"
            else:
                sample = hass.states.get(entity)
                volume = _float_or_none(sample.state) if sample else None
                unit = sample.attributes.get("unit_of_measurement") if sample else None
                reason = None
                if volume is None:
                    reason = "volume_sensor_unavailable"
                elif unit not in {"ml", "mL", "l", "L"}:
                    reason = "volume_unit_unknown"
                else:
                    volume *= 1000 if unit in {"l", "L"} else 1
                    capacity = _positive_number(capacities.get(reservoir))
                    if volume < 0 or (capacity is not None and volume > capacity):
                        reason = "volume_out_of_range"
        result[reservoir] = {"volume_ml": volume if reason is None else None,
                             "source": "physical_sensor" if reason is None else "unknown", "reason": reason}
    return result


def _finish_session(state, running, status, now_ts, area):
    """Persist a bounded automatic history, keeping unknown water as null."""
    start = state.get("session_start_ts")
    if not start:
        return
    reason = str(state.get("last_accounting_reason") or "")
    if reason.startswith("missing_") or "unavailable" in reason or reason.endswith("gap"):
        state.update(session_accounting_valid=False, session_water_broken=True)
    if running or status not in _SESSION_END_STATES:
        return
    measured = state.get("last_accounting_evidence") in {"measured_volume", "user_calibration", "explicit_user_configuration", "device_calibrated", "verified_model", "device_calibration", estimation.LABELED_ESTIMATE}
    measured = measured or (state.get("session_resolution") or {}).get("source") in {"verified_model", "device_calibration"}
    # accounting_valid marks a clean measurement (one context, no refill) for
    # calibration and sharing. The history keeps the water of any run whose
    # counting was never broken, including one that changed settings or was
    # refilled midway (5.7.0-beta.3).
    counted = state.get("session_accounting_valid") or not state.get("session_water_broken", True)
    water = max(0, _number(state.get("used_ml"),0)-_number(state.get("session_start_used_ml"),0)) if measured and counted else None
    first_area = _float_or_none(state.get("session_start_area"))
    record = {"ts": now_ts, "started_ts": start, "type": "automatic", "water": water,
              "area": max(0,area-first_area) if area is not None and first_area is not None else None,
              "duration": round(max(0,now_ts-start)/60000,1), "method":state.get("last_accounting_source"),
              "evidence":state.get("last_accounting_evidence"),
              "context": deepcopy(state.get("session_context")),
              "resolution": deepcopy(state.get("session_resolution")),
              "accounting_valid": bool(state.get("session_accounting_valid")),
              "exposure_complete": bool(state.get("session_exposure_complete")),
              "segments": state.get("session_segments", 1)}
    state["automatic_sessions"] = [record, *(state.get("automatic_sessions") or [])][:50]
    state["session_start_ts"] = None


def list_vacuums(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return enriched, registry-backed vacuum descriptors for the card."""
    from .discovery import descriptors_from_hass

    return descriptors_from_hass(hass)


def _devices_to_tick(
    hass: HomeAssistant, settings: dict[str, Any], tank_states: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    from .sensor_calculations import build_vacuum_devices

    devices = build_vacuum_devices(settings, tank_states or {}, list_vacuums(hass))
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
    mop_intensity: str | None = None,
    intensity_is_evidence: bool = False,
    require_evidence: bool = False,
) -> bool:
    if mop_attached is False or water_box_attached is False:
        return False
    # An explicit no-water level (for example Roborock water_box_mode "off" in
    # vacuum-only runs) means no water reaches the floor for any integration.
    if mop_intensity in _MOP_INTENSITY_OFF:
        return False
    # Only integrations whose adapter declares the level to be a genuine
    # water-output control take part in this rule.  Several adapters bind
    # ``mop_intensity`` to something else entirely — Roomba maps it to
    # ``fan_speed`` — and Ecovacs' ``water_amount`` has no "off" option at all,
    # so reading either as proof of mopping would bill plain vacuuming as water.
    water_state = (
        _intensity_water_state(mop_intensity) if intensity_is_evidence else None
    )
    # A water-output level of zero means no water reaches the floor, so it
    # ends mopping regardless of any mode label.
    if water_state is False:
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
    # Several MIoT integrations (Xiaomi H50/H50 Pro via xiaomi_home) expose a
    # water-output level but no mop-mode or attachment entity.  A recognized
    # non-zero level is direct evidence that water is being dispensed, and
    # without it these vacuums fail the evidence gate forever and never accrue
    # usage.  An unrecognized (possibly localized) token proves nothing.
    if water_state is True:
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


def _open_observation_gap(state: dict[str, Any], started_ts: int) -> None:
    """Remember when observation stopped and whether water could flow meanwhile."""
    exposure = bool(state.get("session_start_ts") or state.get("verified_wash_active")
                    or state.get("wash_sequence_active"))
    if not _positive_number(state.get("gap_started_ts")):
        state["gap_started_ts"] = started_ts
    state["gap_exposure_possible"] = bool(state.get("gap_exposure_possible")) or exposure


def _observe_user_refill_signals(
    hass: HomeAssistant, device: dict[str, Any], state: dict[str, Any]
) -> str | None:
    """Return ``button`` or ``lid`` when the user reported a refill this pass.

    ``input_button``/``button`` states are the last press time: a press is a
    newer time than the last one seen on the same entity. A lid sensor counts
    when it closes (``on`` → ``off``). Binding another entity, an unavailable
    reading, or a restored older press time never counts as a refill.
    """
    source = None
    button = device.get("refill_button_entity")
    if isinstance(button, str) and button:
        raw = _state_value(hass, button)
        if raw is not None and raw != "unavailable":
            previous = state.get("last_refill_button_state")
            same_entity = state.get("last_refill_button_entity") == button
            if same_entity and previous is not None and raw != previous and raw != "unknown":
                newer = _press_is_newer(raw, previous)
                if newer is not False:
                    source = "button"
                if newer is False:
                    raw = previous  # keep the newest press seen
            state["last_refill_button_state"] = raw
            state["last_refill_button_entity"] = button
    lid = device.get("reset_door_sensor")
    if isinstance(lid, str) and lid:
        current = _normalized_signal(_state_value(hass, lid))
        if current in {"on", "off"}:
            same_lid = state.get("last_door_entity") in {None, lid}
            if same_lid and state.get("last_door") == "on" and current == "off":
                source = source or "lid"
            state["last_door"] = current
            state["last_door_entity"] = lid
    return source


def _press_is_newer(raw: str, previous: str) -> bool | None:
    """Compare two press timestamps; None when either is not a timestamp."""
    try:
        current_time = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        previous_time = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
    except ValueError:
        return None
    if (current_time.tzinfo is None) != (previous_time.tzinfo is None):
        return None
    return current_time > previous_time


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
        "low": {"low", "light", "mild", "slight", "min", "fast", "level_1", "standard_1"},
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
            "extreme",
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
    reasons = state.get(_PASS_REASONS_KEY)
    if isinstance(reasons, list) and reason:
        reasons.append(reason)
    changed = False
    for key, value in payload.items():
        if state.get(key) != value:
            state[key] = value
            changed = True
    return changed
