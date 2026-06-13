"""Pure Store-derived calculations for Vacuum Water Monitor sensors."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

MILLISECONDS_PER_DAY = 86_400_000

# Default tank capacity (ml) per known vacuum model, ported from the card's
# CALIBRATION_DATA so the sensor knows capacity from the device model WITHOUT
# any manual calibration. The key matches the auto-detected brand_profile and
# the vacuum entity_id slug (e.g. vacuum.roborock_s8_maxv_ultra). The generic
# profile is intentionally excluded: an unrecognised model stays "unknown"
# instead of reporting a misleading percentage, mirroring the card's water calc.
DEFAULT_TANK_ML: dict[str, float] = {
    "roborock_s8_maxv_ultra": 3000,
    "roborock_s8_pro_ultra": 3500,
    "roborock_s7_maxv_ultra": 3000,
    "roborock_s7_maxv": 200,
    "roborock_s9_maxv": 4000,
    "roborock_q_revo": 5000,
    "roborock_q_revo_maxv": 4000,
    "roborock_q7_max": 350,
    "roborock_q7": 300,
    "dreame_x40_ultra": 4500,
    "dreame_x30_ultra": 4500,
    "dreame_l20_ultra": 4500,
    "dreame_l10s_ultra": 2500,
    "dreame_l10s_pro_ultra": 4500,
    "dreame_d10_plus": 150,
    "ecovacs_x2_omni": 4000,
    "ecovacs_t20_omni": 4000,
    "ecovacs_t30_omni": 4000,
    "ecovacs_n20_plus": 220,
    "irobot_combo_j9": 3000,
    "irobot_combo_j7": 210,
    "irobot_combo_essential": 200,
    "narwal_freo_x_ultra": 5000,
    "narwal_freo_x_plus": 280,
    "eufy_x10_pro_omni": 3000,
    "samsung_jet_bot_combo": 4000,
    "xiaomi_x20_max": 4000,
    "xiaomi_x20_pro": 4000,
}


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
        devices.setdefault(
            str(vacuum_entity),
            _normalize_device(
                str(vacuum_entity),
                {
                    "vacuum_entity": vacuum_entity,
                    "name": item.get("name"),
                },
            ),
        )

    return list(devices.values())


def estimate_water_state(
    device: dict[str, Any] | None,
    tank_state: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate water state from stored tank usage and stored capacity."""
    device = device if isinstance(device, dict) else {}
    tank_state = tank_state if isinstance(tank_state, dict) else {}
    settings = settings if isinstance(settings, dict) else {}

    used_ml = max(0, _number(tank_state.get("used_ml"), 0))
    total_ml = _water_capacity_ml(device, settings)
    if total_ml is None:
        return {
            "source": "unknown_capacity",
            "total_ml": None,
            "used_ml": _format_number(used_ml),
            "remaining_ml": None,
            "remaining_percent": None,
        }

    remaining_ml = max(0, total_ml - used_ml)
    percent = _clamp((remaining_ml / total_ml) * 100, 0, 100)
    return {
        "source": "stored_estimate",
        "total_ml": _format_number(total_ml),
        "used_ml": _format_number(used_ml),
        "remaining_ml": _format_number(remaining_ml),
        "remaining_percent": _format_number(round(percent, 1)),
    }


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

    custom = settings.get("custom_calibration")
    if isinstance(custom, dict):
        profile_key = device.get("brand_profile") or "default"
        for key in (profile_key, "default"):
            value = custom.get(key)
            if not isinstance(value, dict):
                continue
            tank_ml = _optional_number(value.get("tank_ml"))
            if tank_ml and tank_ml > 0:
                return tank_ml

    # Model database fallback: capacity known from the vacuum model without any
    # manual calibration, mirroring the card's auto-detected brand_profile.
    return _model_tank_ml(device)


def _model_tank_ml(device: dict[str, Any]) -> float | None:
    """Default tank capacity (ml) resolved from the vacuum model database."""
    key = device.get("brand_profile")
    if not (isinstance(key, str) and key in DEFAULT_TANK_ML):
        entity = str(device.get("vacuum_entity") or "").strip().lower()
        key = entity[len("vacuum.") :] if entity.startswith("vacuum.") else ""
    tank_ml = DEFAULT_TANK_ML.get(key)
    return float(tank_ml) if tank_ml and tank_ml > 0 else None


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


def _format_number(value: float) -> int | float:
    rounded = round(float(value), 1)
    return int(rounded) if rounded.is_integer() else rounded


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
