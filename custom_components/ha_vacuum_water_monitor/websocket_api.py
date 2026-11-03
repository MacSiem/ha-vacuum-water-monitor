"""WebSocket API for Vacuum Water Monitor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DATA_TICKER, DOMAIN, EVENT_STATE_CHANGED, signal_vacuum_water_updated
from .storage import THRESHOLD_KEYS, VacuumWaterStorage
from .tick import list_vacuums
from .sensor_calculations import build_vacuum_devices, resolve_linked_programs
from .calibration import build_contribution_draft, select_recorded_cycle

_LOGGER = logging.getLogger(__name__)


def _request_entities(msg: dict[str, Any]) -> set[str]:
    """Find robot references in a public request without trusting a client scope."""
    result: set[str] = set()
    def scan(value):
        if isinstance(value, str):
            if value.startswith("entity:vacuum."):
                result.add(value[7:])
            elif value.startswith("vacuum."):
                result.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                scan(key)
                scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)
    scan(msg.get("vacuum_entity"))
    scan(msg.get("target"))
    scan(msg.get("patch"))
    patch = msg.get("patch") or {}
    if isinstance(patch, dict) and isinstance(patch.get("refill_config"), dict):
        result.update(key if key.startswith("vacuum.") else "vacuum." + key
                      for key in patch["refill_config"] if isinstance(key, str) and key)
    return result


def _request_source_entities(msg: dict[str, Any]) -> set[str]:
    """Collect actual source bindings for native HA read authorization."""
    import re
    result = set()
    def visit(value, binding=False):
        if isinstance(value, str):
            if binding and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", value) and not value.startswith("vacuum."):
                result.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                key = str(key)
                visit(item, binding or key.endswith(("_sensor", "_entity")) or key in
                      ("signal_overrides", "button_entity", "lid_entity", "signals"))
        elif isinstance(value, list):
            for item in value:
                visit(item, binding)
    visit(msg.get("patch"))
    visit({key: msg.get(key) for key in ("button_entity", "lid_entity")})
    return result


def _shared_tank(state: dict[str, Any]) -> dict[str, Any]:
    """Live balance only, without a measurement bank or origin details."""
    fields = ("initialized", "used_ml", "accounting_incomplete", "water_empty_active", "last_reset_ts",
              "last_reset_iso", "last_water_volume_ml", "last_status")
    result = {key: state[key] for key in fields if key in state}
    physical = state.get("accounting_v2")
    if isinstance(physical, dict):
        result["accounting_v2"] = {key: physical[key] for key in ("status", "balances_ml") if key in physical}
    return result


async def _filtered_result(hass, user_id, value):
    """Do not return another robot's stored state through aggregate endpoints."""
    from copy import deepcopy
    from .feature_access import check_access
    value = deepcopy(value)
    if not isinstance(value, dict):
        return value
    stored = await _storage(hass).async_get_state()
    policy = (stored.get("settings") or {}).get("feature_access", {"schema": 1, "features": {}})
    known = {v.get("entity_id") for v in list_vacuums(hass) if isinstance(v, dict)}
    known.update((stored.get("tank_states") or {}).keys())
    known.update(d.get("vacuum_entity") for key in ("configured_devices", "user_devices")
                 for d in (stored.get("settings", {}).get(key) or []) if isinstance(d, dict))
    links = (stored.get("settings") or {}).get("robot_links") or {}
    if isinstance(links, dict):
        known.update(entity for entity in links if isinstance(entity, str) and entity.startswith("vacuum."))
        known.update(target for target in links.values() if isinstance(target, str) and target.startswith("vacuum."))
    known.discard(None)
    allowed = {entity for entity in known if isinstance(entity, str)
               and await check_access(hass, user_id, "water", "read", (entity,), policy=policy)}
    measurements = {entity for entity in allowed
                    if await check_access(hass, user_id, "measurements", "read", (entity,), policy=policy)}
    settings_allowed = {entity for entity in allowed
                        if await check_access(hass, user_id, "settings", "read", (entity,), policy=policy)}
    def settings_filter(settings):
        if not isinstance(settings, dict):
            return settings
        settings.pop("feature_access", None)
        for key in ("configured_devices", "user_devices"):
            if isinstance(settings.get(key), list):
                settings[key] = [x if x.get("vacuum_entity") in settings_allowed else
                                 {field: x[field] for field in ("vacuum_entity", "name") if field in x}
                                 for x in settings[key] if isinstance(x, dict) and x.get("vacuum_entity") in allowed]
        keyed = ("refill_config", "refill_settings", "device_options", "sessions", "measurement_plans",
                 "local_measurements", "consumption_calibrations", "signal_overrides", "robot_links")
        for key in keyed:
            if not isinstance(settings.get(key), dict):
                continue
            permitted = measurements if key in ("local_measurements", "consumption_calibrations", "measurement_plans") else settings_allowed
            settings[key] = {k: v for k, v in settings[key].items() if
                (k if str(k).startswith("vacuum.") else "vacuum." + str(k)) in permitted
                and (key != "robot_links" or v == "distinct" or v in allowed)}
        if isinstance(settings.get("custom_calibration"), dict):
            settings["custom_calibration"] = {k: v for k, v in settings["custom_calibration"].items()
                if (str(k).removeprefix("entity:") in measurements if str(k).startswith(("vacuum.", "entity:vacuum."))
                    else bool(allowed) and allowed == measurements and allowed == known)}
        return settings
    if "settings" in value:
        value["settings"] = settings_filter(value["settings"])
    value.pop("entity_origins", None)
    value.pop("identity_unavailable_origins", None)
    if isinstance(value.get("tank_states"), dict):
        value["tank_states"] = {k: v for k, v in value["tank_states"].items() if k in allowed}
    if isinstance(value.get("vacuum_aliases"), dict):
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        value["vacuum_aliases"] = {old: target for old, target in value["vacuum_aliases"].items()
            if target in allowed and (old in allowed or (registry.async_get(old) is None and hass.states.get(old) is None))}
    if isinstance(value.get("tank_states"), dict):
        value["tank_states"] = {entity: (tank if entity in measurements else _shared_tank(tank))
                                for entity, tank in value["tank_states"].items()}
    if isinstance(value.get("state"), dict):
        owner = value.get("vacuum_entity")
        if owner not in allowed:
            value.pop("state")
        elif owner not in measurements:
            value["state"] = _shared_tank(value["state"])
    if not await check_access(hass, user_id, "settings", "read", policy=policy) and isinstance(value.get("settings"), dict):
        safe = {"configured_devices", "user_devices", "robot_links", "warning_threshold", "critical_threshold"}
        if await check_access(hass, user_id, "measurements", "read", policy=policy):
            safe.update({"local_measurements", "consumption_calibrations", "measurement_plans", "custom_calibration",
                         "calibration_sharing", "sharing_intro_choice"})
        value["settings"] = {key: value["settings"][key] for key in safe if key in value["settings"]}
    for key in ("vacuums", "robots"):
        if isinstance(value.get(key), list):
            value[key] = [v for v in value[key] if isinstance(v, dict)
                          and (v.get("entity_id") or v.get("vacuum_entity")) in allowed]
    for report in value.get("robots") or []:
        if report.get("vacuum_entity") not in measurements:
            for key in ("last_tank", "recent_errors_percent", "typical_error_percent", "calibration_factor", "calibration_samples"):
                report.pop(key, None)
            if isinstance(report.get("supply"), dict):
                for key in ("water_per_cleaning_ml", "water_per_day_ml", "basis_runs"):
                    report["supply"].pop(key, None)
        if report.get("vacuum_entity") not in settings_allowed:
            for key in ("capacity_source", "model_capacity_ml", "profile_key", "integration"):
                report.pop(key, None)
    if isinstance(value.get("registry_identity_conflicts"), list):
        value["registry_identity_conflicts"] = [{k: v for k, v in item.items() if k != "entity_origin"}
            for item in value["registry_identity_conflicts"]
            if isinstance(item, dict) and item.get("entity_id") in allowed]
    if isinstance(value.get("ambiguous_vacuum_ids"), list):
        # A retired id can remain ambiguous after the other robot moves away.
        # The original owner still needs the warning even though that id is
        # no longer a currently discoverable vacuum.
        from . import _vacuum_registry_identities
        current_identities = _vacuum_registry_identities(hass)
        ambiguous_origins = ((_storage(hass)._data or {}).get("ambiguous_vacuum_identities") or {})
        principal = await hass.auth.async_get_user(user_id)
        value["ambiguous_vacuum_ids"] = [entity for entity in value["ambiguous_vacuum_ids"]
            if entity in allowed or (principal is not None and principal.is_admin)
            or (ambiguous_origins.get(entity) is not None and any(
                identity == ambiguous_origins[entity] and current in allowed
                for current, identity in current_identities.items()))]
    if isinstance(value.get("balance_links"), dict):
        value["balance_links"] = {k: v for k, v in value["balance_links"].items()
                                   if k in allowed and (v == "distinct" or v in allowed)}
    # A robot permission does not imply permission to read its source sensors.
    # Preserve the robot while suppressing unauthorized source entity IDs.
    import re
    from homeassistant.auth.permissions.const import POLICY_READ
    user = await hass.auth.async_get_user(user_id)
    def scrub_sources(item, binding=False):
        if isinstance(item, str) and binding and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", item) and not item.startswith("vacuum."):
            return item if user is not None and user.permissions.check_entity(item, POLICY_READ) else None
        if isinstance(item, dict):
            return {key: scrub_sources(child, binding or str(key).endswith(("_sensor", "_entity")) or str(key) in
                    ("signal_overrides", "button_entity", "lid_entity", "signals")) for key, child in item.items()}
        if isinstance(item, list):
            return [scrub_sources(child, binding) for child in item]
        return item
    return scrub_sources(value)


