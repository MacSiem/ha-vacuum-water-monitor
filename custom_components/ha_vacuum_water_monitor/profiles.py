"""Canonical vacuum model profiles and deterministic profile resolution."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


class CatalogValidationError(ValueError):
    """Raised when the shipped model catalog cannot be used safely."""


_CATALOG_PATH = Path(__file__).with_name("model_profiles.json")
_RESERVOIRS = {"dock_clean", "dock_dirty", "robot_clean", "robot_dirty"}
_TRACKED_RESERVOIRS = _RESERVOIRS | {"legacy_tank"}
_DEFAULT_ESTIMATED_M2_PER_ACTIVE_MINUTE = 0.8
_DERIVED_TIME_UNCERTAINTY_PERCENT = 65

# Exact values written by the pre-5.2 card when it expanded BRAND_PROFILES into
# HA Store.  This is migration data, not another resolver: it is used only to
# distinguish generated legacy values from genuinely divergent authored ones.
_LEGACY_CARD_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "roborock_s8_maxv_ultra": {
        "label": "Roborock S8 MaxV Ultra",
        "icon": "🦤",
        "water_total_ml": 3000,
        "vacuum_entity": "vacuum.roborock_s8_maxv_ultra",
        "dock_error_sensor": "sensor.roborock_s8_maxv_ultra_dock_error",
        "main_brush_sensor": "sensor.roborock_s8_maxv_ultra_main_brush_time_left",
        "side_brush_sensor": "sensor.roborock_s8_maxv_ultra_side_brush_time_left",
        "filter_time_sensor": "sensor.roborock_s8_maxv_ultra_filter_time_left",
        "sensor_dirty_sensor": "sensor.roborock_s8_maxv_ultra_sensor_time_left",
        "dock_brush_sensor": "sensor.roborock_s8_maxv_ultra_dock_maintenance_brush_time_left",
        "dock_strainer_sensor": "sensor.roborock_s8_maxv_ultra_dock_strainer_time_left",
        "dock_clean_water_sensor": "binary_sensor.roborock_s8_maxv_ultra_dock_clean_water_box",
        "dock_dirty_water_sensor": "binary_sensor.roborock_s8_maxv_ultra_dock_dirty_water_box",
        "water_shortage_sensor": "binary_sensor.roborock_s8_maxv_ultra_water_shortage",
        "mop_attached_sensor": "binary_sensor.roborock_s8_maxv_ultra_mop_attached",
        "mop_drying_sensor": "binary_sensor.roborock_s8_maxv_ultra_mop_drying",
        "area_sensor": "sensor.roborock_s8_maxv_ultra_cleaning_area",
        "duration_sensor": "sensor.roborock_s8_maxv_ultra_cleaning_time",
        "last_clean_start": "sensor.roborock_s8_maxv_ultra_last_clean_begin",
        "last_clean_end": "sensor.roborock_s8_maxv_ultra_last_clean_end",
        "charge_sensor": "sensor.roborock_s8_maxv_ultra_battery",
        "mop_mode_entity": "select.roborock_s8_maxv_ultra_mop_mode",
        "mop_intensity_entity": "select.roborock_s8_maxv_ultra_mop_intensity",
    },
    "roborock_q7": {
        "label": "Roborock Q7",
        "icon": "🦤",
        "water_total_ml": 200,
        "vacuum_entity": "vacuum.roborock_q7",
        "main_brush_sensor": "sensor.roborock_q7_main_brush_time_left",
        "side_brush_sensor": "sensor.roborock_q7_side_brush_time_left",
        "filter_time_sensor": "sensor.roborock_q7_filter_time_left",
        "charge_sensor": "sensor.roborock_q7_battery",
    },
    "dreame_l20_ultra": {
        "label": "Dreame L20 Ultra",
        "icon": "🤖",
        "water_total_ml": 4000,
        "vacuum_entity": "vacuum.dreame_l20_ultra",
        "charge_sensor": "sensor.dreame_l20_ultra_battery",
    },
    "irobot_j7": {
        "label": "iRobot j7+",
        "icon": "🦤",
        "water_total_ml": 0,
        "vacuum_entity": "vacuum.irobot_j7",
        "charge_sensor": "sensor.irobot_j7_battery_level",
    },
    "ecovacs": {
        "label": "Ecovacs (generic)",
        "icon": "🤖",
        "water_total_ml": 240,
        "vacuum_entity": "vacuum.ecovacs",
    },
    "generic": {"label": "Generic Vacuum", "icon": "🦤", "water_total_ml": 0},
}


def normalize_identifier(value: Any) -> str:
    """Normalize an HA/vendor identifier without relying on display labels."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return normalized


