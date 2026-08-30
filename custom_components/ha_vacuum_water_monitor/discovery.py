"""Registry-backed, same-device vacuum descriptor discovery."""

from __future__ import annotations

from typing import Any, Iterable

from .profiles import normalize_identifier, resolve_profile


_ROLE_IDENTIFIERS = {
    "status_sensor": {"status", "cleaning_status", "vacuum_status"},
    "area_sensor": {"cleaning_area", "cleaned_area", "cleaning_area_m2"},
    "mop_mode_entity": {"mop_mode", "mop_cleaning_mode", "mop_wash_mode"},
    "mop_intensity_entity": {"mop_intensity", "mop_water_level", "water_level", "water_flow"},
}


def discover_descriptors(
    entity_records: Iterable[Any], device_records: Iterable[Any], states: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build serializable descriptors from registry-shaped records and states."""
    entities = list(entity_records)
    devices = {_value(record, "id"): record for record in device_records if _value(record, "id")}
    descriptors: list[dict[str, Any]] = []
    for vacuum in sorted(
        (record for record in entities if str(_value(record, "entity_id") or "").startswith("vacuum.")),
        key=lambda record: str(_value(record, "entity_id")),
    ):
        descriptors.append(_descriptor(vacuum, entities, devices, states))
    return descriptors


def descriptors_from_hass(hass: Any) -> list[dict[str, Any]]:
    """Read HA registries at the outer boundary; pure logic remains above."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    records = list(getattr(entity_registry, "entities", {}).values())
    known = {str(_value(record, "entity_id")) for record in records}
    for entity_id in hass.states.async_entity_ids("vacuum"):
        if entity_id not in known:
            records.append({"entity_id": entity_id, "platform": None, "unique_id": None, "device_id": None})
    states = {entity_id: hass.states.get(entity_id) for entity_id in hass.states.async_entity_ids()}
    return discover_descriptors(records, getattr(device_registry, "devices", {}).values(), states)


def _descriptor(
    vacuum: Any, entities: list[Any], devices: dict[str, Any], states: dict[str, Any]
) -> dict[str, Any]:
    entity_id = str(_value(vacuum, "entity_id") or "")
    device_id = _value(vacuum, "device_id")
    device = devices.get(device_id)
    state = states.get(entity_id)
    attributes = _attributes(state)
    # model_id was added after the integration's HA compatibility floor; use
    # getattr for registry objects and preserve it in dict-shaped test fixtures.
    model_id = (
        _value(device, "model_id")
        if isinstance(device, dict)
        else getattr(device, "model_id", None)
    )
    metadata = {
        "entity_id": entity_id,
        "model_id": model_id,
        "model": _value(device, "model"),
        "catalog_identifiers": _identifiers(device),
    }
    descriptor = {
        "entity_id": entity_id,
        "name": attributes.get("friendly_name") or _value(vacuum, "original_name") or entity_id,
        "state": _state_value(state),
        "battery": attributes.get("battery_level", attributes.get("battery")),
        "platform": _value(vacuum, "platform"),
        "registry_unique_id": _value(vacuum, "unique_id"),
        "device_id": device_id,
        "manufacturer": _value(device, "manufacturer"),
        "model": _value(device, "model"),
        "model_id": model_id,
        "source_id": _source_id(entity_id, _value(vacuum, "unique_id"), device_id),
    }
    descriptor.update(resolve_profile(metadata))
    descriptor["signals"] = _signals_for_device(device_id, entities, states)
    return descriptor


def _signals_for_device(device_id: Any, entities: list[Any], states: dict[str, Any]) -> dict[str, str]:
    """Resolve roles only among enabled, available siblings of one device."""
    if not device_id:
        return {}
    siblings = [
        entry
        for entry in entities
        if _value(entry, "device_id") == device_id
        and not _value(entry, "disabled_by")
        and _is_available(states.get(_value(entry, "entity_id")))
    ]
    resolved: dict[str, str] = {}
    for role, exact_identifiers in _ROLE_IDENTIFIERS.items():
        ranked: list[tuple[int, str]] = []
        for sibling in siblings:
            entity_id = str(_value(sibling, "entity_id") or "")
            if not entity_id or entity_id.startswith("vacuum."):
                continue
            score = _role_score(sibling, exact_identifiers)
            if score:
                ranked.append((score, entity_id))
        if not ranked:
            continue
        highest = max(score for score, _ in ranked)
        candidates = [entity_id for score, entity_id in ranked if score == highest]
        if len(candidates) == 1:
            resolved[role] = candidates[0]
    return resolved


def _role_score(record: Any, exact_identifiers: set[str]) -> int:
    translation = normalize_identifier(_value(record, "translation_key"))
    if translation in exact_identifiers:
        return 100
    values = (
        normalize_identifier(_value(record, "original_name")),
        normalize_identifier(_value(record, "entity_id")),
    )
    if any(value in exact_identifiers for value in values):
        return 90
    if any(any(identifier in value for identifier in exact_identifiers) for value in values):
        return 50
    return 0


def _identifiers(device: Any) -> list[str]:
    if device is None:
        return []
    identifiers = _value(device, "identifiers")
    if isinstance(identifiers, (set, list, tuple)):
        return [str(value) for value in identifiers]
    return []


def _source_id(entity_id: str, unique_id: Any, device_id: Any) -> str:
    if device_id:
        return f"device:{device_id}"
    if unique_id:
        return f"unique:{unique_id}"
    return f"entity:{entity_id}"


def _value(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _attributes(state: Any) -> dict[str, Any]:
    attributes = _value(state, "attributes")
    return attributes if isinstance(attributes, dict) else {}


def _state_value(state: Any) -> Any:
    return _value(state, "state")


def _is_available(state: Any) -> bool:
    return state is not None and _state_value(state) not in {"unavailable", "unknown"}
