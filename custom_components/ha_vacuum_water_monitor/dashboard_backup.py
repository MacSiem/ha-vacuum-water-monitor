"""Private administrator-only dashboard placement backups."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from homeassistant.core import HomeAssistant

from .storage import _ReportingStore


class DashboardBackups:
    """Persist detached before/after snapshots before a dashboard write."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = _ReportingStore(hass, 1, "ha_vacuum_water_monitor.dashboard_backups")
        self._lock = asyncio.Lock()

    async def _admin(self, user_id: str | None) -> None:
        user = await self._hass.auth.async_get_user(user_id) if user_id else None
        if user is None or not user.is_active or not user.is_admin:
            raise PermissionError("Administrator access required")

    async def prepare(self, user_id: str | None, target: str | None, before: dict, after: dict) -> str:
        await self._admin(user_id)
        if target is not None and (not isinstance(target, str) or len(target) > 128):
            raise ValueError("Invalid dashboard")
        if not isinstance(before.get("views"), list) or not isinstance(after.get("views"), list):
            raise ValueError("Invalid dashboard configuration")
        encoded = json.dumps([before, after], allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 5_000_000:
            raise ValueError("Dashboard backup is too large")
        async with self._lock:
            records = await self._store.async_load() or {"entries": {}}
            candidate = deepcopy(records)
            key = uuid4().hex
            candidate.setdefault("entries", {})[key] = {
                "user_id": user_id, "target": target,
                "created": datetime.now(timezone.utc).isoformat(),
                "before": deepcopy(before), "after": deepcopy(after),
            }
            await self._admin(user_id)
            await self._store.async_save(candidate)
            return key

    async def list(self, user_id: str | None) -> list[dict]:
        await self._admin(user_id)
        async with self._lock:
            records = await self._store.async_load() or {"entries": {}}
            await self._admin(user_id)
            return [{"id": key, "target": record.get("target"), "created": record.get("created")}
                    for key, record in records.get("entries", {}).items() if record.get("user_id") == user_id]

    async def get(self, user_id: str | None, key: str) -> dict:
        await self._admin(user_id)
        async with self._lock:
            records = await self._store.async_load() or {"entries": {}}
            record = records.get("entries", {}).get(key)
            await self._admin(user_id)
            if not record or record.get("user_id") != user_id:
                raise ValueError("Backup unavailable")
            return deepcopy({field: record.get(field) for field in ("target", "created", "before", "after")})
