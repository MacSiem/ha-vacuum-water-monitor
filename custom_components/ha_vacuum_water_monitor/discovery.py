"""Registry-backed, same-device vacuum descriptor discovery."""

from __future__ import annotations

from typing import Any, Iterable

from .integration_adapters import (
    ADAPTER_ATTRIBUTE_BINDINGS,
    ADAPTER_DESCRIPTOR_METADATA,
    ADAPTER_ROLE_IDENTIFIERS,
    MIOT_ADAPTERS,
    ROLE_IDENTIFIERS,
    adapter_for,
    miot_role_rank_for,
)
from .profiles import normalize_identifier, resolve_profile


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
    integration_adapter = adapter_for(
        descriptor["platform"], descriptor["manufacturer"], descriptor["registry_unique_id"]
    )
    descriptor["integration_adapter"] = integration_adapter
    descriptor.update(ADAPTER_ATTRIBUTE_BINDINGS.get(integration_adapter, {}))
    descriptor.update(ADAPTER_DESCRIPTOR_METADATA.get(integration_adapter, {}))
    related_dock_ids = _verified_related_dock_ids(
        device_id, devices, integration_adapter
    )
    descriptor["related_dock_confidence"] = (
        "high" if related_dock_ids else "none"
    )
    descriptor.update(resolve_profile(metadata))
    signal_device_ids = {device_id, *related_dock_ids} if device_id else set()
    descriptor["signals"], descriptor["ambiguous_roles"] = _signals_for_device(
        signal_device_ids, integration_adapter, entities, states
    )
    descriptor["sibling_entities"] = _sibling_entities(
        signal_device_ids, entities, states
    )
    return descriptor


def _sibling_entities(
    device_ids: Any, entities: list[Any], states: dict[str, Any]
) -> list[dict[str, Any]]:
    """List same-device entities the user can assign to a role by hand.

    Automatic resolution fails closed for integrations this build has never
    seen.  Returning the candidates anyway is what lets the card offer a manual
    assignment instead of leaving the user with a silent zero.
    """
    if not device_ids:
        return []
    if not isinstance(device_ids, (set, frozenset, list, tuple)):
        device_ids = {device_ids}
    siblings: list[dict[str, Any]] = []
    for entry in entities:
        entity_id = str(_value(entry, "entity_id") or "")
        if not entity_id or entity_id.startswith("vacuum."):
            continue
        if _value(entry, "device_id") not in set(device_ids):
            continue
        if _value(entry, "disabled_by"):
            continue
        attributes = _attributes(states.get(entity_id))
        siblings.append(
            {
                "entity_id": entity_id,
                "domain": entity_id.split(".", 1)[0],
                "name": attributes.get("friendly_name")
                or _value(entry, "original_name")
                or entity_id,
                "translation_key": _value(entry, "translation_key"),
                "device_class": attributes.get("device_class")
                or _value(entry, "original_device_class"),
                "unit_of_measurement": attributes.get("unit_of_measurement"),
                "state_class": attributes.get("state_class"),
            }
        )
    siblings.sort(key=lambda item: item["entity_id"])
    return siblings


