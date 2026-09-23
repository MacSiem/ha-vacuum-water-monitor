"""Store-backed persistence for Vacuum Water Monitor."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .refill import REFILL_SOURCES, apply_refill
from .const import (
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


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
            settings.update(clean)
            await self._store.async_save(data)
            return deepcopy(settings)

    async def async_replace_settings_key(self, key: str, value: Any) -> None:
        """Replace one settings key, bypassing the empty-list guard.

        Only for explicit migrations (e.g. pruning ghost configured_devices);
        regular writes must go through async_set_settings.
        """
        async with self._lock:
            data = await self._ensure_loaded_locked()
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
            # A refill starts a new baseline; it is not a signal gap.
            apply_refill(state, when_ts, source, rebaseline=True)
            state["last_reset_iso"] = when_iso
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
        entry = {
            key: value
            for key, value in (("auto_refill", auto_refill), ("button_entity", button_entity), ("lid_entity", lid_entity))
            if value is not None
        }
        async with self._lock:
            data = await self._ensure_loaded_locked()
            settings = data["settings"]
            all_settings = dict(settings.get("refill_settings") or {})
            if entry:
                all_settings[vacuum_entity] = entry
            else:
                all_settings.pop(vacuum_entity, None)
            settings["refill_settings"] = all_settings
            await self._store.async_save(data)
            return deepcopy(settings)

    async def async_save_measurement(self, vacuum_entity, index, expected_ts, values):
        """Select and save a measured cycle under one lock; never retarget a stale UI."""
        from .calibration import select_recorded_cycle, build_local_measurement, fit_local_measurements
        if not isinstance(vacuum_entity, str) or not vacuum_entity.startswith("vacuum."):
            raise ValueError("Select a vacuum entity")
        async with self._lock:
            data = await self._ensure_loaded_locked()
            sessions = data["tank_states"].get(vacuum_entity, {}).get("automatic_sessions", [])
            session = select_recorded_cycle(sessions, index, expected_ts)
            sample = build_local_measurement(session, values, vacuum_entity)
            all_samples = deepcopy(data["settings"].get("local_measurements") or {})
            samples = list(all_samples.get(vacuum_entity) or [])
            if any(s.get("id") == sample["id"] for s in samples):
                raise ValueError("This cycle already has a measurement; it cannot be both training and validation")
            if len(samples) >= 200:
                raise ValueError("Measurement history is full; preserve/export it before collecting more")
            samples.append(sample)
            all_samples[vacuum_entity] = samples
            # Other settings remain intact, and old context samples stay available.
            matching = [s for s in samples if s.get("context") == sample["context"]]
            fitted = fit_local_measurements(matching)
            profiles = deepcopy(data["settings"].get("consumption_calibrations") or {})
            if fitted:
                previous_profiles = profiles.get(vacuum_entity) or []
                if isinstance(previous_profiles, dict):
                    previous_profiles = [previous_profiles]
                profiles[vacuum_entity] = [p for p in previous_profiles
                    if isinstance(p, dict) and p.get("context") != fitted["context"]] + [fitted]
            data["settings"].update(local_measurements=all_samples, consumption_calibrations=profiles)
            await self._store.async_save(data)
            return {"saved": True, "sample_count": len(matching), "calibration": deepcopy(fitted)}

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
            return deepcopy(data["settings"])

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