def _response_entity_ids(result: Any) -> set[str]:
    if not isinstance(result, dict):
        return set()
    found = set((result.get("tank_states") or {}).keys())
    for key in ("vacuums", "robots"):
        found.update(item.get("entity_id") or item.get("vacuum_entity")
                     for item in (result.get(key) or []) if isinstance(item, dict))
    settings = result.get("settings") or {}
    if isinstance(settings, dict):
        for key in ("configured_devices", "user_devices"):
            found.update(item.get("vacuum_entity") for item in (settings.get(key) or []) if isinstance(item, dict))
        for key in ("refill_config", "refill_settings", "device_options", "sessions", "measurement_plans",
                    "local_measurements", "consumption_calibrations", "signal_overrides", "robot_links", "custom_calibration"):
            mapping = settings.get(key)
            if not isinstance(mapping, dict):
                continue
            for entity in mapping:
                if not isinstance(entity, str):
                    continue
                entity = entity.removeprefix("entity:")
                if key == "refill_config" and not entity.startswith("vacuum."):
                    entity = "vacuum." + entity
                if entity.startswith("vacuum."):
                    found.add(entity)
    if isinstance(result.get("vacuum_aliases"), dict):
        found.update(result["vacuum_aliases"].values())
    if isinstance(result.get("state"), dict):
        found.add(result.get("vacuum_entity"))
    return {entity for entity in found if isinstance(entity, str) and entity.startswith("vacuum.")}


