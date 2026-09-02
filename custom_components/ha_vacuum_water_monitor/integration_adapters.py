"""Machine-readable signal aliases exposed by supported HA integrations.

The registry ``translation_key`` is preferred.  Display names are only a
last-resort match for integrations such as MQTT discovery that do not provide
translation keys.  Keeping the aliases here prevents localized UI text from
becoming accounting logic.
"""

from __future__ import annotations

import re
from typing import Any


ROLE_IDENTIFIERS: dict[str, set[str]] = {
    "status_sensor": {
        "status",
        "cleaning_status",
        "vacuum_status",
        "operational_state",
        "state",
    },
    "cleaning_active_sensor": {"in_cleaning", "cleaning_active"},
    "area_sensor": {
        "cleaning_area",
        "cleaned_area",
        "cleaning_area_m2",
        "clean_area",
        "current_clean_area",
        "current_statistics_area",
    },
    "duration_sensor": {
        "cleaning_time",
        "clean_time",
        "current_clean_time",
        "current_statistics_time",
    },
    "mop_mode_entity": {
        "mop_mode",
        "mop_cleaning_mode",
        "mop_wash_mode",
        "mop_route",
    },
    "mop_intensity_entity": {
        "mop_intensity",
        "mop_water_level",
        "water_level",
        "water_flow",
        "water_volume",
    },
    "cleaning_mode_entity": {"cleaning_mode", "clean_mode", "operation_mode"},
    "mop_attached_sensor": {
        "mop_attached",
        "mop_attachment",
        "mop_pad",
    },
    "water_box_attached_sensor": {
        "water_box_attached",
        "water_tank_attached",
        "water_tank",
    },
    "water_box_detached_sensor": {"water_tank_detached"},
    "water_shortage_sensor": {
        "water_shortage",
        "clean_water_shortage",
    },
    "dock_clean_water_sensor": {
        "clean_box_empty",
        "clean_fluid_empty",
        "clean_water_box_empty",
        "dock_clean_water_box",
        "water_tank_clean",
        "freshwater",
    },
    "dock_dirty_water_sensor": {
        "dirty_box_full",
        "dirty_water_box",
        "water_tank_dirty",
        "wastewater",
    },
    "dock_error_sensor": {"dock_error", "base_error"},
    "dock_status_sensor": {"dock_status", "station_state", "base_status"},
    "water_error_sensor": {"operational_error", "water_error"},
    "tank_level_sensor": {"tank_level"},
    "dock_tank_level_sensor": {"dock_tank_level"},
}


