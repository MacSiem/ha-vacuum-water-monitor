"""Read an explicitly configured DIY water counter without changing its data."""
from __future__ import annotations
import math
from typing import Any


def _external_state(hass: Any, entity_id: str | None) -> Any:
    if not entity_id:
        return None
    from homeassistant.helpers import entity_registry as er
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.platform == 'ha_vacuum_water_monitor':
        return None
    return hass.states.get(entity_id)


def _volume(hass: Any, entity_id: str | None, default_unit: str) -> float | None:
    state = _external_state(hass, entity_id)
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    unit = str((state.attributes or {}).get('unit_of_measurement') or default_unit).strip().lower()
    if not math.isfinite(value) or value < 0 or unit not in ('ml', 'l'):
        return None
    return value * 1000 if unit == 'l' else value


def project_external_counter(hass: Any, device: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Project helper values in mL; never write Store or the user's helper.

    An explicit counter or remaining sensor enables DIY mode. A remaining sensor wins
    for remaining volume; the used sensor wins over the input for used volume.
    Invalid/unavailable sources are unknown, never stale Store values.
    """
    helper = device.get('water_used_input')
    if not any(device.get(key) for key in ('water_used_input', 'water_used_sensor', 'water_sensor')):
        return None
    used = _volume(hass, device.get('water_used_sensor') or helper, 'ml')
    remaining_id = device.get('water_sensor')
    remaining = _volume(hass, remaining_id, 'l') if remaining_id else None
    if remaining_id:
        from .sensor_calculations import water_capacity
        total, _source = water_capacity(device, settings or {})
        if remaining is not None and total is not None and remaining > total:
            remaining = None
        used = max(0, total - remaining) if remaining is not None and total is not None else None
    return {'used_ml': used, 'remaining_ml': remaining, 'remaining_sensor': bool(remaining_id),
            **project_auxiliary(hass, device)}


def project_auxiliary(hass: Any, device: dict[str, Any]) -> dict[str, Any]:
    session = _volume(hass, device.get('last_session_sensor'), 'ml') if device.get('last_session_sensor') else None
    reset = _external_state(hass, device.get('last_reset_entity'))
    reset_value = reset.state if reset and reset.state not in ('unknown', 'unavailable', '') else None
    return {'last_session_ml': session, 'last_reset': reset_value}


def source_entities(device: dict[str, Any]) -> set[str]:
    return {value for key in ('water_used_input', 'water_used_sensor', 'water_sensor',
                              'last_session_sensor', 'last_reset_entity')
            if isinstance((value := device.get(key)), str) and value}


def apply_external_view(tank: dict[str, Any], projection: dict[str, Any]) -> None:
    """Neutralize old live-accounting markers in a disposable read projection."""
    tank.update(external_counter=projection, used_ml=projection.get('used_ml'),
                initialized=projection.get('used_ml') is not None or projection.get('remaining_ml') is not None,
                last_reset_iso=projection.get('last_reset'), last_reset_ts=0,
                last_water_volume_ml=None, accounting_incomplete=False, water_empty_active=False,
                water_anchor_kind=None, water_anchor_confidence=None, water_anchor_source=None,
                last_accounting_reason=None, last_accounting_source='external_counter',
                last_accounting_evidence='external_counter', nominal_time_resolution={},
                cycle_full_confirmed=False, cycle_full_confirmation_source=None,
                whole_cycle_fallback_reason=None, cycle_action_totals={})
