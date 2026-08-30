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
        wash_volume = accounting.get("wash_volume_ml")
        if wash_volume is not None and not _positive_number(wash_volume):
            raise CatalogValidationError(f"Profile {key!r} has invalid wash volume")
        if accounting.get("evidence") not in {"maintainer_estimate", "not_published"}:
            raise CatalogValidationError(f"Profile {key!r} has invalid accounting evidence")
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
        "wash_volume_ml": None,
        "accounting_evidence": None,
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
    accounting = record["accounting"]
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
        "usage_ml_per_m2": dict(accounting["usage_ml_per_m2"]),
        "wash_volume_ml": accounting["wash_volume_ml"],
        "accounting_evidence": accounting["evidence"],
    }


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


CATALOG = load_catalog()