def load_catalog(path: Path | str = _CATALOG_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate a catalog, failing closed on malformed records."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise CatalogValidationError(f"Unable to load model profile catalog: {err}") from err
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise CatalogValidationError("Catalog must contain a non-empty profiles object")

    validated: dict[str, dict[str, Any]] = {}
    aliases: set[str] = set()
    for key, record in profiles.items():
        if normalize_identifier(key) != key:
            raise CatalogValidationError(f"Profile key must be normalized: {key!r}")
        if not isinstance(record, dict):
            raise CatalogValidationError(f"Profile {key!r} must be an object")
        identifiers = record.get("identifiers")
        if not isinstance(identifiers, list) or not identifiers or not all(
            isinstance(value, str) and normalize_identifier(value) for value in identifiers
        ):
            raise CatalogValidationError(f"Profile {key!r} has invalid identifiers")
        normalized_identifiers = [normalize_identifier(value) for value in identifiers]
        all_identifiers = set(normalized_identifiers) | {key}
        if aliases.intersection(all_identifiers):
            raise CatalogValidationError(f"Profile {key!r} reuses a catalog identifier")
        aliases.update(all_identifiers)

        reservoirs = record.get("reservoirs_ml")
        if not isinstance(reservoirs, dict) or set(reservoirs) != _RESERVOIRS:
            raise CatalogValidationError(
                f"Profile {key!r} reservoirs_ml must declare all reservoirs"
            )
        for reservoir, capacity in reservoirs.items():
            if capacity is not None and not _positive_number(capacity):
                raise CatalogValidationError(
                    f"Profile {key!r} reservoir {reservoir!r} must be positive or null"
                )
        tracked_reservoir = record.get("tracked_reservoir")
        if tracked_reservoir not in _TRACKED_RESERVOIRS:
            raise CatalogValidationError(f"Profile {key!r} has invalid tracked_reservoir")
        tracked_capacity = record.get("tracked_capacity_ml")
        if not _positive_number(tracked_capacity):
            raise CatalogValidationError(f"Profile {key!r} tracked_capacity_ml must be positive")
        if (
            tracked_reservoir in _RESERVOIRS
            and reservoirs[tracked_reservoir] != tracked_capacity
        ):
            raise CatalogValidationError(
                f"Profile {key!r} tracked_capacity_ml must match tracked_reservoir"
            )
        legacy = record.get("legacy_calibration")
        if not isinstance(legacy, dict) or legacy.get("tank_ml") != tracked_capacity:
            raise CatalogValidationError(
                f"Profile {key!r} legacy_calibration must preserve tank_ml"
            )
        legacy_robot = record.get("legacy_robot_tank_ml")
        if legacy_robot is not None and not _positive_number(legacy_robot):
            raise CatalogValidationError(
                f"Profile {key!r} legacy_robot_tank_ml must be positive or null"
            )

        accounting = record.get("accounting")
        if not isinstance(accounting, dict) or not isinstance(
            accounting.get("usage_ml_per_m2"), dict
        ):
            raise CatalogValidationError(f"Profile {key!r} has invalid accounting")
        for rate in accounting["usage_ml_per_m2"].values():
            if not _positive_number(rate):
                raise CatalogValidationError(f"Profile {key!r} has invalid usage rate")
        minute_rates = accounting.get("usage_ml_per_active_minute", {})
        if not isinstance(minute_rates, dict) or any(
            not _positive_number(rate) for rate in minute_rates.values()
        ):
            raise CatalogValidationError(
                f"Profile {key!r} has invalid active-minute usage rate"
            )
        wash_volume = accounting.get("wash_volume_ml")
        if wash_volume is not None and not _positive_number(wash_volume):
            raise CatalogValidationError(f"Profile {key!r} has invalid wash volume")
        if accounting.get("evidence") not in {
            "maintainer_estimate",
            "cross_model_estimate",
            "not_published",
        }:
            raise CatalogValidationError(f"Profile {key!r} has invalid accounting evidence")
        uncertainty = accounting.get("uncertainty_percent")
        if uncertainty is not None and (
            not _positive_number(uncertainty) or uncertainty > 100
        ):
            raise CatalogValidationError(
                f"Profile {key!r} has invalid uncertainty_percent"
            )
        if accounting.get("rate_signal", "mop_mode") not in {
            "mop_mode",
            "mop_intensity",
            "cleaning_mode",
        }:
            raise CatalogValidationError(f"Profile {key!r} has invalid rate_signal")
        if record.get("capability") not in {"automatic_estimate", "manual_only"}:
            raise CatalogValidationError(f"Profile {key!r} has invalid capability")
        if not isinstance(record.get("evidence"), str) or not isinstance(
            record.get("sources"), list
        ):
            raise CatalogValidationError(f"Profile {key!r} requires evidence and sources")
        validated[key] = deepcopy(record)
    return validated


def resolve_profile(device: dict[str, Any] | None, catalog: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve one profile using explicit configuration before registry metadata."""
    device = device if isinstance(device, dict) else {}
    catalog = CATALOG if catalog is None else catalog
    indexes = _catalog_indexes(catalog)

    locked = _first_profile(
        indexes,
        device.get("profile_override"),
        device.get("locked_profile"),
        device.get("brand_profile") if device.get("profile_locked") else None,
    ) if device.get("profile_locked") else None
    if locked:
        return _resolved(catalog[locked], locked, "locked_override", "high")

    for source, confidence, values in (
        ("model_id", "high", (device.get("model_id"),)),
        ("model", "high", (device.get("model"),)),
        ("catalog_identifier", "medium", _identifier_values(device)),
        ("resolved_profile", "high", (device.get("profile_key"),)),
        ("legacy_brand_profile", "medium", (device.get("brand_profile"),)),
        ("entity_alias", "low", (device.get("entity_id"), device.get("vacuum_entity"))),
    ):
        profile_key = _first_profile(indexes, *values)
        if profile_key:
            return _resolved(catalog[profile_key], profile_key, source, confidence)
    return {
        "profile_key": None,
        "profile_source": "unknown",
        "profile_confidence": "none",
        "capability": "unknown",
        "evidence": None,
        "sources": [],
        "tracked_reservoir": None,
        "tracked_capacity_ml": None,
        "reservoirs_ml": {},
        "usage_ml_per_m2": {},
        "usage_ml_per_active_minute": {},
        "wash_volume_ml": None,
        "accounting_evidence": None,
        "uncertainty_percent": None,
    }


def _identifier_values(device: dict[str, Any]) -> tuple[Any, ...]:
    values = device.get("catalog_identifiers")
    if isinstance(values, (list, tuple)):
        return tuple(values)
    return (device.get("identifier"), device.get("catalog_identifier"))


def _catalog_indexes(catalog: dict[str, dict[str, Any]]) -> dict[str, str]:
    indexes: dict[str, str] = {}
    for key, record in catalog.items():
        indexes[normalize_identifier(key)] = key
        for identifier in record["identifiers"]:
            indexes[normalize_identifier(identifier)] = key
    return indexes


def _first_profile(indexes: dict[str, str], *values: Any) -> str | None:
    for value in values:
        normalized = normalize_identifier(value)
        if normalized in indexes:
            return indexes[normalized]
        if normalized.startswith("vacuum_") and normalized[7:] in indexes:
            return indexes[normalized[7:]]
    return None


def _resolved(record: dict[str, Any], key: str, source: str, confidence: str) -> dict[str, Any]:
    if key == "generic":
        return {
            "profile_key": key,
            "profile_source": source,
            "profile_confidence": confidence,
            "capability": "manual_only",
            "evidence": record["evidence"],
            "sources": list(record["sources"]),
            "tracked_reservoir": None,
            "tracked_capacity_ml": None,
            "reservoirs_ml": {},
            "usage_ml_per_m2": {},
            "usage_ml_per_active_minute": {},
            "wash_volume_ml": None,
            "accounting_evidence": "not_published",
            "uncertainty_percent": None,
        }
    accounting = record["accounting"]
    area_rates = _with_default_rate(dict(accounting["usage_ml_per_m2"]))
    minute_rates = dict(accounting.get("usage_ml_per_active_minute", {}))
    time_accounting_evidence = accounting["evidence"]
    estimated_speed: float | None = None
    uncertainty = accounting.get("uncertainty_percent")
    if area_rates and not minute_rates:
        estimated_speed = _DEFAULT_ESTIMATED_M2_PER_ACTIVE_MINUTE
        minute_rates = {
            mode: round(rate * estimated_speed, 4)
            for mode, rate in area_rates.items()
        }
        time_accounting_evidence = "derived_from_area_rate"
        uncertainty = max(
            float(uncertainty or 0), _DERIVED_TIME_UNCERTAINTY_PERCENT
        )
    return {
        "profile_key": key,
        "profile_source": source,
        "profile_confidence": confidence,
        "capability": record["capability"],
        "evidence": record["evidence"],
        "sources": list(record["sources"]),
        "tracked_reservoir": record["tracked_reservoir"],
        "tracked_capacity_ml": record["tracked_capacity_ml"],
        "reservoirs_ml": dict(record["reservoirs_ml"]),
        "usage_ml_per_m2": area_rates,
        "usage_ml_per_active_minute": minute_rates,
        "wash_volume_ml": accounting["wash_volume_ml"],
        "accounting_evidence": accounting["evidence"],
        "uncertainty_percent": uncertainty,
        "rate_signal": accounting.get("rate_signal", "mop_mode"),
        "time_accounting_evidence": time_accounting_evidence,
        "estimated_m2_per_active_minute": estimated_speed,
    }


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _with_default_rate(rates: dict[str, float]) -> dict[str, float]:
    """Use the declared middle mode when an integration exposes no mode."""
    if not rates or "default" in rates:
        return rates
    for key in ("medium", "standard", "moderate", "balanced"):
        if key in rates:
            return {**rates, "default": rates[key]}
    ordered = sorted(rates.values())
    return {**rates, "default": ordered[len(ordered) // 2]}


def legacy_profile_defaults(profile_key: Any) -> dict[str, Any]:
    """Return exact pre-5.2 card expansion defaults for migration only."""
    normalized = normalize_identifier(profile_key)
    defaults = deepcopy(_LEGACY_CARD_PROFILE_DEFAULTS.get(normalized, {}))
    canonical = _catalog_indexes(CATALOG).get(normalized)
    if canonical:
        record = CATALOG[canonical]
        accounting = record["accounting"]
        legacy = record["legacy_calibration"]
        defaults.setdefault("tracked_capacity_ml", record["tracked_capacity_ml"])
        defaults.setdefault("tracked_reservoir", record["tracked_reservoir"])
        defaults.setdefault("usage_ml_per_m2", accounting["usage_ml_per_m2"])
        defaults.setdefault(
            "usage_ml_per_active_minute",
            accounting.get("usage_ml_per_active_minute", {}),
        )
        defaults.setdefault("rate_signal", accounting.get("rate_signal", "mop_mode"))
        defaults.setdefault("water_per_m2", legacy.get("water_per_m2", {}))
        defaults.setdefault("intensity_factor", legacy.get("intensity_factors", {}))
        defaults.setdefault("wash_volume_ml", accounting.get("wash_volume_ml"))
        defaults.setdefault("mop_wash_ml", legacy.get("mop_wash_ml"))
        defaults.setdefault("accounting_evidence", accounting.get("evidence"))
        defaults.setdefault("evidence", record.get("evidence"))
    return defaults


CATALOG = load_catalog()