def _authorize(feature: str, operation: str):
    """Recheck the real caller before read, before Store IO, and before reply."""
    from functools import wraps
    def decorate(handler):
        @wraps(handler)
        async def wrapped(hass, connection, msg):
            from .feature_access import check_access, check_native_read, reset_write_guard, set_write_guard
            user_id = getattr(getattr(connection, "user", None), "id", None)
            if user_id is None:
                connection.send_error(msg["id"], "unauthorized", "Access denied")
                return
            entities = _request_entities(msg)
            initial_settings = (await _storage(hass).async_get_state()).get("settings") or {}
            initial_policy = initial_settings.get("feature_access")
            if msg.get("type") == f"{DOMAIN}/refresh_bindings":
                # A scoped administrator-authorized user may retry an internal
                # refresh when at least one of their robots remains actionable.
                for device in list_vacuums(hass):
                    entity = device.get("entity_id")
                    if entity and await check_access(hass, user_id, "settings", "execute", (entity,)):
                        entities.add(entity)
                        break
            features = {feature}
            if msg.get("type") == f"{DOMAIN}/set_settings":
                patch = msg.get("patch") or {}
                measurement_keys = {"custom_calibration", "local_measurements", "consumption_calibrations",
                                    "measurement_plans", "calibration_sharing", "sharing_intro_choice"}
                if set(patch) & measurement_keys:
                    features.add("measurements")
                    if not set(patch) - measurement_keys:
                        features.discard("settings")
            source_entities = _request_source_entities(msg)
            if not await check_native_read(hass, user_id, source_entities):
                connection.send_error(msg["id"], "unauthorized", "Access denied")
                return
            if msg.get("vacuum_entity"):
                from .robots import resolve_balance_owner
                entities.add(resolve_balance_owner(hass, await _storage(hass).async_get_state(), msg["vacuum_entity"]))
            if not all([await check_access(hass, user_id, item, operation, entities) for item in features]):
                connection.send_error(msg["id"], "unauthorized", "Access denied")
                return
            if msg.get("type") == f"{DOMAIN}/set_settings":
                user = await hass.auth.async_get_user(user_id)
                stored = await _storage(hass).async_get_state()
                policy = (stored.get("settings") or {}).get("feature_access") or {}
                if user is not None and not user.is_admin:
                    patch = msg.get("patch") or {}
                    scoped = {"configured_devices", "user_devices", "robot_links", "refill_config",
                              "refill_settings", "device_options", "sessions", "signal_overrides", "custom_calibration"}
                    calibration = patch.get("custom_calibration") or {}
                    for item in features:
                        rule = policy.get("features", {}).get(item, {}).get("execute", {})
                        if "entity_ids" in rule and (not msg.get("partial", False) or not entities or set(patch) - scoped or not isinstance(calibration, dict)
                                or any(not str(key).startswith(("vacuum.", "entity:vacuum.")) for key in calibration)):
                            connection.send_error(msg["id"], "unauthorized", "An entity-scoped rule cannot change global settings")
                            return
            class Buffered:
                def __init__(self, original):
                    self.original, self.response = original, None
                def __getattr__(self, name):
                    return getattr(self.original, name)
                def send_result(self, identity, result=None):
                    self.response = ("result", identity, result)
                def send_error(self, identity, code, message):
                    self.response = ("error", identity, code, message)
            buffered = Buffered(connection)
            route_sources = ((msg["vacuum_entity"],) if msg.get("type") in
                             (f"{DOMAIN}/reset_tank", f"{DOMAIN}/mark_empty") and msg.get("vacuum_entity") else ())
            token = set_write_guard(user_id, tuple(features), entities, read_entities=source_entities,
                                    route_sources=route_sources, fence_policy=True,
                                    policy_snapshot=initial_policy) if operation == "execute" else None
            try:
                await handler(hass, buffered, msg)
            finally:
                if token is not None:
                    reset_write_guard(token)
            if buffered.response is None:
                return
            if buffered.response[0] == "error":
                connection.send_error(*buffered.response[1:])
                return
            result = await _filtered_result(hass, user_id, buffered.response[2])
            latest = (await _storage(hass).async_get_state()).get("settings") or {}
            if latest.get("feature_access") != initial_policy:
                connection.send_error(msg["id"], "unauthorized", "Access changed; retry")
                return
            if (not all([await check_access(hass, user_id, item, operation, entities) for item in features])
                    or not await check_native_read(hass, user_id, source_entities)):
                connection.send_error(msg["id"], "unauthorized", "Access denied")
                return
            # One fresh principal and the current policy, then no intervening
            # await before sending the aggregate result. HA access can change
            # independently of the VWM policy during the earlier awaits.
            from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
            from .feature_access import default_feature_access, feature_access_allowed, policy_for_registry
            user = await hass.auth.async_get_user(user_id)
            raw_settings = (_storage(hass)._data or {}).get("settings") or {}
            current_policy = raw_settings.get("feature_access")
            if user is None or not user.is_active or current_policy != initial_policy:
                connection.send_error(msg["id"], "unauthorized", "Access changed; retry")
                return
            policy = current_policy if current_policy is not None else default_feature_access()
            try:
                policy = policy_for_registry(hass, policy)
                required = POLICY_CONTROL if operation == "execute" else POLICY_READ
                if any(not feature_access_allowed(policy, item, operation, user_id=user.id,
                           is_active=user.is_active, is_admin=user.is_admin, entity_id=entity)
                       or not user.permissions.check_entity(entity, required)
                       for item in features for entity in entities):
                    connection.send_error(msg["id"], "unauthorized", "Access changed; retry")
                    return
                response_sources = _request_source_entities({"patch": result})
                if any(not user.permissions.check_entity(entity, POLICY_READ) for entity in source_entities | response_sources):
                    connection.send_error(msg["id"], "unauthorized", "Access changed; retry")
                    return
                if any(not feature_access_allowed(policy, "water", "read", user_id=user.id,
                           is_active=user.is_active, is_admin=user.is_admin, entity_id=entity)
                       or not user.permissions.check_entity(entity, POLICY_READ)
                       for entity in _response_entity_ids(result)):
                    connection.send_error(msg["id"], "unauthorized", "Access changed; retry")
                    return
            except (ValueError, AttributeError, TypeError):
                connection.send_error(msg["id"], "unauthorized", "Access denied")
                return
            # Re-project private fields against the final principal, not the
            # earlier async filtering decisions. No await may follow this.
            def can_read(feature, entity):
                return (isinstance(entity, str)
                        and feature_access_allowed(policy, feature, "read", user_id=user.id,
                            is_active=user.is_active, is_admin=user.is_admin, entity_id=entity)
                        and user.permissions.check_entity(entity, POLICY_READ))
            if isinstance(result, dict):
                if isinstance(result.get("ambiguous_vacuum_ids"), list) and not user.is_admin:
                    from . import _vacuum_registry_identities
                    identities = _vacuum_registry_identities(hass)
                    originals = ((_storage(hass)._data or {}).get("ambiguous_vacuum_identities") or {})
                    result["ambiguous_vacuum_ids"] = [entity for entity in result["ambiguous_vacuum_ids"]
                        if can_read("water", entity) or (originals.get(entity) is not None and any(
                            identity == originals[entity] and can_read("water", current)
                            for current, identity in identities.items()))]
                for key in ("vacuums", "robots"):
                    for item in result.get(key) or []:
                        if not isinstance(item, dict):
                            continue
                        for ref in ("balance_owner", "possible_duplicate_of"):
                            if item.get(ref) and not can_read("water", item[ref]):
                                item.pop(ref, None)
                        if isinstance(item.get("duplicate_entities"), list):
                            item["duplicate_entities"] = [ref for ref in item["duplicate_entities"] if can_read("water", ref)]
                        entity = item.get("vacuum_entity") or item.get("entity_id")
                        if key == "robots" and not can_read("measurements", entity):
                            for field in ("last_tank", "recent_errors_percent", "typical_error_percent", "calibration_factor", "calibration_samples"):
                                item.pop(field, None)
                            if isinstance(item.get("supply"), dict):
                                for field in ("water_per_cleaning_ml", "water_per_day_ml", "basis_runs"):
                                    item["supply"].pop(field, None)
                        if key == "robots" and not can_read("settings", entity):
                            for field in ("capacity_source", "model_capacity_ml", "profile_key", "integration"):
                                item.pop(field, None)
                tanks = result.get("tank_states")
                if isinstance(tanks, dict):
                    result["tank_states"] = {entity: tank if can_read("measurements", entity) else _shared_tank(tank)
                                             for entity, tank in tanks.items()}
                owner = result.get("vacuum_entity") or msg.get("vacuum_entity")
                if msg.get("type") == f"{DOMAIN}/save_measurement" and not can_read("measurements", owner):
                    result.pop("calibration", None)
                    result.pop("sample_count", None)
                if isinstance(result.get("state"), dict) and not can_read("measurements", owner):
                    result["state"] = _shared_tank(result["state"])
                settings_result = result.get("settings")
                if isinstance(settings_result, dict):
                    if not feature_access_allowed(policy, "settings", "read", user_id=user.id,
                            is_active=user.is_active, is_admin=user.is_admin):
                        safe = {"configured_devices", "user_devices", "robot_links", "warning_threshold", "critical_threshold"}
                        if feature_access_allowed(policy, "measurements", "read", user_id=user.id,
                                is_active=user.is_active, is_admin=user.is_admin):
                            safe.update({"local_measurements", "consumption_calibrations", "measurement_plans",
                                         "custom_calibration", "calibration_sharing", "sharing_intro_choice"})
                        result["settings"] = settings_result = {k: v for k, v in settings_result.items() if k in safe}
                    all_robots = {item.get("entity_id") for item in list_vacuums(hass) if isinstance(item, dict) and item.get("entity_id")}
                    all_robots.update(((_storage(hass)._data or {}).get("tank_states") or {}).keys())
                    can_read_default = bool(all_robots) and all(can_read("measurements", entity) for entity in all_robots)
                    for key in ("local_measurements", "consumption_calibrations", "measurement_plans", "custom_calibration"):
                        mapping = settings_result.get(key)
                        if isinstance(mapping, dict):
                            settings_result[key] = {entity: data for entity, data in mapping.items()
                                if isinstance(entity, str) and (can_read("measurements", entity.removeprefix("entity:"))
                                    or (key == "custom_calibration" and entity == "default" and (user.is_admin or can_read_default)))}
                    for key in ("configured_devices", "user_devices"):
                        if isinstance(settings_result.get(key), list):
                            settings_result[key] = [item if can_read("settings", item.get("vacuum_entity")) else
                                {k: item[k] for k in ("vacuum_entity", "name") if k in item}
                                for item in settings_result[key] if isinstance(item, dict)]
                    for key in ("refill_config", "refill_settings", "device_options", "sessions", "signal_overrides", "robot_links"):
                        mapping = settings_result.get(key)
                        if isinstance(mapping, dict):
                            settings_result[key] = {entity: data for entity, data in mapping.items()
                                if can_read("settings", entity if str(entity).startswith("vacuum.") else "vacuum." + str(entity))}
            connection.send_result(buffered.response[1], result)
        return wrapped
    return decorate