ADAPTER_ROLE_IDENTIFIERS: dict[str, dict[str, tuple[str, ...]]] = {
    "roborock": {
        "status_sensor": ("status", "a01_status", "q7_status"),
        "cleaning_active_sensor": ("in_cleaning",),
        "area_sensor": ("cleaning_area", "clean_area"),
        "duration_sensor": ("cleaning_time", "clean_time"),
        "mop_mode_entity": ("mop_mode", "cleaning_route"),
        "mop_intensity_entity": ("mop_intensity", "water_box_mode", "water_flow"),
        "cleaning_mode_entity": ("cleaning_mode",),
        "mop_attached_sensor": ("mop_attached",),
        "water_box_attached_sensor": ("water_box_attached",),
        "water_shortage_sensor": ("water_shortage",),
        "dock_clean_water_sensor": ("clean_box_empty", "clean_fluid_empty"),
        "dock_dirty_water_sensor": ("dirty_box_full",),
        "dock_error_sensor": ("dock_error",),
    },
    "matter": {
        "status_sensor": ("operational_state",),
        "cleaning_mode_entity": ("clean_mode",),
        "water_error_sensor": ("operational_error",),
    },
    "ecovacs": {
        "area_sensor": ("stats_area",),
        "duration_sensor": ("stats_time",),
        "mop_intensity_entity": ("water_amount",),
        "cleaning_mode_entity": ("work_mode",),
        "mop_attached_sensor": ("water_mop_attached",),
        "dock_status_sensor": ("station_state",),
        "dock_error_sensor": ("error",),
    },
    "roomba": {
        "tank_level_sensor": ("tank_level",),
        "dock_tank_level_sensor": ("dock_tank_level",),
    },
    "smartthings": {
        "mop_intensity_entity": ("robot_cleaner_water_spray_level",),
        "cleaning_mode_entity": ("robot_cleaner_cleaning_type",),
    },
    "tplink": {
        # Current HA Core exposes run statistics, but not python-kasa's Mop
        # module (mop_attached/mop_waterlevel) as HA entities yet.  Area/time
        # are still useful when the user supplies an explicit mop gate.
        "area_sensor": ("clean_area",),
        "duration_sensor": ("clean_time",),
    },
    "xiaomi_miio": {
        "area_sensor": ("clean_area",),
        "duration_sensor": ("clean_time",),
        # HA Core's xiaomi_miio ``water_level`` sensor belongs to humidifiers,
        # not robot vacuums.  Vacuum water evidence is attachment/shortage.
        "mop_attached_sensor": ("is_water_box_carriage_attached",),
        "water_box_attached_sensor": ("is_water_box_attached",),
        "water_box_detached_sensor": ("water_tank_detached",),
        "water_shortage_sensor": ("is_water_shortage", "no_water"),
    },
    # XiaoMi/ha_xiaomi_home publishes no ``translation_key`` at all and names
    # entities from localized MIoT descriptions.  Its only machine-stable
    # handle is the generated entity_id (which equals unique_id):
    # ``<platform>.<model>_<cloud>_<did>_<miot_property>_p_<siid>_<piid>``.
    # The aliases below are therefore canonical MIoT property names, matched
    # as a suffix by ``miot_property_for``.  Statistical/lifetime properties
    # (``statistical-clean-area``) are deliberately absent: they accumulate
    # across sessions and would be read as a single run.
    "xiaomi_home": {
        "status_sensor": ("status",),
        "area_sensor": ("cleaning_area", "clean_area"),
        "duration_sensor": ("cleaning_time", "clean_time"),
        "mop_intensity_entity": (
            "mop_water_output_level",
            "mop_water_output_level_no_tank",
        ),
        # ``mode`` is intentionally absent: suffix matching would claim every
        # ``*_mode`` entity (dnd_mode, carpet_mode, water_mode), and MIoT
        # ``vacuum:mode`` is suction power, not the sweep/mop distinction.
        "cleaning_mode_entity": ("sweep_mop_type", "clean_mode"),
        "mop_attached_sensor": ("mop_status", "sweep_mop_status"),
        "water_box_attached_sensor": (
            "host_water_tank_status",
            "water_tank_status",
            "water_box_status",
            "water_box_exist",
        ),
        "water_shortage_sensor": ("water_shortage_status",),
        "dock_clean_water_sensor": ("base_station_water_tank_status",),
        "dock_dirty_water_sensor": ("sewage_tank_status",),
    },
    # al-one/hass-xiaomi-miot exposes the same MIoT properties, but prefixes
    # ``translation_key`` with the service name (``vacuum-cleaning_area``) and
    # suffixes ``unique_id`` with the piid (``...-vacuum-2.cleaning_area-6``).
    # Both reduce to the same canonical property name after normalization.
    "xiaomi_miot": {
        "status_sensor": ("status",),
        "area_sensor": ("cleaning_area", "clean_area"),
        "duration_sensor": ("cleaning_time", "clean_time"),
        "mop_intensity_entity": (
            "mop_water_output_level",
            "mop_water_output_level_no_tank",
        ),
        # See the xiaomi_home note above: bare ``mode`` is too greedy to match
        # as a suffix and does not mean the sweep/mop distinction.
        "cleaning_mode_entity": ("sweep_mop_type", "sweep_type", "clean_mode"),
        "mop_attached_sensor": ("mop_status", "sweep_mop_status"),
        "water_box_attached_sensor": (
            "host_water_tank_status",
            "water_tank_status",
            "water_check_status",
            "water_box_status",
        ),
        "water_shortage_sensor": ("water_shortage_status",),
        "dock_clean_water_sensor": ("base_station_water_tank_status",),
        "dock_dirty_water_sensor": ("sewage_tank_status",),
    },
    # This is the HACS integration maintained at Tasshack/dreame-vacuum, not
    # an HA Core integration.  The aliases are its documented entity keys.
    "dreame_vacuum": {
        # ``state`` includes WASHING/RETURNING_WASHING; ``status`` does not.
        # Tuple order is a preference order, not an unordered alias bag.
        "status_sensor": ("state", "status", "task_status"),
        "area_sensor": ("cleaned_area",),
        "duration_sensor": ("cleaning_time",),
        "mop_intensity_entity": ("water_volume", "mop_pad_humidity"),
        "cleaning_mode_entity": ("cleaning_mode",),
        "mop_attached_sensor": ("mop_pad",),
        "water_box_attached_sensor": ("water_tank",),
        "dock_status_sensor": ("self_wash_base_status",),
        "dock_error_sensor": ("error",),
    },
    # Valetudo publishes these canonical, retained signals through HA MQTT
    # discovery.  Options for Water and Mode remain model-specific.
    "valetudo": {
        "status_sensor": ("status", "robot_state"),
        "area_sensor": ("current_statistics_area",),
        "duration_sensor": ("current_statistics_time",),
        "mop_intensity_entity": ("water", "water_grade", "water_usage_control"),
        "cleaning_mode_entity": ("mode", "operation_mode"),
        "mop_attached_sensor": ("mop",),
        "water_box_attached_sensor": ("watertank",),
        "dock_clean_water_sensor": ("water_tank_clean", "freshwater"),
        "dock_dirty_water_sensor": ("water_tank_dirty", "wastewater"),
        "dock_status_sensor": ("dock_status",),
    },
}