def _signals_for_device(
    device_ids: Any,
    integration_adapter: Any,
    entities: list[Any],
    states: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    """Resolve roles among enabled siblings using adapter-owned contracts.

    Some integrations, notably Dreame, intentionally mark mode entities
    unavailable during a run.  Keeping an exact registry binding lets the tick
    resume when the entity returns; availability is evaluated when its value is
    consumed.  Unknown/uncontracted platforms still fail closed.

    Returns the resolved roles and the roles that had more than one equally
    strong candidate.  A tie is resolved deterministically rather than dropped:
    HA Core's ``xiaomi_miio`` registers ``is_water_box_attached`` twice for
    mop-capable models, and silently discarding the role there removed the mop
    evidence for every such vacuum.  The ambiguity is reported so the card can
    ask the user to confirm the binding.
    """
    if not device_ids:
        return {}, []
    if not isinstance(device_ids, (set, frozenset, list, tuple)):
        device_ids = {device_ids}
    else:
        device_ids = set(device_ids)
    siblings = [
        entry
        for entry in entities
        if _value(entry, "device_id") in device_ids
        and not _value(entry, "disabled_by")
    ]
    resolved: dict[str, str] = {}
    ambiguous: list[str] = []
    for role, exact_identifiers in ROLE_IDENTIFIERS.items():
        ranked: list[tuple[int, str]] = []
        for sibling in siblings:
            entity_id = str(_value(sibling, "entity_id") or "")
            if not entity_id or entity_id.startswith("vacuum."):
                continue
            score = _role_score(
                sibling, role, exact_identifiers, integration_adapter
            )
            if score:
                if _is_available(states.get(entity_id)):
                    score += 2
                ranked.append((score, entity_id))
        if not ranked:
            continue
        highest = max(score for score, _ in ranked)
        candidates = sorted(
            entity_id for score, entity_id in ranked if score == highest
        )
        if len(candidates) > 1:
            ambiguous.append(role)
            if role not in _TIE_BREAKABLE_ROLES or highest < _TIE_BREAK_MIN_SCORE:
                # Anything outside the interchangeable-attachment set feeds a
                # quantity, a rate key or a calibration anchor, and a weak
                # substring match is not a contract.  The role stays unbound
                # and the card asks the user to choose.
                continue
        # Equal binary attachment evidence is interchangeable, so a tie there is
        # resolved rather than dropped.  HA Core's ``xiaomi_miio`` registers
        # ``is_water_box_attached`` twice for mop-capable models; dropping it
        # removed the mop evidence for every such vacuum.  Shortest entity_id
        # wins because Home Assistant appends ``_2`` to the later duplicate,
        # which makes the choice independent of registry iteration order.
        resolved[role] = min(candidates, key=lambda value: (len(value), value))
    return resolved, ambiguous


# The only roles whose equally ranked candidates are genuinely interchangeable:
# they report the same physical attachment as a binary.  Every other role feeds
# either a quantity (area, duration, tank level), a rate key (mop mode and
# intensity, cleaning mode) or a calibration anchor (shortage, dock water and
# error states) whose wrong pick silently changes the reported millilitres — and
# an anchor additionally trains a persisted calibration factor.
_TIE_BREAKABLE_ROLES = frozenset(
    {
        "mop_attached_sensor",
        "water_box_attached_sensor",
        "water_box_detached_sensor",
    }
)

# Only a contract-grade match may be tie-broken.  Valetudo's substring tier
# scores 50/30 and routinely matches one dock sensor for several roles.
_TIE_BREAK_MIN_SCORE = 90


def _verified_related_dock_ids(
    device_id: Any,
    devices: dict[str, Any],
    integration_adapter: str,
) -> set[str]:
    """Link one separate Roborock dock only when registry metadata is exact.

    Home Assistant may expose the robot and dock as separate device-registry
    entries without ``via_device_id``.  Model prefix + manufacturer + shared
    config entry is deterministic.  Multiple matches fail closed.
    """
    if integration_adapter != "roborock" or not device_id:
        return set()
    robot = devices.get(device_id)
    robot_model = normalize_identifier(_value(robot, "model"))
    robot_manufacturer = normalize_identifier(_value(robot, "manufacturer"))
    robot_entries = _config_entries(robot)
    if not robot_model or not robot_manufacturer or not robot_entries:
        return set()

    candidates: list[str] = []
    for candidate_id, candidate in devices.items():
        if candidate_id == device_id:
            continue
        if normalize_identifier(_value(candidate, "manufacturer")) != robot_manufacturer:
            continue
        candidate_model = normalize_identifier(_value(candidate, "model"))
        is_matching_dock = (
            candidate_model == f"{robot_model}_dock"
            or (
                candidate_model.startswith(f"{robot_model}_")
                and candidate_model.endswith("dock")
            )
        )
        if not is_matching_dock:
            continue
        if not robot_entries.intersection(_config_entries(candidate)):
            continue
        candidates.append(str(candidate_id))
    return {candidates[0]} if len(candidates) == 1 else set()


def _config_entries(device: Any) -> set[str]:
    entries = _value(device, "config_entries")
    if isinstance(entries, (set, frozenset, list, tuple)):
        return {str(entry) for entry in entries if entry}
    return set()


def _role_score(
    record: Any, role: str, exact_identifiers: set[str], integration_adapter: Any
) -> int:
    translation = normalize_identifier(_value(record, "translation_key"))
    platform = normalize_identifier(_value(record, "platform"))
    adapter = normalize_identifier(integration_adapter)
    vendor_identifiers = ADAPTER_ROLE_IDENTIFIERS.get(adapter, {}).get(role, ())
    platform_matches_adapter = bool(
        platform
        and (
            platform == adapter
            or (adapter == "valetudo" and platform == "mqtt")
        )
    )
    if platform_matches_adapter and translation in vendor_identifiers:
        # Earlier tuple entries are stronger when an integration exposes
        # several similar sensors (Dreame state > status > task_status).
        return 160 - vendor_identifiers.index(translation) * 10
    if adapter in MIOT_ADAPTERS and platform_matches_adapter:
        # These integrations name entities after canonical MIoT properties
        # instead of a translation_key.  The property identifies exactly one
        # role, so an entity claimed by another role must not fall through to
        # a weaker match here.
        matched_role, rank, depth = miot_role_rank_for(
            (
                _value(record, "translation_key"),
                _value(record, "unique_id"),
                _value(record, "entity_id"),
            ),
            adapter,
        )
        if matched_role != role:
            return 0
        # Depth keeps the score above the contract floor so a MIoT match is
        # never demoted below a substring guess, while still ranking a bare
        # ``status`` above ``task_status`` on the same device.
        return max(150 - rank * 5 - min(depth, 40), 100)
    if adapter != "valetudo":
        return 0
    # Friendly/original names are not a machine contract and may be localized
    # or user-edited.  Valetudo's canonical MQTT discovery is the sole
    # documented exception when translation_key is absent.
    if not (adapter == "valetudo" and platform == "mqtt"):
        return 0
    values = (
        normalize_identifier(_value(record, "original_name")),
        normalize_identifier(_value(record, "entity_id")),
    )
    vendor_identifier_set = set(vendor_identifiers)
    all_identifiers = exact_identifiers | vendor_identifier_set
    if any(value in vendor_identifiers for value in values) and platform_matches_adapter:
        return 110
    if any(value in exact_identifiers for value in values):
        return 90 if platform_matches_adapter else 70
    if any(any(identifier in value for identifier in all_identifiers) for value in values):
        return 50 if platform_matches_adapter else 30
    return 0


def _identifiers(device: Any) -> list[str]:
    if device is None:
        return []
    identifiers = _value(device, "identifiers")
    if isinstance(identifiers, (set, list, tuple)):
        values: list[str] = []
        for identifier in identifiers:
            if isinstance(identifier, (tuple, list)) and len(identifier) == 2:
                domain, value = identifier
                values.extend((str(value), f"{domain}_{value}"))
            else:
                values.append(str(identifier))
        return values
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
