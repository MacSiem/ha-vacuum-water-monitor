"""Store-backed persistence for Vacuum Water Monitor."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .refill import REFILL_SOURCES, USER_REFILL_DEDUPE_SECONDS, apply_refill, confirm_same_refill
from .const import (
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


THRESHOLD_KEYS = ("warning_threshold", "critical_threshold")
_VACUUM_KEYED_SETTINGS = ("refill_config", "refill_settings", "device_options", "local_measurements",
                          "consumption_calibrations", "measurement_plans", "sessions", "intro_dismissed")


def measurement_identity(data: dict[str, Any], vacuum_entity: str) -> tuple[str, set[str]]:
    """Stable owner and proven historical IDs; a reused ID cannot prove ownership."""
    origins = data.get("entity_origins") or {}
    origin = origins.get(vacuum_entity) or vacuum_entity
    other_origins = {value for key, value in origins.items() if key != vacuum_entity}
    aliases = data.get("vacuum_aliases") or {}
    proven = {origin}
    if vacuum_entity not in other_origins:
        proven.add(vacuum_entity)
    proven.update(old for old, target in aliases.items()
                  if target == vacuum_entity and old not in other_origins)
    return origin, proven


def measurement_belongs(sample: dict[str, Any], origin: str, proven: set[str]) -> bool:
    """Scope new samples explicitly; accept legacy IDs only with registry evidence."""
    scope = sample.get("identity_scope")
    return scope == origin if scope is not None else sample.get("device_id") in proven


def measurement_projection(sample: dict[str, Any], origin: str, proven: set[str]) -> dict[str, Any]:
    """Normalize proven identity for comparison only; leave recorded evidence intact."""
    projected = deepcopy(sample)
    projected["device_id"] = origin
    context = projected.get("context")
    if isinstance(context, dict) and context.get("device_id") in proven:
        context["device_id"] = origin
    return projected


def _move_vacuum_references(data: dict[str, Any], old: str, new: str) -> None:
    """Move typed live references only; refuse any overlapping destination."""
    settings = data["settings"]
    maps = [data["tank_states"]]
    maps.extend(settings[key] for key in _VACUUM_KEYED_SETTINGS if isinstance(settings.get(key), dict))
    links = settings.get("robot_links")
    if isinstance(links, dict):
        maps.append(links)
    custom = settings.get("custom_calibration")
    origins = data.get("entity_origins") or {}
    def referenced(entity: str) -> bool:
        return (any(entity in mapping for mapping in maps)
                or (isinstance(links, dict) and entity in links.values())
                or (isinstance(custom, dict) and ("entity:" + entity in custom or entity in custom))
                or any(isinstance(item, dict) and item.get("vacuum_entity") == entity
                       for key in ("configured_devices", "user_devices")
                       for item in (settings.get(key) or [])))
    if referenced(old) and referenced(new):
        raise ValueError("rename conflict: destination already has data")
    if old in origins and new in origins:
        raise ValueError("rename conflict: destination has an entity identity")
    identities = data.get("registry_identities") or {}
    aliases = data.get("vacuum_aliases") or {}
    previous_target = aliases.get(new) if isinstance(aliases, dict) else None
    if previous_target:
        original = identities.get(previous_target) if isinstance(identities, dict) else None
        incoming = identities.get(old) if isinstance(identities, dict) else None
        # The move consumes the destination alias. Capture its former owner
        # first in the same transaction, including reconciliation after unload.
        if original is None or incoming is None or original != incoming:
            data.setdefault("ambiguous_vacuum_identities", {}).setdefault(new, original)
    data["entity_origins"] = origins
    for mapping in maps:
        if old in mapping:
            mapping[new] = mapping.pop(old)
    if isinstance(links, dict):
        for entity, target in links.items():
            if target == old:
                links[entity] = new
    if isinstance(custom, dict) and "entity:" + old in custom:
        custom["entity:" + new] = custom.pop("entity:" + old)
    if isinstance(custom, dict) and old in custom:
        custom[new] = custom.pop(old)
    for key in ("configured_devices", "user_devices"):
        for item in settings.get(key) or []:
            if isinstance(item, dict) and item.get("vacuum_entity") == old:
                item["vacuum_entity"] = new
    origins[new] = origins.pop(old, old)
    aliases = data.setdefault("vacuum_aliases", {})
    for source, target in aliases.items():
        if target == old:
            aliases[source] = new
    aliases[old] = new
    aliases.pop(new, None)


def _public_state(data: dict[str, Any]) -> dict[str, Any]:
    """Hide registry identity and held conflict data from ordinary consumers."""
    data = deepcopy(data)
    data.pop("registry_identities", None)
    ambiguous = data.pop("ambiguous_vacuum_identities", {})
    data["ambiguous_vacuum_ids"] = sorted(ambiguous) if isinstance(ambiguous, dict) else []
    orphans = data.pop("identity_orphan_sources", {})
    if isinstance(orphans, dict) and orphans:
        hidden = set(orphans)
        data["registry_identity_conflicts"] = [{"entity_id": old, "reason": "identity_unresolved",
            "entity_origin": (data.get("entity_origins") or {}).get(marker, old)}
            for marker, old in orphans.items()]
        data["tank_states"] = {key: value for key, value in data.get("tank_states", {}).items() if key not in hidden}
        settings = data.get("settings", {})
        for key in _VACUUM_KEYED_SETTINGS:
            if isinstance(settings.get(key), dict):
                settings[key] = {k: v for k, v in settings[key].items() if k not in hidden}
        for key in ("configured_devices", "user_devices"):
            if isinstance(settings.get(key), list):
                settings[key] = [item for item in settings[key]
                                 if not isinstance(item, dict) or item.get("vacuum_entity") not in hidden]
        if isinstance(settings.get("robot_links"), dict):
            settings["robot_links"] = {k: v for k, v in settings["robot_links"].items()
                                       if k not in hidden and (not isinstance(v, str) or v not in hidden)}
        if isinstance(settings.get("custom_calibration"), dict):
            settings["custom_calibration"] = {k: v for k, v in settings["custom_calibration"].items()
                if k not in hidden and not any(k == "entity:" + item for item in hidden)}
        if isinstance(data.get("entity_origins"), dict):
            data["entity_origins"] = {k: v for k, v in data["entity_origins"].items() if k not in hidden}
    return data


def validate_threshold_settings(settings: dict[str, Any]) -> None:
    """Validate the complete effective pair before changing either value."""
    for key in THRESHOLD_KEYS:
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 99:
            raise ValueError(f"{key} must be a number between 1 and 99")
    if settings["critical_threshold"] >= settings["warning_threshold"]:
        raise ValueError("critical_threshold must be lower than warning_threshold")


def _default_state() -> dict[str, Any]:
    return {
        "settings": {
            "warning_threshold": DEFAULT_WARNING_THRESHOLD,
            "critical_threshold": DEFAULT_CRITICAL_THRESHOLD,
            "configured_devices": [],
            "user_devices": [],
            "maintenance_items": [],
            "refill_config": {},
            "refill_settings": {},
            "custom_calibration": {},
            "sessions": {},
            "intro_dismissed": {},
            "device_options": {},
        },
        "tank_states": {},
    }


class VacuumWaterStorage:
    """Thin async wrapper around Home Assistant storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Bind storage to a Home Assistant instance."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] | None = None
        self._retired_vacuum_ids: set[str] = set()
        self._identity_unavailable_ids: set[str] = set()

    async def async_rename_vacuum(self, old: str, new: str) -> bool:
        """Apply an authoritative registry rename as a single Store write."""
        if not (old.startswith("vacuum.") and new.startswith("vacuum.")) or old == new:
            return False
        async with self._lock:
            data = await self._ensure_loaded_locked()
            candidate = deepcopy(data)
            try:
                _move_vacuum_references(candidate, old, new)
            except ValueError as err:
                _LOGGER.warning("Vacuum rename conflict %s -> %s: %s", old, new, err)
                return False
            identities = candidate.get("registry_identities")
            if isinstance(identities, dict) and old in identities:
                identities[new] = identities.pop(old)
            await self._store.async_save(candidate)
            self._data = candidate
            self._retired_vacuum_ids.add(old)
            self._retired_vacuum_ids.discard(new)
            return True

    async def async_reconcile_registry(self, current: dict[str, list[str]]) -> None:
        """Reconcile only unique, previously recorded registry identities."""
        async with self._lock:
            data = await self._ensure_loaded_locked()
            candidate = deepcopy(data)
            previous = candidate.get("registry_identities") or {}
            if not isinstance(previous, dict):
                previous = {}
            for entity in candidate.get("tank_states", {}):
                if entity not in current and entity not in previous:
                    _LOGGER.warning("Vacuum history %s has no recorded registry identity; a rename cannot be reconciled automatically", entity)
            reverse: dict[tuple[str, ...], list[str]] = {}
            for entity, identity in current.items():
                reverse.setdefault(tuple(identity), []).append(entity)
            previous_reverse: dict[tuple[str, ...], list[str]] = {}
            for entity, identity in previous.items():
                if isinstance(identity, list) and len(identity) == 3 and all(isinstance(part, str) for part in identity):
                    previous_reverse.setdefault(tuple(identity), []).append(entity)
            retired = []
            unresolved = {}
            orphan_sources = candidate.setdefault("identity_orphan_sources", {})
            ambiguous = candidate.setdefault("ambiguous_vacuum_identities", {})
            for source, target in (candidate.get("vacuum_aliases") or {}).items():
                original_identity = previous.get(target) or current.get(target)
                if source in current and original_identity and current[source] != original_identity:
                    ambiguous.setdefault(source, original_identity)
            def hold_for_identity(old: str, identity: list[str]) -> None:
                marker = "vacuum.vwm_unresolved_" + hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
                if marker in current or marker in orphan_sources:
                    raise ValueError("Vacuum identity conflict cannot be isolated safely")
                _move_vacuum_references(candidate, old, marker)
                candidate.get("vacuum_aliases", {}).pop(old, None)
                orphan_sources[marker] = old
                unresolved[marker] = identity
                _LOGGER.warning("Vacuum identity conflict for %s: previous history is held until its registry identity returns", old)
            # Vacate every reused id before attempting any recovery. Otherwise
            # an old occupant's origin can block a returning identity forever.
            reused = set()
            for old, identity in previous.items():
                if old in current and current[old] != identity:
                    if not (isinstance(identity, list) and len(identity) == 3 and all(isinstance(part, str) for part in identity)):
                        raise ValueError("Vacuum identity conflict cannot be isolated safely")
                    ambiguous.setdefault(old, identity)
                    hold_for_identity(old, identity)
                    reused.add(old)
            work = {**{old: identity for old, identity in previous.items() if old not in reused}, **unresolved}
            unresolved = {}
            previous_reverse = {}
            for entity, identity in work.items():
                if isinstance(identity, list) and len(identity) == 3 and all(isinstance(part, str) for part in identity):
                    previous_reverse.setdefault(tuple(identity), []).append(entity)
            for old, identity in work.items():
                if current.get(old) == identity:
                    continue
                if not (isinstance(identity, list) and len(identity) == 3 and all(isinstance(part, str) for part in identity)):
                    unresolved[old] = identity
                    continue
                matches = reverse.get(tuple(identity), [])
                if len(matches) != 1 or len(previous_reverse.get(tuple(identity), [])) != 1:
                    unresolved[old] = identity
                    continue
                new = matches[0]
                try:
                    _move_vacuum_references(candidate, old, new)
                except ValueError as err:
                    _LOGGER.warning("Vacuum rename conflict %s -> %s: %s", old, new, err)
                    unresolved[old] = identity
                    continue
                if old in orphan_sources:
                    candidate.get("vacuum_aliases", {}).pop(old, None)
                    orphan_sources.pop(old, None)
                retired.append(old)
            candidate["registry_identities"] = {**unresolved, **current}
            for entity, identity in list(ambiguous.items()):
                if identity is not None and entity in current and current[entity] == identity:
                    ambiguous.pop(entity)
            origins = candidate.setdefault("entity_origins", {})
            candidate["identity_unavailable_origins"] = sorted(
                str(origins.get(entity, entity)) for entity in unresolved if entity not in orphan_sources
            )
            for entity, identity in current.items():
                if entity in origins:
                    continue
                if entity in origins.values():
                    digest = hashlib.sha256("|".join(identity).encode()).hexdigest()[:10]
                    origins[entity] = entity + "_" + digest
            aliases = candidate.get("vacuum_aliases")
            if isinstance(aliases, dict):
                for entity in current:
                    aliases.pop(entity, None)
            if candidate != data:
                await self._store.async_save(candidate)
                self._data = candidate
            self._retired_vacuum_ids.update(retired)
            self._retired_vacuum_ids.difference_update(current)
            self._identity_unavailable_ids = {entity for entity in unresolved if entity not in orphan_sources}

    async def async_load(self) -> dict[str, Any]:
        """Load storage, creating the default shape when absent."""
        async with self._lock:
            if self._data is None:
                loaded = await self._store.async_load()
                if not isinstance(loaded, dict):
                    loaded = {}
                self._data = _default_state()
                self._deep_merge(self._data, loaded)
            return deepcopy(self._data)

    async def async_get_state(self) -> dict[str, Any]:
        """Return product state without internal registry identity keys."""
        data = await self.async_load()
        return _public_state(data)

    async def async_get_settings(self) -> dict[str, Any]:
        """Return persisted settings."""
        return (await self.async_get_state())["settings"]

    async def async_set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply a shallow settings patch.

        Empty-list patches are refused to protect user data from accidental
        frontend initialization writes, matching the v5 sentence-manager guard.
        """
        if not isinstance(patch, dict):
            raise ValueError("settings patch must be an object")

        async with self._lock:
            data = await self._ensure_loaded_locked()
            settings = data["settings"]
            clean: dict[str, Any] = {}
            for key, value in patch.items():
                if (
                    isinstance(value, list)
                    and not value
                    and isinstance(settings.get(key), list)
                    and settings.get(key)
                ):
                    _LOGGER.warning("Refusing empty-list settings patch for %s", key)
                    continue
                clean[str(key)] = deepcopy(value)
            hidden = set((data.get("identity_orphan_sources") or {}).keys())
            if hidden:
                for key in _VACUUM_KEYED_SETTINGS:
                    if isinstance(clean.get(key), dict) and isinstance(settings.get(key), dict):
                        clean[key].update({k: deepcopy(v) for k, v in settings[key].items() if k in hidden})
                for key in ("configured_devices", "user_devices"):
                    if isinstance(clean.get(key), list) and isinstance(settings.get(key), list):
                        clean[key].extend(deepcopy(item) for item in settings[key]
                                          if isinstance(item, dict) and item.get("vacuum_entity") in hidden)
                if isinstance(clean.get("robot_links"), dict) and isinstance(settings.get("robot_links"), dict):
                    clean["robot_links"].update({k: v for k, v in settings["robot_links"].items()
                        if k in hidden or (isinstance(v, str) and v in hidden)})
                if isinstance(clean.get("custom_calibration"), dict) and isinstance(settings.get("custom_calibration"), dict):
                    clean["custom_calibration"].update({k: deepcopy(v) for k, v in settings["custom_calibration"].items()
                        if k in hidden or any(k == "entity:" + item for item in hidden)})
            aliases = data.get("vacuum_aliases") or {}
            ambiguous = data.get("ambiguous_vacuum_identities") or {}
            for key in ("configured_devices", "user_devices"):
                if isinstance(clean.get(key), list) and any(
                    isinstance(item, dict) and isinstance(item.get("vacuum_entity"), str)
                    and item["vacuum_entity"] in ambiguous
                    for item in clean[key]
                ):
                    raise ValueError("A configured vacuum ID was reused; update this card's robot selection")
            if self.hass is not None and aliases:
                from homeassistant.helpers import entity_registry as er
                registry = er.async_get(self.hass)
                for key in ("configured_devices", "user_devices"):
                    if not isinstance(clean.get(key), list):
                        continue
                    for item in clean[key]:
                        if not isinstance(item, dict):
                            continue
                        old = item.get("vacuum_entity")
                        if not isinstance(old, str):
                            continue
                        target = aliases.get(old)
                        if target and registry.async_get(old) is None:
                            if registry.async_get(target) is None:
                                raise ValueError("Renamed vacuum is not present in the entity registry")
                            item["vacuum_entity"] = target
            updated_settings = {**settings, **clean}
            if any(key in clean for key in THRESHOLD_KEYS):
                validate_threshold_settings(updated_settings)
            # Publish the entire patch only after validation and persistence succeed.
            updated_data = {**data, "settings": updated_settings}
            await self._store.async_save(updated_data)
            self._data = updated_data
            return _public_state(updated_data)["settings"]

    async def async_replace_settings_key(self, key: str, value: Any) -> None:
        """Replace one settings key, bypassing the empty-list guard.

        Only for explicit migrations (e.g. pruning ghost configured_devices);
        regular writes must go through async_set_settings.
        """
        async with self._lock:
            data = await self._ensure_loaded_locked()
            hidden = set((data.get("identity_orphan_sources") or {}).keys())
            if key in ("configured_devices", "user_devices") and isinstance(value, list) and hidden:
                value = [*value, *(deepcopy(item) for item in data["settings"].get(key, [])
                                  if isinstance(item, dict) and item.get("vacuum_entity") in hidden)]
            data["settings"][str(key)] = deepcopy(value)
            await self._store.async_save(data)

    async def async_get_tank_state(self, vacuum_entity: str) -> dict[str, Any]:
        """Return one vacuum tank state."""
        data = await self.async_load()
        return deepcopy(
            data["tank_states"].get(vacuum_entity, self.default_tank_state())
        )

    async def async_set_tank_state(
        self, vacuum_entity: str, tank_state: dict[str, Any]
    ) -> None:
        """Persist one vacuum tank state."""
        if not vacuum_entity:
            raise ValueError("vacuum_entity is required")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            data["tank_states"][vacuum_entity] = deepcopy(tank_state)
            await self._store.async_save(data)

    async def async_set_tank_states(
        self,
        tank_states: dict[str, dict[str, Any]],
        *,
        expected_reset_ts: dict[str, Any] | None = None,
        delay_seconds: float | None = None,
        persist: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Persist tick results; never overwrite a refill recorded meanwhile.

        ``persist=False`` updates only the in-memory Store data (a pass that
        changed nothing but its tick timestamp); the next real write, or a
        pending delayed write, carries it to disk.

        A tick computes from a snapshot. When a refill was recorded after that
        snapshot (``last_reset_ts`` changed), its result is dropped and the next
        pass starts from the refilled state. Returns the states actually written.
        """
        async with self._lock:
            data = await self._ensure_loaded_locked()
            written: dict[str, dict[str, Any]] = {}
            for vacuum_entity, tank_state in tank_states.items():
                if vacuum_entity in self._retired_vacuum_ids or vacuum_entity in self._identity_unavailable_ids:
                    continue
                if expected_reset_ts is not None and vacuum_entity in expected_reset_ts:
                    current = data["tank_states"].get(vacuum_entity) or {}
                    if int(current.get("last_reset_ts") or 0) != int(expected_reset_ts[vacuum_entity] or 0):
                        continue
                data["tank_states"][vacuum_entity] = deepcopy(tank_state)
                written[vacuum_entity] = deepcopy(tank_state)
            if written and persist:
                await self._save_locked(data, delay_seconds)
            return written

    async def _save_locked(self, data: dict[str, Any], delay_seconds: float | None = None) -> None:
        """Write now, or coalesce frequent event-driven writes (flushed on shutdown)."""
        delay_save = getattr(self._store, "async_delay_save", None)
        if delay_seconds and callable(delay_save):
            delay_save(lambda: data, delay_seconds)
            return
        await self._store.async_save(data)

    async def async_reset_tank(
        self, vacuum_entity: str, when_iso: str, when_ts: int, source: str = "card"
    ) -> dict[str, Any]:
        """Mark one tank refilled and return the new tank state."""
        if not vacuum_entity.startswith("vacuum.") or len(vacuum_entity) <= 7:
            raise ValueError("Select a vacuum entity")
        if source not in REFILL_SOURCES:
            raise ValueError("Unknown refill source")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            state = self.default_tank_state()
            state.update(data["tank_states"].get(vacuum_entity) or {})
            # A second report of the same physical refill (a double press, the
            # button after the dock already cleared) must not erase the water
            # counted in between or add a second history entry. The tick applies
            # the same window to lid and button entities.
            previous_reset = int(state.get("last_reset_ts") or 0)
            if (state.get("initialized") and not state.get("water_empty_active")
                    and not state.get("accounting_incomplete")
                    and 0 <= when_ts - previous_reset <= USER_REFILL_DEDUPE_SECONDS * 1000):
                if confirm_same_refill(state, source):
                    data["tank_states"][vacuum_entity] = state
                    await self._store.async_save(data)
                return deepcopy(state)
            # A refill starts a new baseline; it is not a signal gap.
            practice = data["settings"].get("refill_settings", {}).get(vacuum_entity, {}).get("full_refill_practice_confirmed") is True
            apply_refill(state, when_ts, source, rebaseline=True, full_practice_confirmed=practice)
            state["last_reset_iso"] = when_iso
            data["tank_states"][vacuum_entity] = state
            await self._store.async_save(data)
            return deepcopy(state)

    async def async_mark_empty(self, vacuum_entity: str) -> dict[str, Any]:
        """The user reports the tracked tank empty; the next tick anchors it."""
        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum.") or len(vacuum_entity) <= 7:
            raise ValueError("Select a vacuum entity")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            state = self.default_tank_state()
            state.update(data["tank_states"].get(vacuum_entity) or {})
            if state.get("water_empty_active") or state.get("user_empty_active"):
                return deepcopy(state)  # already empty until the next refill
            state["user_empty_active"] = True
            data["tank_states"][vacuum_entity] = state
            await self._store.async_save(data)
            return deepcopy(state)

    async def async_set_refill_settings(
        self,
        vacuum_entity: str,
        *,
        auto_refill: bool | None,
        button_entity: str | None,
        lid_entity: str | None,
        full_refill_practice_confirmed: bool | None = None,
    ) -> dict[str, Any]:
        """Replace one vacuum's refill choices and return all settings."""
        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum.") or len(vacuum_entity) <= 7:
            raise ValueError("Select a vacuum entity")
        if auto_refill is not None and not isinstance(auto_refill, bool):
            raise ValueError("auto_refill must be true, false or null")
        if button_entity is not None and (
            not isinstance(button_entity, str) or not button_entity.startswith(("input_button.", "button."))
        ):
            raise ValueError("Refill button must be an input_button or button entity")
        if lid_entity is not None and (
            not isinstance(lid_entity, str) or not lid_entity.startswith("binary_sensor.")
        ):
            raise ValueError("Tank lid sensor must be a binary_sensor entity")
        if full_refill_practice_confirmed is not None and type(full_refill_practice_confirmed) is not bool:
            raise ValueError("Confirm full refill practice with true or false")
        entry = {
            key: value
            for key, value in (("auto_refill", auto_refill), ("button_entity", button_entity), ("lid_entity", lid_entity))
            if value is not None
        }
        async with self._lock:
            data = await self._ensure_loaded_locked()
            settings = data["settings"]
            all_settings = dict(settings.get("refill_settings") or {})
            previous = all_settings.get(vacuum_entity) or {}
            if full_refill_practice_confirmed is not None:
                entry["full_refill_practice_confirmed"] = full_refill_practice_confirmed
            elif "full_refill_practice_confirmed" in previous:
                entry["full_refill_practice_confirmed"] = previous["full_refill_practice_confirmed"]
            if entry:
                all_settings[vacuum_entity] = entry
            else:
                all_settings.pop(vacuum_entity, None)
            settings["refill_settings"] = all_settings
            await self._store.async_save(data)
            return _public_state(data)["settings"]

    async def async_set_device_options(self, vacuum_entity: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Validate and store one robot's options; return all settings."""
        from .device_options import merge_options

        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum.") or len(vacuum_entity) <= 7:
            raise ValueError("Select a vacuum entity")
        if not isinstance(patch, dict):
            raise ValueError("Options must be an object")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            settings = data["settings"]
            all_options = dict(settings.get("device_options") or {})
            merged = merge_options(dict(all_options.get(vacuum_entity) or {}), patch)
            if merged:
                all_options[vacuum_entity] = merged
            else:
                all_options.pop(vacuum_entity, None)
            settings["device_options"] = all_options
            await self._store.async_save(data)
            return _public_state(data)["settings"]

    async def async_set_robot_link(self, vacuum_entity: str, target: str | None) -> dict[str, Any]:
        """Record whether a (bridged) robot is the same as another one.

        ``target`` is the robot it duplicates, ``"distinct"`` for a separate
        robot, or ``None`` to forget the decision.
        """
        for entity in (vacuum_entity, target if target not in (None, "distinct") else None):
            if entity is not None and (not isinstance(entity, str) or not entity.startswith("vacuum.") or len(entity) <= 7):
                raise ValueError("Select a vacuum entity")
        if target == vacuum_entity:
            raise ValueError("A robot cannot duplicate itself")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            settings = data["settings"]
            links = dict(settings.get("robot_links") or {})
            if target is None:
                links.pop(vacuum_entity, None)
            else:
                links[vacuum_entity] = target
            settings["robot_links"] = links
            await self._store.async_save(data)
            return _public_state(data)["settings"]

    async def async_save_measurement(self, vacuum_entity, index, expected_ts, values):
        """Select and save a measured cycle under one lock; never retarget a stale UI."""
        from .calibration import select_recorded_cycle, build_local_measurement, fit_local_measurements
        from .profiles import _compatible_context
        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum."):
            raise ValueError("Select a vacuum entity")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            sessions = data["tank_states"].get(vacuum_entity, {}).get("automatic_sessions", [])
            session = select_recorded_cycle(sessions, index, expected_ts)
            sample = build_local_measurement(session, values, vacuum_entity)
            origin, proven = measurement_identity(data, vacuum_entity)
            sample["identity_scope"] = origin
            all_samples = deepcopy(data["settings"].get("local_measurements") or {})
            samples = list(all_samples.get(vacuum_entity) or [])
            if any(s.get("id") == sample["id"] for s in samples):
                raise ValueError("This cycle already has a measurement; it cannot be both training and validation")
            if len(samples) >= 200:
                raise ValueError("Measurement history is full; preserve/export it before collecting more")
            samples.append(sample)
            all_samples[vacuum_entity] = samples
            # Other settings remain intact, and old context samples stay available.
            projected = [measurement_projection(s, origin, proven) for s in samples
                         if measurement_belongs(s, origin, proven)]
            target_context = measurement_projection(sample, origin, proven)["context"]
            matching = [s for s in projected if s.get("context") == target_context]
            fitted = fit_local_measurements(matching)
            profiles = deepcopy(data["settings"].get("consumption_calibrations") or {})
            if fitted:
                previous_profiles = profiles.get(vacuum_entity) or []
                if isinstance(previous_profiles, dict):
                    previous_profiles = [previous_profiles]
                profiles[vacuum_entity] = [p for p in previous_profiles
                    if isinstance(p, dict) and not (p.get("device_id") in proven
                        and all(p.get(key) == fitted.get(key) for key in ("kind", "scope", "method"))
                        and _compatible_context(p.get("context"), fitted["context"]))] + [fitted]
            data["settings"].update(local_measurements=all_samples, consumption_calibrations=profiles)
            await self._store.async_save(data)
            return {"saved": True, "sample_count": len(matching), "calibration": deepcopy(fitted)}

    async def async_set_measurement_plan(self, vacuum_entity, plan):
        """Save prospective declarations without altering any recorded session."""
        from .calibration import validate_measurement_plan
        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum."):
            raise ValueError("Select a vacuum entity")
        clean = validate_measurement_plan(plan)
        async with self._lock:
            data = await self._ensure_loaded_locked()
            plans = deepcopy(data["settings"].get("measurement_plans") or {})
            plans[vacuum_entity] = clean
            data["settings"]["measurement_plans"] = plans
            await self._store.async_save(data)
            return _public_state(data)["settings"]

    async def async_reprofile(self, vacuum_entity: str) -> dict[str, Any]:
        """Refresh generated discovery, retaining authored config and all history."""
        if not vacuum_entity.startswith("vacuum."):
            raise ValueError("vacuum_entity must name a vacuum")
        from .sensor_calculations import _configuration_field_provenance
        async with self._lock:
            data = await self._ensure_loaded_locked()
            for key in ("configured_devices", "user_devices"):
                for index, device in enumerate(data["settings"].get(key) or []):
                    if not isinstance(device, dict) or device.get("vacuum_entity") != vacuum_entity:
                        continue
                    authored = _configuration_field_provenance(device)[0] - {"profile_locked", "profile_override", "locked_profile", "profile_key", "profile_source", "profile_confidence", "brand_profile"}
                    replacement = {k: deepcopy(v) for k, v in device.items() if k in authored}
                    replacement["vacuum_entity"] = vacuum_entity
                    replacement["config_provenance"] = {"authored_fields": sorted(authored | {"vacuum_entity"})}
                    data["settings"][key][index] = replacement
            state = data["tank_states"].get(vacuum_entity)
            if isinstance(state, dict):
                state.update(last_area=None, last_duration_seconds=None, last_tick_ts=0,
                             last_water_volume_ml=None, area_gap=True, duration_gap=True)
            await self._store.async_save(data)
            return _public_state(data)["settings"]

    async def _ensure_loaded_locked(self) -> dict[str, Any]:
        """Load data while caller holds the lock."""
        if self._data is None:
            loaded = await self._store.async_load()
            if not isinstance(loaded, dict):
                loaded = {}
            self._data = _default_state()
            self._deep_merge(self._data, loaded)
        return self._data

    @staticmethod
    def default_tank_state() -> dict[str, Any]:
        """Return the additive v5 state shape while accepting v4 records."""
        return {
            "used_ml": 0,
            "initialized": False,
            "last_reset_iso": None,
            "last_status": None,
            "last_dock_status": None,
            "last_area": None,
            "last_duration_seconds": None,
            "last_dock_err": None,
            "last_door": None,
            "last_reset_ts": 0,
            "wash_sequence_active": False,
            "area_gap": False,
            "last_accounting_source": None,
            "last_accounting_rate_ml": None,
            "last_accounting_evidence": None,
            "last_accounting_reason": None,
            "missing_usage_rate_reason": None,
            "last_tick_ts": 0,
            "water_empty_active": False,
            "water_anchor_source": None,
            "water_anchor_kind": None,
            "water_anchor_confidence": None,
            "water_anchor_candidate_source": None,
            "water_anchor_candidate_since_ts": 0,
            "last_low_water_ts": 0,
            "calibration_factor": 1.0,
            "calibration_samples": 0,
            "last_calibration_predicted_ml": None,
            "last_calibration_target_ml": None,
        }

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)