def _storage(hass: HomeAssistant) -> VacuumWaterStorage:
    return hass.data[DOMAIN]["storage"]


def _entry_id(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        return entries[0].entry_id
    return DOMAIN


async def _refresh_bindings(hass: HomeAssistant) -> bool:
    """Adopt persisted signal/identity changes before acknowledging the write."""
    ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
    if ticker is None:
        return False
    from .feature_access import suspend_write_guard, reset_write_guard
    token = suspend_write_guard()
    try:
        return bool(await ticker.run(None))
    except Exception:  # The settings have already been saved.
        _LOGGER.exception("Settings saved, but signal bindings could not be refreshed")
        return False
    finally:
        reset_write_guard(token)


def _notify_store_updated(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    async_dispatcher_send(
        hass, signal_vacuum_water_updated(_entry_id(hass)), payload
    )
    # HA custom events are broadcast outside our per-user authorization.
    # Publish only change markers; authorized clients fetch their own view.
    event = {}
    if "settings" in payload:
        event["settings_changed"] = True
    if "tank_states" in payload:
        event["state_changed"] = True
    if payload.get("registry_rename") or payload.get("registry_changed"):
        event["registry_changed"] = True
    if payload.get("feature_access_changed"):
        event["feature_access_changed"] = True
    hass.bus.async_fire(EVENT_STATE_CHANGED, event)
    from .robots import async_schedule_issue_sync

    async_schedule_issue_sync(hass)


# Household commands are available to every authenticated HA user. Threshold
# changes mirror the administrator permission of the integration's HA options.
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@websocket_api.async_response
async def _ws_subscribe(hass, connection, msg):
    """Stream sanitized changes only while the current caller may read them."""
    from .feature_access import check_access
    user_id = getattr(getattr(connection, "user", None), "id", None)
    if user_id is None or not await check_access(hass, user_id, "water", "read"):
        connection.send_error(msg["id"], "unauthorized", "Access denied")
        return
    active = True
    tasks = set()
    async def deliver(data):
        nonlocal active
        if not active:
            return
        before = ((await _storage(hass).async_get_state()).get("settings") or {}).get("feature_access")
        if not await check_access(hass, user_id, "water", "read"):
            connection.send_event(msg["id"], {"access_revoked": True})
            unsubscribe()
            return
        filtered = {key: True for key in ("state_changed", "settings_changed", "registry_changed", "feature_access_changed")
                    if data.get(key) is True}
        visible = await _filtered_result(hass, user_id, {"vacuums": list_vacuums(hass)})
        user = await hass.auth.async_get_user(user_id)
        after = ((_storage(hass)._data or {}).get("settings") or {}).get("feature_access")
        if not active or before != after:
            # The policy's own event will deliver a fresh marker or revocation.
            return
        from homeassistant.auth.permissions.const import POLICY_READ
        from .feature_access import default_feature_access, feature_access_allowed, policy_for_registry
        policy = after if after is not None else default_feature_access()
        try:
            policy = policy_for_registry(hass, policy)
            if user is None or not user.is_active or not feature_access_allowed(
                    policy, "water", "read", user_id=user.id, is_active=user.is_active, is_admin=user.is_admin):
                connection.send_event(msg["id"], {"access_revoked": True})
                unsubscribe()
                return
            filtered["authorized_vacuums"] = [item["entity_id"] for item in visible.get("vacuums", [])
                if feature_access_allowed(policy, "water", "read", user_id=user.id, is_active=user.is_active,
                                          is_admin=user.is_admin, entity_id=item["entity_id"])
                and user.permissions.check_entity(item["entity_id"], POLICY_READ)]
        except (ValueError, AttributeError, TypeError):
            connection.send_event(msg["id"], {"access_revoked": True})
            unsubscribe()
            return
        connection.send_event(msg["id"], {"data": filtered})
    @callback
    def forward(event):
        task = hass.async_create_task(deliver(dict(event.data)))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    stop = hass.bus.async_listen(EVENT_STATE_CHANGED, forward)
    def unsubscribe():
        nonlocal active
        if active:
            active = False
            stop()
    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_feature_access"})
@websocket_api.async_response
async def _ws_get_feature_access(hass, connection, msg):
    from .feature_access import default_feature_access, effective_feature_capabilities, check_access
    user_id = connection.user.id
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_active:
        connection.send_error(msg["id"], "unauthorized", "Access denied")
        return
    settings = await _storage(hass).async_get_settings()
    policy = settings["feature_access"] if "feature_access" in settings else default_feature_access()
    try:
        resources = {}
        for device in list_vacuums(hass):
            entity = device.get("entity_id")
            if not isinstance(entity, str) or not await check_access(hass, user_id, "water", "visible", (entity,), policy=policy):
                continue
            resources[entity] = {feature: {operation: await check_access(hass, user_id, feature, operation, (entity,), policy=policy)
                                           for operation in ("visible", "read", "execute")}
                                 for feature in ("water", "settings", "measurements")}
        current = await _storage(hass).async_get_settings()
        if current.get("feature_access", default_feature_access()) != policy:
            connection.send_error(msg["id"], "feature_access_changed", "Access settings changed; retry")
            return
        user = await hass.auth.async_get_user(user_id)
        if user is None or not user.is_active:
            connection.send_error(msg["id"], "unauthorized", "Access denied")
            return
        latest_policy = ((_storage(hass)._data or {}).get("settings") or {}).get("feature_access", default_feature_access())
        if latest_policy != policy:
            connection.send_error(msg["id"], "feature_access_changed", "Access settings changed; retry")
            return
        from .feature_access import policy_for_registry
        effective_policy = policy_for_registry(hass, policy)
        caps = effective_feature_capabilities(effective_policy, user_id=user.id, is_active=user.is_active, is_admin=user.is_admin)
        # Native ACL can change while resource capabilities are being collected.
        # Recompute synchronously with the fresh principal before sending.
        from homeassistant.auth.permissions.const import POLICY_READ, POLICY_CONTROL
        from .feature_access import feature_access_allowed
        resources = {entity: {feature: {operation:
            feature_access_allowed(effective_policy, feature, operation, user_id=user.id, is_active=user.is_active,
                                   is_admin=user.is_admin, entity_id=entity)
            and user.permissions.check_entity(entity, POLICY_CONTROL if operation == "execute" else POLICY_READ)
            for operation in ("visible", "read", "execute")}
            for feature in ("water", "settings", "measurements")}
            for entity in resources
            if feature_access_allowed(effective_policy, "water", "visible", user_id=user.id, is_active=user.is_active,
                                      is_admin=user.is_admin, entity_id=entity)
            and user.permissions.check_entity(entity, POLICY_READ)}
    except (ValueError, AttributeError, TypeError):
        connection.send_error(msg["id"], "invalid_feature_access", "Access settings are invalid")
        return
    connection.send_result(msg["id"], {"capabilities": caps, "resources": resources,
                                       **({"policy": policy} if user.is_admin else {})})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/set_feature_access", vol.Required("policy"): dict})
@websocket_api.async_response
async def _ws_set_feature_access(hass, connection, msg):
    from .feature_access import validate_feature_access, set_write_guard, reset_write_guard
    user = await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_active or not user.is_admin:
        connection.send_error(msg["id"], "unauthorized", "Administrator required")
        return
    try:
        policy = validate_feature_access(msg["policy"])
        from . import _vacuum_registry_identities
        current = _vacuum_registry_identities(hass)
        previous = (await _storage(hass).async_get_settings()).get("feature_access") or {"features": {}}
        for feature, operations in policy["features"].items():
            for operation, rule in operations.items():
                if "entity_ids" not in rule:
                    continue
                prior = previous.get("features", {}).get(feature, {}).get(operation, {})
                old_bindings = prior.get("entity_identities", {})
                bindings = {}
                for entity in rule["entity_ids"]:
                    identity = old_bindings.get(entity) or current.get(entity)
                    if identity is None:
                        raise ValueError("Missing registry identity")
                    bindings[entity] = identity
                rule["entity_identities"] = bindings
    except ValueError:
        connection.send_error(msg["id"], "invalid_feature_access", "Access settings are invalid")
        return
    token = set_write_guard(user.id, "settings", (), admin=True)
    try:
        settings = await _storage(hass).async_set_settings({"feature_access": policy})
    finally:
        reset_write_guard(token)
    _notify_store_updated(hass, {"settings": settings, "feature_access_changed": True})
    user = await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_active or not user.is_admin:
        connection.send_error(msg["id"], "unauthorized", "Administrator required")
        return
    connection.send_result(msg["id"], {"policy": policy})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_vacuums"})
@websocket_api.async_response
@_authorize("water", "read")
async def _ws_list_vacuums(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return enriched HA vacuum descriptors."""
    stored = await _storage(hass).async_get_state()
    connection.send_result(msg["id"], _vacuum_list(hass, stored))


def _vacuum_list(hass: HomeAssistant, stored: dict[str, Any]) -> dict[str, Any]:
    """Describe the actual balance owner, using the same grouping as accounting."""
    settings = stored.get("settings") or {}
    discovered = list_vacuums(hass)
    devices = build_vacuum_devices(settings, stored.get("tank_states"), discovered)
    owners = {entity: device["vacuum_entity"] for device in devices
              for entity in [device["vacuum_entity"], *device.get("duplicate_entities", [])]}
    vacuums = resolve_linked_programs(discovered, settings)
    for vacuum in vacuums:
        vacuum["balance_owner"] = owners.get(vacuum["entity_id"], vacuum["entity_id"])
    return {"vacuums": vacuums, "balance_links": settings.get("robot_links") or {}}


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
@websocket_api.async_response
@_authorize("water", "read")
async def _ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return persisted settings and tank states."""
    connection.send_result(msg["id"], await _storage(hass).async_get_state())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_settings",
        vol.Required("patch"): dict,
        vol.Optional("partial", default=False): bool,
        vol.Optional("expected"): dict,
    }
)
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_set_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Patch persisted settings and keep the HA threshold options in sync."""
    if "feature_access" in msg["patch"]:
        connection.send_error(msg["id"], "unauthorized", "Use administrator access settings")
        return
    threshold_patch = any(key in msg["patch"] for key in THRESHOLD_KEYS)
    entry = None
    if threshold_patch:
        if not connection.user.is_admin:
            connection.send_error(msg["id"], "unauthorized", "Administrator required to change thresholds")
            return
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            connection.send_error(msg["id"], "invalid_payload", "Integration config entry is unavailable")
            return
        entry = entries[0]
    try:
        if "expected" in msg:
            settings = await _storage(hass).async_set_settings(msg["patch"], partial=msg.get("partial", False), expected=msg["expected"])
        elif msg.get("partial"):
            settings = await _storage(hass).async_set_settings(msg["patch"], partial=True)
        else:
            settings = await _storage(hass).async_set_settings(msg["patch"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    if entry is not None:
        options = {**entry.options, **{key: settings[key] for key in THRESHOLD_KEYS}}
        if options != entry.options:
            hass.config_entries.async_update_entry(entry, options=options)
    bindings_refreshed = None
    if any(key in msg["patch"] for key in ("configured_devices", "user_devices", "robot_links",
                                           "signal_overrides", "custom_calibration", "refill_config", "device_options")):
        bindings_refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings, "bindings_refreshed": bindings_refreshed})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/refresh_bindings"})
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_refresh_bindings(hass, connection, msg):
    """Retry refresh only; never repeat a previously saved action."""
    refreshed = await _refresh_bindings(hass)
    stored = await _storage(hass).async_get_state()
    connection.send_result(msg["id"], {"bindings_refreshed": refreshed, "settings": stored.get("settings") or {},
                                       **_vacuum_list(hass, stored)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_user_device",
        vol.Required("vacuum_entity"): str,
    }
)
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_remove_user_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Explicitly remove one manually-added device.

    Uses async_replace_settings_key so removing the last device (an empty
    list) is honored — the generic set_settings guard refuses empty-list
    patches to protect against accidental frontend init writes, but an
    explicit user delete is intentional.
    """
    storage = _storage(hass)
    settings = await storage.async_remove_user_device(msg["vacuum_entity"])
    bindings_refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(
        msg["id"], {"settings": settings, "removed": msg["vacuum_entity"], "bindings_refreshed": bindings_refreshed}
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/reprofile", vol.Required("vacuum_entity"): str})
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_reprofile(hass, connection, msg):
    """Explicitly refresh local profile settings; never call a vacuum service."""
    try:
        settings = await _storage(hass).async_reprofile(msg["vacuum_entity"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    bindings_refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    listing = _vacuum_list(hass, await _storage(hass).async_get_state())
    connection.send_result(msg["id"], {"settings": settings, "bindings_refreshed": bindings_refreshed, **listing})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reset_tank",
        vol.Required("vacuum_entity"): str,
    }
)
@websocket_api.async_response
@_authorize("water", "execute")
async def _ws_reset_tank(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reset a vacuum tank counter."""
    if not msg["vacuum_entity"].startswith("vacuum.") or hass.states.get(msg["vacuum_entity"]) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    from .robots import async_mark_refilled_with_owner

    owner, state = await async_mark_refilled_with_owner(hass, msg["vacuum_entity"], "card")
    connection.send_result(msg["id"], {"state": state, "vacuum_entity": owner})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dismiss_intro",
        vol.Required("tag"): str,
    }
)
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_dismiss_intro(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist dismissed intro banner state."""
    current = await _storage(hass).async_get_settings()
    dismissed = dict(current.get("intro_dismissed") or {})
    dismissed[msg["tag"]] = True
    settings = await _storage(hass).async_set_settings(
        {"intro_dismissed": dismissed}
    )
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/calibration_preview",
    vol.Required("vacuum_entity"): str,
    vol.Optional("session_index", default=0): vol.All(int, vol.Range(min=0, max=49)),
    vol.Required("session_ts"): int,
    vol.Optional("observed_ml"): vol.Any(int, float),
    vol.Optional("resolution_ml"): vol.Any(int, float),
})
@websocket_api.async_response
@_authorize("measurements", "read")
async def _ws_calibration_preview(hass, connection, msg):
    """Read one stored cycle and return an allowlisted draft without saving it."""
    vacuum = msg["vacuum_entity"]
    if not vacuum.startswith("vacuum.") or hass.states.get(vacuum) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    current = await _storage(hass).async_get_state()
    sessions = current.get("tank_states", {}).get(vacuum, {}).get("automatic_sessions", [])
    index = msg.get("session_index", 0)
    try:
        record = select_recorded_cycle(sessions, index, msg["session_ts"])
        draft = build_contribution_draft(record, msg.get("observed_ml"), msg.get("resolution_ml"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    connection.send_result(msg["id"], draft)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/contribution_preview",
    vol.Required("vacuum_entity"): str,
    vol.Required("sample_ids"): vol.All([str], vol.Length(min=1, max=50)),
})
@websocket_api.async_response
@_authorize("measurements", "read")
async def _ws_contribution_preview(hass, connection, msg):
    """Project selected saved confirmations locally; never transmit or approve."""
    from .contribution import build_confirmed_contribution
    from .profiles import CATALOG
    vacuum = msg["vacuum_entity"]
    if not vacuum.startswith("vacuum.") or hass.states.get(vacuum) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    current = await _storage(hass).async_get_state()
    stored = current.get("settings", {}).get("local_measurements", {}).get(vacuum, [])
    from .storage import measurement_belongs, measurement_identity
    origin, proven = measurement_identity(current, vacuum)
    try:
        if len(set(msg["sample_ids"])) != len(msg["sample_ids"]):
            raise ValueError("Select distinct saved measurements")
        selected = []
        for identity in msg["sample_ids"]:
            matches = [s for s in stored if isinstance(s, dict) and s.get("id") == identity]
            if len(matches) != 1 or not measurement_belongs(matches[0], origin, proven):
                raise ValueError("Saved measurement changed; select it again")
            selected.append({**matches[0], "device_id": origin})
        preview = build_confirmed_contribution(selected, public_catalog=CATALOG)
    except (ValueError, TypeError, OverflowError) as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    connection.send_result(msg["id"], preview)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_measurement_plan",
    vol.Required("vacuum_entity"): str,
    vol.Required("plan"): dict,
})
@websocket_api.async_response
@_authorize("measurements", "execute")
async def _ws_set_measurement_plan(hass, connection, msg):
    """Declare collection settings locally; never operate the robot or dock."""
    if hass.states.get(msg["vacuum_entity"]) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    try:
        settings = await _storage(hass).async_set_measurement_plan(msg["vacuum_entity"], msg["plan"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings":settings})
    connection.send_result(msg["id"], {"saved":True, "settings":settings, "bindings_refreshed": refreshed})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/save_measurement",
    vol.Required("vacuum_entity"): str,
    vol.Required("session_index"): vol.All(int, vol.Range(min=0, max=49)),
    vol.Required("session_ts"): int,
    vol.Required("measurement"): dict,
})
@websocket_api.async_response
@_authorize("measurements", "execute")
async def _ws_save_measurement(hass, connection, msg):
    """Save an explicitly confirmed local measurement, without uploading data."""
    vacuum = msg["vacuum_entity"]
    if not vacuum.startswith("vacuum.") or hass.states.get(vacuum) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    try:
        result = await _storage(hass).async_save_measurement(
            vacuum, msg["session_index"], msg["session_ts"], msg["measurement"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    result["bindings_refreshed"] = await _refresh_bindings(hass) if result.get("calibration") else None
    _notify_store_updated(hass, {"settings": await _storage(hass).async_get_settings()})
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_refill_settings",
        vol.Required("vacuum_entity"): str,
        vol.Optional("auto_refill"): vol.Any(None, bool),
        vol.Optional("button_entity"): vol.Any(None, str),
        vol.Optional("lid_entity"): vol.Any(None, str),
        vol.Optional("full_refill_practice_confirmed"): bool,
    }
)
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_set_refill_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Replace one vacuum's refill choices and bind them immediately."""
    try:
        settings = await _storage(hass).async_set_refill_settings(
            msg["vacuum_entity"],
            auto_refill=msg.get("auto_refill"),
            button_entity=msg.get("button_entity") or None,
            lid_entity=msg.get("lid_entity") or None,
            full_refill_practice_confirmed=msg.get("full_refill_practice_confirmed"),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings, "bindings_refreshed": refreshed})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/health"})
