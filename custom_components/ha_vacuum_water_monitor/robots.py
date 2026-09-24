"""User actions and health reports shared by entities, Repairs, services and the card.

Every way to act on a robot (the card, a Home Assistant entity, a Repairs fix,
the ``mark_refilled`` service) ends in the functions below, so they validate,
store, re-bind and notify the same way.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .const import (
    DATA_STORAGE,
    DATA_TICKER,
    DOMAIN,
    EVENT_STATE_CHANGED,
    event_tank_states,
    signal_vacuum_water_updated,
)
from .health import MOP_ATTRIBUTE_KEYS, REPAIR_CHECKS, robot_health
from .sensor_calculations import (
    _model_tank_ml,
    apply_custom_calibration,
    build_vacuum_devices,
    estimate_water_state,
    filter_active_devices,
    vacuum_slug,
    water_capacity,
)
from .storage import VacuumWaterStorage

_LOGGER = logging.getLogger(__name__)

DATA_ISSUES = "issues"
DATA_ISSUE_SYNC = "issue_sync"
# Issues wait until integrations have loaded their robots after a restart.
ISSUE_STARTUP_GRACE_SECONDS = 120
ISSUE_SYNC_DELAY_SECONDS = 3
# While a robot runs, ticks change the Store every few seconds; Repairs follow
# at most once a minute then (user actions still sync within seconds).
ISSUE_SYNC_TICK_DELAY_SECONDS = 60

_FIXABLE = {"awaiting_refill", "accounting_paused", "unknown_capacity", "possible_duplicate"}


def storage(hass: HomeAssistant) -> VacuumWaterStorage:
    return hass.data[DOMAIN][DATA_STORAGE]


@callback
def async_notify(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    """Tell sensors, entities and open cards that the Store changed."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        async_dispatcher_send(hass, signal_vacuum_water_updated(entry.entry_id), payload)
    event = dict(payload)
    if isinstance(event.get("tank_states"), dict):
        event["tank_states"] = event_tank_states(event["tank_states"])
        event["partial"] = True
    hass.bus.async_fire(EVENT_STATE_CHANGED, event)
    async_schedule_issue_sync(hass)


def _rebind(hass: HomeAssistant) -> None:
    ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
    if ticker is not None:
        hass.async_create_task(ticker.run(None))


def resolve_link(settings: dict[str, Any], vacuum_entity: str) -> str:
    """A robot the user linked as a duplicate acts on its owner."""
    links = settings.get("robot_links") if isinstance(settings.get("robot_links"), dict) else {}
    target = links.get(vacuum_entity)
    return target if target and target != "distinct" else vacuum_entity


async def async_mark_refilled(hass: HomeAssistant, vacuum_entity: str, source: str) -> dict[str, Any]:
    """Mark one robot's tracked tank full (deduplicated like every refill report)."""
    settings = (await storage(hass).async_get_state()).get("settings") or {}
    vacuum_entity = resolve_link(settings, vacuum_entity)
    now = datetime.now(timezone.utc)
    state = await storage(hass).async_reset_tank(
        vacuum_entity, now.isoformat(), int(now.timestamp() * 1000), source=source)
    async_notify(hass, {"tank_states": {vacuum_entity: state}})
    return state


async def async_mark_empty(hass: HomeAssistant, vacuum_entity: str) -> dict[str, Any]:
    """The user says the tank ran dry: anchor and learn from it right away."""
    settings = (await storage(hass).async_get_state()).get("settings") or {}
    vacuum_entity = resolve_link(settings, vacuum_entity)
    state = await storage(hass).async_mark_empty(vacuum_entity)
    ticker = hass.data.get(DOMAIN, {}).get(DATA_TICKER)
    if ticker is not None:
        await ticker.run({vacuum_entity})
        state = await storage(hass).async_get_tank_state(vacuum_entity)
    async_notify(hass, {"tank_states": {vacuum_entity: state}})
    return state


async def async_set_options(hass: HomeAssistant, vacuum_entity: str, patch: dict[str, Any]) -> dict[str, Any]:
    settings = await storage(hass).async_set_device_options(vacuum_entity, patch)
    _rebind(hass)
    async_notify(hass, {"settings": settings})
    return settings


async def async_set_auto_refill(hass: HomeAssistant, vacuum_entity: str, enabled: bool | None) -> dict[str, Any]:
    """Change only the automatic dock refill; a bound button or lid stays bound."""
    from .sensor_calculations import refill_choices

    current = refill_choices((await storage(hass).async_get_state()).get("settings"), vacuum_entity)
    settings = await storage(hass).async_set_refill_settings(
        vacuum_entity, auto_refill=enabled,
        button_entity=current.get("button_entity"), lid_entity=current.get("lid_entity"))
    _rebind(hass)
    async_notify(hass, {"settings": settings})
    return settings


async def async_set_link(hass: HomeAssistant, vacuum_entity: str, target: str | None) -> dict[str, Any]:
    settings = await storage(hass).async_set_robot_link(vacuum_entity, target)
    _rebind(hass)
    async_notify(hass, {"settings": settings})
    return settings