# Integrations whose entities carry a canonical MIoT property name rather than
# a Home Assistant ``translation_key``.
MIOT_ADAPTERS: frozenset[str] = frozenset({"xiaomi_home", "xiaomi_miot"})


# Runtime behavior that is part of an integration contract rather than a
# model profile.  Known adapters fail closed when they cannot prove that a mop
# is active; this prevents vacuum-only runs from consuming virtual water.
#
# ``mop_intensity_is_evidence`` is deliberately limited to the MIoT adapters,
# whose ``mop_intensity_entity`` is a real water-output control.  Elsewhere the
# same role is bound to something that says nothing about water: Roomba maps it
# to ``fan_speed``, and Ecovacs' ``water_amount`` has no "off" option, so a
# vacuum-only run would otherwise be billed as mopping.
ADAPTER_DESCRIPTOR_METADATA: dict[str, dict[str, Any]] = {
    adapter: {
        "mop_evidence_required": True,
        "signal_contract_version": 1,
        **({"mop_intensity_is_evidence": True} if adapter in MIOT_ADAPTERS else {}),
    }
    for adapter in ADAPTER_ROLE_IDENTIFIERS
}


# Some integrations publish session data as documented attributes of the
# vacuum entity instead of separate registry entities.  These bindings remain
# canonical machine keys; no localized friendly-name matching is involved.
ADAPTER_ATTRIBUTE_BINDINGS: dict[str, dict[str, Any]] = {
    "roomba": {
        "area_attribute": "cleaned_area",
        # Core returns m² for metric HA installations and ft² otherwise.
        "area_attribute_unit": "ha_unit_system",
        "duration_attribute": "cleaning_time",
        "duration_attribute_unit": "min",
        "mop_intensity_attribute": "fan_speed",
        "water_box_attached_attribute": "tank_present",
        # Core calls these robot/dock tank levels but does not distinguish
        # clean/dirty water for every model.  A model profile must opt in
        # before either percentage becomes authoritative telemetry.
        "tank_semantics_confirmed": False,
    },
}


# Matching is suffix-based and always prefers the longest property, so
# ``base-station-water-tank-status`` can never be shortened into
# ``water-tank-status`` or ``status``.
_MIOT_PROPERTY_ROLES: dict[str, dict[str, str]] = {
    adapter: {
        prop: role
        for role, props in ADAPTER_ROLE_IDENTIFIERS[adapter].items()
        for prop in props
    }
    for adapter in MIOT_ADAPTERS
}

