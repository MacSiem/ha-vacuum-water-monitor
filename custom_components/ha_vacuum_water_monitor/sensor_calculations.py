"""Pure Store-derived calculations for Vacuum Water Monitor sensors."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
from typing import Any

try:
    from .profiles import resolve_profile
except ImportError:  # Supports this module's existing direct-file pure tests.
    _profile_spec = importlib.util.spec_from_file_location(
        "vwm_standalone_profiles", Path(__file__).with_name("profiles.py")
    )
    assert _profile_spec and _profile_spec.loader
    _profile_module = importlib.util.module_from_spec(_profile_spec)
    _profile_spec.loader.exec_module(_profile_module)
    resolve_profile = _profile_module.resolve_profile

MILLISECONDS_PER_DAY = 86_400_000


def vacuum_slug(vacuum_entity: str) -> str:
    """Return a stable slug for a vacuum entity id."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(vacuum_entity).lower()).strip("_")
    return slug or "unknown"


def build_vacuum_devices(
    settings: dict[str, Any] | None,
    tank_states: dict[str, Any] | None,
    discovered_vacuums: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the effective vacuum list from Store settings and known state."""
    settings = settings if isinstance(settings, dict) else {}
    tank_states = tank_states if isinstance(tank_states, dict) else {}
    discovered_vacuums = discovered_vacuums if isinstance(discovered_vacuums, list) else []

    devices: dict[str, dict[str, Any]] = {}

    for key in ("configured_devices", "user_devices"):
        for item in settings.get(key) or []:
            if not isinstance(item, dict):
                continue
            vacuum_entity = item.get("vacuum_entity")
            if not vacuum_entity:
                continue
            devices[str(vacuum_entity)] = _normalize_device(str(vacuum_entity), item)

    for vacuum_entity in tank_states:
        if not vacuum_entity:
            continue
        devices.setdefault(
            str(vacuum_entity),
            _normalize_device(str(vacuum_entity), {"vacuum_entity": vacuum_entity}),
        )

    for item in discovered_vacuums:
        if not isinstance(item, dict):
            continue
        vacuum_entity = item.get("entity_id") or item.get("vacuum_entity")
        if not vacuum_entity:
            continue
        entity = str(vacuum_entity)
        devices.setdefault(entity, _normalize_device(entity, {"vacuum_entity": entity}))
        _merge_discovery(devices[entity], item)

    # Backfill display names from live discovery: entries seeded from
    # tank_states or configured_devices may carry no name and fall back to the
    # raw entity_id ("vacuum.roborock_s7_maxv" instead of "Roborock S7 MaxV").
    for item in discovered_vacuums:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity_id") or item.get("vacuum_entity") or "")
        name = item.get("name")
        if not entity or not name or entity not in devices:
            continue
        device = devices[entity]
        if not device.get("name") or device.get("name") == entity:
            device["name"] = str(name)

    return list(devices.values())


def filter_active_devices(
    devices: list[dict[str, Any]],
    known_entities: set[str],
    tank_states: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Drop ghost devices before entity/device creation.

    A device is kept when its vacuum_entity currently exists in HA (known) or
    has recorded tank history (real vacuum that is temporarily offline).
    Phantom entries — e.g. a profile-default entity id persisted by a pre-5.1.6
    card stub config — match neither and must not create HA devices.
    """
    tank_states = tank_states if isinstance(tank_states, dict) else {}
    kept: list[dict[str, Any]] = []
    for device in devices:
        vacuum_entity = device.get("vacuum_entity")
        if not vacuum_entity:
            continue
        entity = str(vacuum_entity)
        if entity not in known_entities and entity not in tank_states:
            continue
        kept.append(device)
    return kept


def estimate_water_state(
    device: dict[str, Any] | None,
    tank_state: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate water state from stored tank usage and stored capacity."""
    device = device if isinstance(device, dict) else {}
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    settings = settings if isinstance(settings, dict) else {}

    profile = resolve_profile(device)
    initialized = bool(tank_state.get("initialized")) or parse_refill_datetime(tank_state) is not None
    total_ml = _water_capacity_ml(device, settings)
    metadata = {
        "initialized": initialized,
        "state_reason": None,
        "capability": device.get("capability") or profile["capability"],
        "profile_key": device.get("profile_key") or profile["profile_key"],
        "profile_source": device.get("profile_source") or profile["profile_source"],
        "profile_confidence": device.get("profile_confidence") or profile["profile_confidence"],
        "accounting_evidence": tank_state.get("last_accounting_evidence") or device.get("accounting_evidence") or profile["accounting_evidence"],
    }
    if not initialized:
        return {
            "source": "uninitialized",
            "total_ml": _format_number(total_ml) if total_ml is not None else None,
            "used_ml": None,
            "remaining_ml": None,
            "remaining_percent": None,
            **{**metadata, "state_reason": "awaiting_refill"},
        }

    used_ml = max(0, _number(tank_state.get("used_ml"), 0))
    if total_ml is None:
        return {
            "source": "unknown_capacity",
            "total_ml": None,
            "used_ml": _format_number(used_ml),
            "remaining_ml": None,
            "remaining_percent": None,
            **{**metadata, "state_reason": "unknown_capacity"},
        }

    remaining_ml = max(0, total_ml - used_ml)
    percent = _clamp((remaining_ml / total_ml) * 100, 0, 100)
    return {
        "source": "stored_estimate",
        "total_ml": _format_number(total_ml),
        "used_ml": _format_number(used_ml),
        "remaining_ml": _format_number(remaining_ml),
        "remaining_percent": _format_number(round(percent, 1)),
        **metadata,
    }


def apply_custom_calibration(
    device: dict[str, Any] | None,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge stored per-device usage calibration into an effective device.

    Explicit device configuration remains authoritative. The returned copy is
    safe for the accounting tick to mutate without changing Store settings.
    """
    effective = dict(device) if isinstance(device, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    profile = resolve_profile(effective)
    for key in ("profile_key", "profile_source", "profile_confidence", "capability", "evidence"):
        if profile.get(key) is not None:
            effective.setdefault(key, profile[key])

    calibration = _merged_custom_calibration(effective, settings)
    profile_usage = _valid_rate_mapping(profile.get("usage_ml_per_m2"))
    custom_usage = _valid_rate_mapping(
        calibration.get("usage_ml_per_m2", calibration.get("water_per_m2"))
    )
    discovered_usage = _valid_rate_mapping(effective.get("usage_ml_per_m2"))
    explicit_fields = _explicit_fields(effective)
    explicit_usage = (
        discovered_usage
        if "usage_ml_per_m2" in explicit_fields
        else {} if explicit_fields else (
            {} if discovered_usage == profile_usage else discovered_usage
        )
    )
    merged_usage = {**profile_usage, **custom_usage, **explicit_usage}
    if merged_usage:
        effective["usage_ml_per_m2"] = merged_usage

    for key in ("intensity_factor",):
        merged_mapping = {
            **_valid_rate_mapping(calibration.get(key)),
            **_valid_rate_mapping(effective.get(key)),
        }
        if merged_mapping:
            effective[key] = merged_mapping

    profile_wash = _positive_optional(profile.get("wash_volume_ml"))
    custom_wash = _positive_optional(
        calibration.get("wash_volume_ml", calibration.get("mop_wash_ml"))
    )
    discovered_wash = _positive_optional(effective.get("wash_volume_ml"))
    explicit_wash = (
        discovered_wash
        if "wash_volume_ml" in explicit_fields
        else None if explicit_fields or discovered_wash == profile_wash else discovered_wash
    )
    wash_volume = explicit_wash or custom_wash or profile_wash
    if wash_volume is not None:
        effective["wash_volume_ml"] = wash_volume

    capacity = _positive_optional(
        calibration.get("tracked_capacity_ml", calibration.get("tank_ml"))
    )
    profile_capacity = _positive_optional(profile.get("tracked_capacity_ml"))
    discovered_capacity = _positive_optional(effective.get("tracked_capacity_ml"))
    if capacity is not None and (
        "tracked_capacity_ml" not in explicit_fields
        and (discovered_capacity is None or discovered_capacity == profile_capacity)
    ):
        effective["tracked_capacity_ml"] = capacity
    legacy_robot = _positive_optional(
        effective.get("legacy_robot_tank_ml", effective.get("robot_tank_ml"))
    ) or _positive_optional(calibration.get("robot_tank_ml"))
    if legacy_robot is not None:
        effective["legacy_robot_tank_ml"] = legacy_robot
    profile_evidence = profile.get("accounting_evidence")
    discovery_evidence = effective.get("accounting_evidence")
    if explicit_usage or explicit_wash:
        if discovery_evidence is None or discovery_evidence == profile_evidence:
            effective["accounting_evidence"] = "explicit_user_configuration"
    elif custom_usage or custom_wash:
        if discovery_evidence is None or discovery_evidence == profile_evidence:
            effective["accounting_evidence"] = "user_calibration"
    elif profile_evidence is not None:
        effective.setdefault("accounting_evidence", profile_evidence)
    return effective


def parse_refill_datetime(tank_state: dict[str, Any] | None) -> datetime | None:
    """Parse the Store refill timestamp as an aware UTC datetime."""
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    raw_iso = tank_state.get("last_reset_iso")
    if isinstance(raw_iso, str) and raw_iso.strip():
        try:
            parsed = datetime.fromisoformat(raw_iso.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    raw_ts = _optional_number(tank_state.get("last_reset_ts"))
    if raw_ts and raw_ts > 0:
        seconds = raw_ts / 1000 if raw_ts > 10_000_000_000 else raw_ts
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    return None


def next_maintenance_due(
    maintenance_items: list[Any] | None, now_ms: int | None = None
) -> dict[str, Any] | None:
    """Return the most urgent scheduled custom maintenance item."""
    if not isinstance(maintenance_items, list):
        return None
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(maintenance_items):
        if not isinstance(item, dict):
            continue
        interval_days = _optional_number(item.get("intervalDays"))
        last_done_ms = _optional_number(item.get("lastDone"))
        if not interval_days or interval_days <= 0 or not last_done_ms:
            continue

        days_since = int((now_ms - last_done_ms) // MILLISECONDS_PER_DAY)
        days_left = int(interval_days) - days_since
        due_at_ms = int(last_done_ms + int(interval_days) * MILLISECONDS_PER_DAY)
        candidate = {
            "index": index,
            "name": str(item.get("name") or "Maintenance item"),
            "icon": item.get("icon"),
            "interval_days": int(interval_days),
            "last_done_ms": int(last_done_ms),
            "last_done_at": _datetime_from_ms(int(last_done_ms)).isoformat(),
            "due_at_ms": due_at_ms,
            "due_at": _datetime_from_ms(due_at_ms).isoformat(),
            "days_since": days_since,
            "days_left": days_left,
            "days_overdue": abs(days_left) if days_left < 0 else 0,
            "overdue": days_left < 0,
        }
        candidates.append(candidate)

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item["days_left"], item["due_at_ms"], item["index"]))[0]


def _normalize_device(vacuum_entity: str, item: dict[str, Any]) -> dict[str, Any]:
    device = dict(item)
    device["_explicit_fields"] = tuple(device)
    device["vacuum_entity"] = vacuum_entity
    if not device.get("name"):
        device["name"] = device.get("device_name") or device.get("label") or vacuum_entity
    return device


def _water_capacity_ml(
    device: dict[str, Any], settings: dict[str, Any]
) -> float | None:
    direct = _optional_number(device.get("water_total_ml"))
    if direct and direct > 0:
        return direct

    custom = _merged_custom_calibration(device, settings)
    tracked = _optional_number(device.get("tracked_capacity_ml"))
    profile_capacity = _model_tank_ml(device)
    explicit_fields = _explicit_fields(device)
    if custom:
        tank_ml = _optional_number(custom.get("tracked_capacity_ml", custom.get("tank_ml")))
        if tank_ml and tank_ml > 0 and (
            "tracked_capacity_ml" not in explicit_fields
            and (not tracked or tracked == profile_capacity)
        ):
            return tank_ml

    if tracked and tracked > 0:
        return tracked

    # Model database fallback: capacity known from the vacuum model without any
    # manual calibration, mirroring the card's auto-detected brand_profile.
    return _model_tank_ml(device)


def _model_tank_ml(device: dict[str, Any]) -> float | None:
    """Default tank capacity (ml) resolved from the vacuum model database."""
    tank_ml = resolve_profile(device).get("tracked_capacity_ml")
    return float(tank_ml) if tank_ml and tank_ml > 0 else None


def _custom_calibration_keys(device: dict[str, Any]) -> tuple[str, ...]:
    """Return custom calibration keys from most to least device-specific."""
    entity = str(device.get("vacuum_entity") or "").strip().lower()
    profile = device.get("brand_profile")
    resolved = _resolve_model_key(device)
    candidates = [
        f"entity:{entity}" if entity else "",
        str(profile) if isinstance(profile, str) else "",
        resolved or "",
        "default",
    ]
    return tuple(dict.fromkeys(key for key in candidates if key))


def _matching_custom_calibration(
    device: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any] | None:
    """Return the most specific valid custom calibration for a device."""
    custom = settings.get("custom_calibration")
    if not isinstance(custom, dict):
        return None
    for key in _custom_calibration_keys(device):
        value = custom.get(key)
        if isinstance(value, dict):
            return value
    return None


def _merged_custom_calibration(device: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Merge default/profile/entity calibration layers without cross-device leakage."""
    custom = settings.get("custom_calibration")
    if not isinstance(custom, dict):
        return {}
    merged: dict[str, Any] = {}
    for key in reversed(_custom_calibration_keys(device)):
        value = custom.get(key)
        if not isinstance(value, dict):
            continue
        for name, raw in _normalize_calibration_layer(value).items():
            if isinstance(raw, dict) and isinstance(merged.get(name), dict):
                merged[name] = {**merged[name], **raw}
            else:
                merged[name] = raw
    return merged


def _normalize_calibration_layer(layer: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy aliases before applying this layer's precedence."""
    normalized = dict(layer)

    usage: dict[str, Any] = {}
    for key in ("water_per_m2", "usage_ml_per_m2"):
        value = layer.get(key)
        if isinstance(value, dict):
            usage.update(value)
    if usage:
        normalized["usage_ml_per_m2"] = usage
    normalized.pop("water_per_m2", None)

    for canonical, legacy in (
        ("wash_volume_ml", "mop_wash_ml"),
        ("tracked_capacity_ml", "tank_ml"),
    ):
        canonical_value = _positive_optional(layer.get(canonical))
        legacy_value = _positive_optional(layer.get(legacy))
        if canonical_value is not None or legacy_value is not None:
            normalized[canonical] = (
                canonical_value if canonical_value is not None else legacy_value
            )
        normalized.pop(legacy, None)
    return normalized


def _resolve_model_key(device: dict[str, Any]) -> str:
    """Resolve the canonical backend profile key for calibration lookup."""
    return str(resolve_profile(device).get("profile_key") or "")


def _merge_discovery(device: dict[str, Any], descriptor: dict[str, Any]) -> None:
    """Add descriptor metadata while keeping every explicit user field authoritative."""
    signals = descriptor.get("signals")
    if isinstance(signals, dict):
        if "signals" in device:
            explicit_signals = device["signals"]
            if isinstance(explicit_signals, dict):
                for key, value in explicit_signals.items():
                    device.setdefault(key, value)
        else:
            for key, value in signals.items():
                if value and key not in device:
                    device[key] = value
            device["signals"] = dict(signals)
    for key, value in descriptor.items():
        if key in {"entity_id", "vacuum_entity", "signals", "name"}:
            continue
        if value is not None and key not in device:
            device[key] = value
    if descriptor.get("name") and (not device.get("name") or device["name"] == device["vacuum_entity"]):
        device["name"] = str(descriptor["name"])


def _number(value: Any, default: float) -> float:
    parsed = _optional_number(value)
    return default if parsed is None else parsed


def _optional_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_optional(value: Any) -> float | None:
    parsed = _optional_number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _valid_rate_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): parsed
        for key, raw in value.items()
        if str(key).strip() and (parsed := _positive_optional(raw)) is not None
    }


def _explicit_fields(device: dict[str, Any]) -> set[str]:
    """Return fields supplied by settings rather than merged discovery data."""
    fields = device.get("_explicit_fields")
    if not isinstance(fields, (list, tuple, set, frozenset)):
        return set()
    return {str(field) for field in fields}


def _format_number(value: float) -> int | float:
    rounded = round(float(value), 1)
    return int(rounded) if rounded.is_integer() else rounded


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