@websocket_api.async_response
@_authorize("water", "read")
async def _ws_health(hass, connection, msg):
    """One report per robot: tank size and source, accuracy, refill method, checks."""
    from .robots import async_reports

    connection.send_result(msg["id"], {"robots": await async_reports(hass)})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_device_options",
    vol.Required("vacuum_entity"): str,
    vol.Required("options"): dict,
})
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_set_device_options(hass, connection, msg):
    """Store a robot's options (tank size); ``null`` restores the default."""
    try:
        settings = await _storage(hass).async_set_device_options(msg["vacuum_entity"], msg["options"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings, "bindings_refreshed": refreshed})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/mark_empty",
    vol.Required("vacuum_entity"): str,
})
@websocket_api.async_response
@_authorize("water", "execute")
async def _ws_mark_empty(hass, connection, msg):
    """The robot ran out of water (robots whose dock cannot say so)."""
    from .robots import async_mark_empty_with_owner

    if not msg["vacuum_entity"].startswith("vacuum.") or hass.states.get(msg["vacuum_entity"]) is None:
        connection.send_error(msg["id"], "invalid_payload", "Select an existing vacuum entity")
        return
    try:
        owner, state = await async_mark_empty_with_owner(hass, msg["vacuum_entity"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    connection.send_result(msg["id"], {"state": state, "vacuum_entity": owner})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_robot_link",
    vol.Required("vacuum_entity"): str,
    vol.Required("target"): vol.Any(None, str),
})
@websocket_api.async_response
@_authorize("settings", "execute")
async def _ws_set_robot_link(hass, connection, msg):
    """Hide a duplicate robot (target = the real robot), keep it (\"distinct\") or forget (null)."""
    try:
        settings = await _storage(hass).async_set_robot_link(msg["vacuum_entity"], msg["target"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_payload", str(err))
        return
    refreshed = await _refresh_bindings(hass)
    _notify_store_updated(hass, {"settings": settings})
    connection.send_result(msg["id"], {"settings": settings, "bindings_refreshed": refreshed})


def async_register_commands(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for handler in (
        _ws_subscribe,
        _ws_get_feature_access,
        _ws_set_feature_access,
        _ws_list_vacuums,
        _ws_get_state,
        _ws_set_settings,
        _ws_refresh_bindings,
        _ws_remove_user_device,
        _ws_reprofile,
        _ws_reset_tank,
        _ws_set_refill_settings,
        _ws_dismiss_intro,
        _ws_calibration_preview,
        _ws_save_measurement,
        _ws_set_measurement_plan,
        _ws_contribution_preview,
        _ws_health,
        _ws_set_device_options,
        _ws_set_robot_link,
        _ws_mark_empty,
    ):
        websocket_api.async_register_command(hass, handler)