# ``_p_<siid>_<piid>`` is appended by xiaomi_home; a bare ``_<piid>`` is left by
# al-one's unique_id.  Both are stripped before the property is matched.
# The trailing ``_<n>`` covers Home Assistant's collision suffix, appended when
# a generated entity_id is already taken.
_MIOT_ENTITY_SUFFIX = re.compile(r"_p_\d+_\d+(?:_\d+)?$")
_MIOT_PIID_SUFFIX = re.compile(r"_\d+$")

# Segments that turn a per-run property into a lifetime counter.  MIoT exposes
# ``statistical-clean-area`` and ``total-clean-time`` beside the current-run
# values, and a suffix match alone would accept them as the current run —
# reading a monotonically growing total as a single session.
_MIOT_AGGREGATE_MARKERS = frozenset(
    {
        "total",
        "statistical",
        "statistics",
        "historical",
        "history",
        "accumulated",
        "lifetime",
        "all",
    }
)


def miot_property_for(values: Any, adapter: Any) -> str | None:
    """Return the longest canonical MIoT property named by any given value."""
    return _miot_match(values, adapter)[0]


def _miot_match(values: Any, adapter: Any) -> tuple[str | None, int]:
    """Return the best MIoT property and how much text precedes it.

    ``values`` are raw registry fields (translation_key, unique_id, entity_id).
    Preferring the longest match keeps distinct reservoirs apart: the dock tank,
    the robot tank and the plain run status all end in ``status``.

    The second element counts the segments before the property.  Entities of one
    device share the same generated prefix, so a smaller count means a cleaner
    match: ``..._ov42gl_status_p_2_2`` beats ``..._ov42gl_task_status_p_2_9``
    for the run-status role without either of them being discarded as a tie.
    """
    properties = _MIOT_PROPERTY_ROLES.get(_normalize(adapter))
    if not properties:
        return None, 0
    best: str | None = None
    best_depth = 0
    for value in values if isinstance(values, (list, tuple, set)) else (values,):
        candidate = _normalize(value)
        if not candidate:
            continue
        candidate = _MIOT_ENTITY_SUFFIX.sub("", candidate)
        candidate = _MIOT_PIID_SUFFIX.sub("", candidate)
        if not candidate:
            continue
        for prop in properties:
            if candidate == prop:
                head = ""
            elif candidate.endswith(f"_{prop}"):
                head = candidate[: -len(prop) - 1]
            else:
                continue
            if head.rsplit("_", 1)[-1] in _MIOT_AGGREGATE_MARKERS:
                continue
            depth = len(head.split("_")) if head else 0
            if best is None or len(prop) > len(best):
                best = prop
                best_depth = depth
            elif prop == best and depth < best_depth:
                best_depth = depth
    return best, best_depth


def miot_role_rank_for(values: Any, adapter: Any) -> tuple[str | None, int, int]:
    """Return the role named by a MIoT property, its rank and its match depth.

    Rank mirrors the tuple order in ``ADAPTER_ROLE_IDENTIFIERS``: earlier
    entries are the better signal for that role, so a device exposing both
    ``sweep_mop_type`` and ``clean_mode`` resolves to the former instead of
    falling through to an entity-id length tie-break.  Depth separates a clean
    property match from one that merely ends with the same word.
    """
    prop, depth = _miot_match(values, adapter)
    if prop is None:
        return None, 0, 0
    adapter_key = _normalize(adapter)
    role = _MIOT_PROPERTY_ROLES.get(adapter_key, {}).get(prop)
    if role is None:
        return None, 0, 0
    props = ADAPTER_ROLE_IDENTIFIERS.get(adapter_key, {}).get(role, ())
    return role, props.index(prop) if prop in props else 0, depth


def adapter_for(platform: Any, manufacturer: Any = None, unique_id: Any = None) -> str:
    """Return the narrow adapter key without guessing from friendly names."""
    platform_key = _normalize(platform)
    manufacturer_key = _normalize(manufacturer)
    unique_key = _normalize(unique_id)
    if platform_key == "mqtt" and (
        "valetudo" in manufacturer_key or "valetudo" in unique_key
    ):
        return "valetudo"
    return platform_key


def _normalize(value: Any) -> str:
    return "_".join(
        part for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in str(value or "")
        ).split()
        if part
    )
