"""Collect independent, continuous floor and completed-wash exposures."""
from copy import deepcopy
import json
import uuid

# Persisted observations must not bridge a Home Assistant process restart.
_EPOCH = uuid.uuid4().hex
QUALITY = {"boundaries_confirmed": True, "uninterrupted": True,
           "exposure_complete": True, "settings_constant": True,
           "same_reservoir": True, "intervening_refill": False,
           "unmeasured_transfer": False}


def identity(device, context, settings):
    """Use concrete binding and observed action controls; unknown is not a value."""
    context = context or {}
    robot = device.get("measurement_identity") or device.get("vacuum_entity")
    station = context.get("dock_variant")
    common = {k: context.get(k) for k in ("firmware", "integration_id", "integration_version")}
    declared = context.get("settings") or {}
    floor = {}
    for key, role in (("cleaning_mode", "cleaning_mode_entity"), ("mop_mode", "mop_mode_entity"),
                      ("water_level", "mop_intensity_entity")):
        bound = device.get(role) or (key == "water_level" and device.get("mop_intensity_attribute"))
        floor[key] = settings.get(key) if bound else (settings.get(key) or declared.get(key))
    wash = {k: v for k, v in settings.items() if k.startswith("wash_")}
    for key in ("wash_mode", "wash_frequency", "wash_temperature"):
        if key + "_entity" not in wash and declared.get(key):
            wash[key + "_entity"] = declared[key]
    observed = settings.get("observed_settings") or {}
    if (not robot or not station or not all(common.values()) or not all(floor.values())
            or not wash or not all(wash.values()) or any(v.get("value") is None for v in observed.values())
            or device.get("tracked_reservoir") != "dock_clean"
            or device.get("split_no_unmeasured_transfer") is not True
            or not device.get("wash_completed_sensor")):
        return None
    # A control affects only the action whose exposure it governs.
    floor["controls"] = {k: v for k, v in observed.items() if not k.startswith("wash_")}
    wash["controls"] = {k: v for k, v in observed.items() if k.startswith("wash_")}
    serialize = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
    return {"robot": robot, "station": serialize({"robot": robot, "dock": station}),
            "reservoir": "dock_clean", "floor_context": serialize({**common, **floor}),
            "wash_context": serialize({**common, **wash})}


def observe(state, device, context, settings, *, now, area, wet, cleaning, washing,
            completed, volume, resolution, volume_binding_ok, max_interval, max_area,
            status=None, continuity_ok=True):
    start = state.get("session_start_ts")
    if not start:
        if device.get("wash_completed_sensor"):
            state["split_idle_baseline"] = {"epoch": _EPOCH, "status": status, "count": completed, "area": area,
                                            "ts": now, "reset": state.get("last_reset_ts"),
                                            "continuity_ok": continuity_ok}
        return
    ident = identity(device, context, settings)
    old = state.get("split_session_observation")
    if not isinstance(old, dict) or old.get("start") != start:
        baseline = state.pop("split_idle_baseline", {})
        direct_wash = bool(washing and baseline.get("epoch") == _EPOCH and baseline.get("status") in {"idle", "docked", "charging"}
                           and baseline.get("count") == completed and baseline.get("area") == area
                           and baseline.get("reset") == state.get("last_reset_ts")
                           and baseline.get("continuity_ok") and continuity_ok
                           and 0 < now - baseline.get("ts", now) <= max_interval)
        state["split_session_observation"] = {
            "start": start, "epoch": _EPOCH, "identity": ident, "area": 0., "washes": 0,
            "last_area": area, "last_count": completed, "last_ts": now,
            "last_wet": bool(wet and cleaning), "saw_wash": bool(washing),
            "reset": state.get("last_reset_ts"), "volume": volume, "last_volume": volume,
            "resolution": resolution, "volume_binding_ok": bool(volume_binding_ok and volume is not None
                and state.get("last_water_volume_ml") == volume),
            "valid": bool(ident and area is not None and completed is not None and completed >= 0
                          and completed.is_integer() and continuity_ok
                          and ((area == 0 and not washing) or direct_wash))}
        return
    obs = deepcopy(old)
    delta = None if area is None or obs["last_area"] is None else area - obs["last_area"]
    count_delta = None if completed is None or obs["last_count"] is None else completed - obs["last_count"]
    if (not continuity_ok or obs.get("epoch") != _EPOCH or ident != obs["identity"] or now <= obs["last_ts"]
            or now - obs["last_ts"] > max_interval or state.get("last_reset_ts") != obs["reset"]
            or delta is None or delta < 0 or delta > max_area or completed is None
            or not completed.is_integer() or count_delta not in (0, 1)):
        obs["valid"] = False
    elif delta > 0:
        if not obs["last_wet"] or not (wet and cleaning):
            obs["valid"] = False
        else:
            obs["area"] += delta
    if count_delta == 1:
        if not obs["saw_wash"]:
            obs["valid"] = False
        else:
            obs["washes"] += 1
        obs["saw_wash"] = False
    elif washing:
        obs["saw_wash"] = True
    # A bound sensor gap or rise invalidates the manual observation too.
    if device.get("water_volume_sensor") and (not volume_binding_ok or volume is None
            or obs["last_volume"] is None or volume > obs["last_volume"]):
        obs["valid"] = False
    # Keep sensor quality separate from manual exposure quality.
    if (not volume_binding_ok or volume is None or obs["last_volume"] is None
            or volume > obs["last_volume"] or resolution != obs["resolution"]):
        obs["volume_binding_ok"] = False
    obs.update(last_area=area, last_count=completed, last_ts=now,
               last_wet=bool(wet and cleaning), last_volume=volume)
    state["split_session_observation"] = obs


def finish(state, record, status):
    obs = state.pop("split_session_observation", None)
    if (not isinstance(obs, dict) or not obs.get("valid") or obs.get("saw_wash")
            or obs.get("epoch") != _EPOCH or not state.get("session_exposure_complete")
            or state.get("session_forecast_interrupted") or status not in {"docked", "charging"}
            or not (obs.get("area") or obs.get("washes"))):
        return
    sample = {"id": f"{obs['identity']['robot']}:{obs['start']}", "identity": obs["identity"],
              "area_m2": obs["area"], "wash_count": obs["washes"], "quality": dict(QUALITY)}
    record["split_observation"] = sample
    if (obs.get("volume_binding_ok") and obs.get("volume") is not None
            and obs.get("last_volume") is not None and obs.get("resolution")
            and obs["volume"] - obs["last_volume"] > obs["resolution"]):
        samples = list(state.get("split_sensor_measurements") or [])
        context_count = sum(1 for item in samples if item.get("identity") == obs["identity"])
        sample = {**deepcopy(sample), "source": "bound_reservoir_sensor",
                  "observed_ml": obs["volume"] - obs["last_volume"],
                  "resolution_ml": obs["resolution"],
                  "purpose": "validation" if (context_count + 1) % 4 == 0 else "training"}
        if not any(item.get("id") == sample["id"] for item in samples):
            state["split_sensor_measurements"] = [*samples, sample]