def build_reports(hass: HomeAssistant, stored: dict[str, Any], discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One health report per robot the integration tracks (pure given its inputs)."""
    settings = stored.get("settings") or {}
    tank_states = stored.get("tank_states") or {}
    known = {str(item.get("entity_id")) for item in discovered if isinstance(item, dict) and item.get("entity_id")}
    devices = filter_active_devices(build_vacuum_devices(settings, tank_states, discovered), known, tank_states)
    links = settings.get("robot_links") if isinstance(settings.get("robot_links"), dict) else {}
    by_entity = {str(item.get("entity_id")): item for item in discovered if isinstance(item, dict)}
    reports = []
    for device in devices:
        entity = str(device.get("vacuum_entity"))
        tank = VacuumWaterStorage.default_tank_state()
        if isinstance(tank_states.get(entity), dict):
            tank.update(tank_states[entity])
        effective = apply_custom_calibration(device, settings)
        estimate = estimate_water_state(device, tank, settings)
        _capacity, source = water_capacity(device, settings)
        state = hass.states.get(entity)
        attributes = getattr(state, "attributes", None) or {}
        mop_attribute_present = any(
            isinstance(effective.get(key), str) and effective.get(key) in attributes for key in MOP_ATTRIBUTE_KEYS)
        suggestion = (by_entity.get(entity) or {}).get("possible_duplicate_of")
        duplicate_of = suggestion if suggestion and not links.get(entity) and suggestion in by_entity else None
        report = robot_health(
            device, effective, tank, estimate,
            capacity_source=source if estimate.get("total_ml") is not None else None,
            model_capacity_ml=_model_tank_ml(device),
            duplicate_of=duplicate_of,
            duplicate_of_name=(by_entity.get(duplicate_of) or {}).get("name") if duplicate_of else None,
            mop_attribute_present=mop_attribute_present,
        )
        report["available"] = state is not None and state.state != STATE_UNAVAILABLE
        reports.append(report)
    return reports


async def async_reports(hass: HomeAssistant) -> list[dict[str, Any]]:
    from .tick import list_vacuums

    return build_reports(hass, await storage(hass).async_get_state(), list_vacuums(hass))


def issue_id(check_id: str, vacuum_entity: str) -> str:
    return f"{check_id}_{vacuum_slug(vacuum_entity)}"


@callback
def async_schedule_issue_sync(hass: HomeAssistant, delay: float = ISSUE_SYNC_DELAY_SECONDS) -> None:
    """Coalesce Repairs updates; a sooner request replaces a later pending one."""
    bucket = hass.data.get(DOMAIN)
    if bucket is None:
        return
    pending = bucket.get(DATA_ISSUE_SYNC)
    if pending:
        cancel, due = pending
        if due <= hass.loop.time() + delay:
            return
        cancel()

    @callback
    def _run(_now: Any) -> None:
        bucket.pop(DATA_ISSUE_SYNC, None)
        if DATA_STORAGE in bucket:
            hass.async_create_task(async_sync_issues(hass))

    bucket[DATA_ISSUE_SYNC] = (async_call_later(hass, delay, _run), hass.loop.time() + delay)


async def async_sync_issues(hass: HomeAssistant) -> None:
    """Mirror the actionable checks of every available robot into Repairs."""
    bucket = hass.data.get(DOMAIN)
    if bucket is None or DATA_STORAGE not in bucket:
        return
    if hass.state is not CoreState.running:
        async_schedule_issue_sync(hass, ISSUE_STARTUP_GRACE_SECONDS)
        return
    try:
        reports = await async_reports(hass)
    except Exception:  # noqa: BLE001 - Repairs must never break the integration
        _LOGGER.debug("Health report failed", exc_info=True)
        return
    current: dict[str, tuple] = bucket.setdefault(DATA_ISSUES, {})
    wanted: dict[str, tuple] = {}
    unavailable = {str(report["vacuum_entity"]) for report in reports if not report.get("available")}
    for report in reports:
        entity = str(report["vacuum_entity"])
        if entity in unavailable:
            continue
        for check in report["checks"]:
            if check["id"] not in REPAIR_CHECKS:
                continue
            params = check.get("params") or {}
            placeholders = {
                "name": str(report.get("name") or entity),
                "target_name": str(params.get("target_name") or ""),
                "model_capacity": str(int(report["model_capacity_ml"])) if report.get("model_capacity_ml") else "",
            }
            data = {"vacuum_entity": entity, "check": check["id"], "target": params.get("target")}
            wanted[issue_id(check["id"], entity)] = (check["id"], check["severity"], tuple(sorted(placeholders.items())),
                                                     tuple(sorted((k, v) for k, v in data.items() if v is not None)))
    registry = ir.async_get(hass)
    for key, signature in wanted.items():
        # A finished fix flow deletes its issue; recreate it if the check persists.
        if current.get(key) == signature and registry.async_get_issue(DOMAIN, key) is not None:
            continue
        check_id, severity, placeholders, data = signature
        ir.async_create_issue(
            hass, DOMAIN, key,
            is_fixable=check_id in _FIXABLE,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if severity == "error" else ir.IssueSeverity.WARNING,
            translation_key=check_id,
            translation_placeholders=dict(placeholders),
            data=dict(data),
        )
        current[key] = signature
    for key, signature in list(current.items()):
        if key in wanted:
            continue
        # The issues of a robot that is only temporarily unavailable stay.
        if dict(signature[3]).get("vacuum_entity") in unavailable:
            continue
        ir.async_delete_issue(hass, DOMAIN, key)
        current.pop(key, None)


@callback
def async_clear_issues(hass: HomeAssistant) -> None:
    bucket = hass.data.get(DOMAIN) or {}
    if pending := bucket.pop(DATA_ISSUE_SYNC, None):
        pending[0]()
    for key in list((bucket.get(DATA_ISSUES) or {})):
        ir.async_delete_issue(hass, DOMAIN, key)
    bucket.pop(DATA_ISSUES, None)
