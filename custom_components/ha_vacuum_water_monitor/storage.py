"""Store-backed persistence for Vacuum Water Monitor."""

from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
MAX_SETTINGS_BYTES = 512_000
MAX_STORAGE_BYTES = 1_000_000
MAX_TANK_STATES = 100


def _serialized_bytes(value: Any) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, ValueError) as err:
        raise ValueError("stored state must be bounded JSON data") from err
    return len(encoded)


def _validate_data_budget(
    current: dict[str, Any], candidate: dict[str, Any]
) -> None:
    """Bound cumulative storage while permitting legacy size-reducing writes."""
    current_settings_size = _serialized_bytes(current.get("settings") or {})
    candidate_settings_size = _serialized_bytes(candidate.get("settings") or {})
    if (
        candidate_settings_size > MAX_SETTINGS_BYTES
        and candidate_settings_size > current_settings_size
    ):
        raise ValueError("settings exceed the cumulative storage budget")

    current_tanks = current.get("tank_states") or {}
    candidate_tanks = candidate.get("tank_states") or {}
    if not isinstance(candidate_tanks, dict):
        raise ValueError("tank_states must be an object")
    if len(candidate_tanks) > MAX_TANK_STATES and len(candidate_tanks) > len(current_tanks):
        raise ValueError("too many tank states")

    current_size = _serialized_bytes(current)
    candidate_size = _serialized_bytes(candidate)
    if candidate_size > MAX_STORAGE_BYTES and candidate_size > current_size:
        raise ValueError("stored state exceeds the cumulative budget")


def _default_state() -> dict[str, Any]:
    return {
        "settings": {
            "warning_threshold": DEFAULT_WARNING_THRESHOLD,
            "critical_threshold": DEFAULT_CRITICAL_THRESHOLD,
            "configured_devices": [],
            "user_devices": [],
            "maintenance_items": [],
            "refill_config": {},
            "custom_calibration": {},
            "sessions": {},
            "intro_dismissed": {},
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
        """Return the full persisted state."""
        return await self.async_load()

    async def async_get_settings(self) -> dict[str, Any]:
        """Return persisted settings."""
        data = await self.async_load()
        return data["settings"]

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
            candidate = deepcopy(data)
            candidate["settings"].update(clean)
            _validate_data_budget(data, candidate)
            await self._store.async_save(candidate)
            self._data = candidate
            return deepcopy(candidate["settings"])

    async def async_replace_settings_key(self, key: str, value: Any) -> None:
        """Replace one settings key, bypassing the empty-list guard.

        Only for explicit migrations (e.g. pruning ghost configured_devices);
        regular writes must go through async_set_settings.
        """
        async with self._lock:
            data = await self._ensure_loaded_locked()
            candidate = deepcopy(data)
            candidate["settings"][str(key)] = deepcopy(value)
            _validate_data_budget(data, candidate)
            await self._store.async_save(candidate)
            self._data = candidate

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
            candidate = deepcopy(data)
            candidate["tank_states"][vacuum_entity] = deepcopy(tank_state)
            _validate_data_budget(data, candidate)
            await self._store.async_save(candidate)
            self._data = candidate

    async def async_set_tank_states(
        self, tank_states: dict[str, dict[str, Any]]
    ) -> None:
        """Persist all supplied tank states."""
        if not isinstance(tank_states, dict):
            raise ValueError("tank_states must be an object")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            candidate = deepcopy(data)
            candidate["tank_states"].update(deepcopy(tank_states))
            _validate_data_budget(data, candidate)
            await self._store.async_save(candidate)
            self._data = candidate

    async def async_reset_tank(
        self, vacuum_entity: str, when_iso: str, when_ts: int
    ) -> dict[str, Any]:
        """Reset one tank counter and return the new tank state."""
        async with self._lock:
            data = await self._ensure_loaded_locked()
            state = self.default_tank_state()
            state.update(data["tank_states"].get(vacuum_entity) or {})
            state["used_ml"] = 0
            state["last_reset_iso"] = when_iso
            state["last_reset_ts"] = when_ts
            candidate = deepcopy(data)
            candidate["tank_states"][vacuum_entity] = state
            _validate_data_budget(data, candidate)
            await self._store.async_save(candidate)
            self._data = candidate
            return deepcopy(state)

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
        """Return the v4-compatible tank state shape."""
        return {
            "used_ml": 0,
            "last_reset_iso": None,
            "last_status": None,
            "last_area": None,
            "last_dock_err": None,
            "last_door": None,
            "last_reset_ts": 0,
        }

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)
