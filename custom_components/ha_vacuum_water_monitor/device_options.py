"""Per-robot choices made in Home Assistant (entities, Repairs) or the card.

``settings["device_options"][vacuum_entity]`` is the single place for choices a
user makes about one robot outside the card's YAML. The newest explicit choice
wins over the card configuration and the model database, and every reader (the
engine, the sensors, the card, the health report) applies it the same way.
"""

from __future__ import annotations

import math
from typing import Any

CAPACITY_MIN_ML = 100
CAPACITY_MAX_ML = 10000
CAPACITY_STEP_ML = 50

OPTION_KEYS = frozenset({"capacity_ml"})


def device_options(settings: dict[str, Any] | None, vacuum_entity: str | None) -> dict[str, Any]:
    """Return one robot's stored options (a copy, never ``None``)."""
    settings = settings if isinstance(settings, dict) else {}
    options = settings.get("device_options")
    entry = options.get(vacuum_entity) if isinstance(options, dict) and vacuum_entity else None
    return dict(entry) if isinstance(entry, dict) else {}


def validate_capacity(value: Any) -> float | None:
    """Return a valid tank size in ml, ``None`` to clear it, or raise ``ValueError``."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Tank size must be a number of millilitres")
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError("Tank size must be a number of millilitres") from err
    if not math.isfinite(number) or not CAPACITY_MIN_ML <= number <= CAPACITY_MAX_ML:
        raise ValueError(f"Tank size must be between {CAPACITY_MIN_ML} and {CAPACITY_MAX_ML} ml")
    return round(number, 1)


def capacity_override(settings: dict[str, Any] | None, vacuum_entity: str | None) -> float | None:
    """The tank size the user chose for this robot, if any."""
    try:
        return validate_capacity(device_options(settings, vacuum_entity).get("capacity_ml"))
    except ValueError:
        return None


def apply_device_options(device: dict[str, Any], settings: dict[str, Any] | None) -> None:
    """Apply a robot's options to its effective device, as authored configuration."""
    capacity = capacity_override(settings, device.get("vacuum_entity"))
    if capacity is None:
        return
    explicit = set(device.get("_explicit_fields") or ())
    device["water_total_ml"] = capacity
    explicit.add("water_total_ml")
    if "tracked_capacity_ml" in explicit:
        # An authored engine capacity would otherwise keep anchoring the old size.
        device["tracked_capacity_ml"] = capacity
    device["_explicit_fields"] = tuple(sorted(explicit))
    device["capacity_option_ml"] = capacity


def merge_options(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Validate a patch for one robot; ``None`` removes a key."""
    unknown = set(patch) - OPTION_KEYS
    if unknown:
        raise ValueError(f"Unknown robot option: {', '.join(sorted(unknown))}")
    merged = dict(current)
    if "capacity_ml" in patch:
        capacity = validate_capacity(patch["capacity_ml"])
        if capacity is None:
            merged.pop("capacity_ml", None)
        else:
            merged["capacity_ml"] = capacity
    return merged
