"""Machine-readable signal aliases exposed by supported HA integrations.

The registry ``translation_key`` is preferred.  Display names are only a
last-resort match for integrations such as MQTT discovery that do not provide
translation keys.  Keeping the aliases here prevents localized UI text from
becoming accounting logic.
"""

from __future__ import annotations

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


# Runtime behavior that is part of an integration contract rather than a
# model profile.  Known adapters fail closed when they cannot prove that a mop
# is active; this prevents vacuum-only runs from consuming virtual water.
ADAPTER_DESCRIPTOR_METADATA: dict[str, dict[str, Any]] = {
    adapter: {"mop_evidence_required": True, "signal_contract_version": 1}
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
