"""5.8.0 inside a real Home Assistant core: settings entities, Repairs, health, diagnostics."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .test_ha_runtime import DOMAIN, VACUUM, _settle, _setup, _tank


def _entity(hass: HomeAssistant, domain: str, key: str) -> str:
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.platform == DOMAIN and entry.domain == domain and entry.unique_id.endswith(f"_vacuum_robot_{key}"):
            return entry.entity_id
    raise AssertionError(f"no {domain} entity for {key}")


async def _issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    return {issue_id: issue for (domain, issue_id), issue in ir.async_get(hass).issues.items() if domain == DOMAIN}


async def test_settings_entities_are_created_on_the_robot_device(hass: HomeAssistant) -> None:
    await _setup(hass)
    number = _entity(hass, "number", "tank_capacity")
    switch = _entity(hass, "switch", "auto_refill")
    button = _entity(hass, "button", "refilled")
    registry = er.async_get(hass)
    sensor = next(e for e in registry.entities.values()
                  if e.platform == DOMAIN and e.unique_id.endswith("_vacuum_robot_water_remaining"))
    assert {registry.async_get(entity).device_id for entity in (number, switch, button)} == {sensor.device_id}
    assert float(hass.states.get(number).state) > 0
    from custom_components.ha_vacuum_water_monitor.robots import async_reports
    assert next(r for r in await async_reports(hass) if r["vacuum_entity"] == VACUUM)["capacity_source"] == "model"
    assert hass.states.get(number).attributes["source"] in {"model", "user_option"}
    assert hass.states.get(switch).state == "on"


async def test_tank_size_entity_is_the_one_source(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    number = _entity(hass, "number", "tank_capacity")
    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 3000}, blocking=True)
    await hass.async_block_till_done()
    settings = (await storage.async_get_state())["settings"]
    assert settings["device_options"][VACUUM] == {"capacity_ml": 3000.0}
    assert float(hass.states.get(number).state) == 3000
    from custom_components.ha_vacuum_water_monitor.robots import async_reports
    assert next(r for r in await async_reports(hass) if r["vacuum_entity"] == VACUUM)["capacity_source"] == "user_option"
    assert hass.states.get(number).attributes["source"] in {"model", "user_option"}
    remaining = next(state for state in hass.states.async_all("sensor")
                     if state.attributes.get("vacuum_entity") == VACUUM and state.attributes.get("total_ml") is not None)
    assert remaining.attributes["total_ml"] == 3000
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises((ServiceValidationError, ValueError)):
        await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 50}, blocking=True)


async def test_refilled_button_and_auto_refill_switch(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    hass.states.async_set("input_button.dock_refilled", "2026-09-01T10:00:00+00:00")
    await storage.async_set_refill_settings(VACUUM, auto_refill=None, button_entity="input_button.dock_refilled",
                                            lid_entity=None)
    await storage.async_set_tank_state(VACUUM, {"used_ml": 2200, "initialized": True})
    await hass.services.async_call("button", "press", {"entity_id": _entity(hass, "button", "refilled")}, blocking=True)
    tank = await _tank(storage)
    assert (tank["used_ml"], tank["last_reset_source"]) == (0, "entity")

    switch = _entity(hass, "switch", "auto_refill")
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    settings = (await storage.async_get_state())["settings"]
    # Turning off the dock refill keeps the button the user bound.
    assert settings["refill_settings"][VACUUM] == {"auto_refill": False, "button_entity": "input_button.dock_refilled"}
    assert hass.states.get(switch).state == "off"


async def test_repairs_ask_to_confirm_a_full_tank_and_the_fix_starts_counting(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    issues = await _issues(hass)
    assert "awaiting_refill_vacuum_robot" in issues
    issue = issues["awaiting_refill_vacuum_robot"]
    assert issue.is_fixable and issue.translation_placeholders["name"] == "Robot"

    from custom_components.ha_vacuum_water_monitor import repairs

    flow = await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["step_id"] == "confirm"
    done = await flow.async_step_confirm({})
    assert done["type"] == "create_entry"
    tank = await _tank(storage)
    assert tank["initialized"] and tank["last_reset_source"] == "repair"
    ir.async_delete_issue(hass, DOMAIN, issue.issue_id)  # what the Repairs flow manager does on finish
    issues = await _issues(hass)
    assert "awaiting_refill_vacuum_robot" not in issues


async def test_unknown_tank_size_repair_sets_the_option(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    from custom_components.ha_vacuum_water_monitor import repairs

    flow = await repairs.async_create_fix_flow(hass, "unknown_capacity_vacuum_robot",
                                               {"vacuum_entity": VACUUM, "check": "unknown_capacity"})
    flow.hass = hass
    assert (await flow.async_step_init())["type"] == "form"
    invalid = await flow.async_step_init({"capacity_ml": 20})
    assert invalid["type"] == "form" and invalid["errors"] == {"capacity_ml": "invalid_capacity"}
    assert (await flow.async_step_init({"capacity_ml": 2750}))["type"] == "create_entry"
    assert (await storage.async_get_state())["settings"]["device_options"][VACUUM]["capacity_ml"] == 2750


async def test_health_websocket_and_duplicate_link(hass: HomeAssistant, hass_ws_client) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/health"})
    response = await client.receive_json()
    assert response["success"], response
    robot = next(r for r in response["result"]["robots"] if r["vacuum_entity"] == VACUUM)
    assert robot["refill_method"] == "dock_auto" and robot["checks"][0]["id"] == "awaiting_refill"

    await client.send_json_auto_id({"type": f"{DOMAIN}/set_device_options", "vacuum_entity": VACUUM,
                                    "options": {"capacity_ml": 99999}})
    response = await client.receive_json()
    assert not response["success"] and response["error"]["code"] == "invalid_payload"

    await client.send_json_auto_id({"type": f"{DOMAIN}/set_robot_link", "vacuum_entity": "vacuum.copy",
                                    "target": VACUUM})
    response = await client.receive_json()
    assert response["success"] and response["result"]["settings"]["robot_links"] == {"vacuum.copy": VACUUM}


async def test_diagnostics_redact_names(hass: HomeAssistant) -> None:
    await _setup(hass)
    from homeassistant.helpers import entity_registry  # noqa: F401
    from custom_components.ha_vacuum_water_monitor.diagnostics import async_get_config_entry_diagnostics

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    data = await async_get_config_entry_diagnostics(hass, entry)
    robot = next(r for r in data["robots"] if r["vacuum_entity"] == VACUUM)
    assert robot["name"] == "**REDACTED**"
    assert data["version"]


async def test_unload_removes_issues(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert await _issues(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not {k for (d, k) in ir.async_get(hass).issues if d == DOMAIN}
    await _settle(hass)


async def test_refill_reminder_blueprint_is_valid_in_home_assistant(hass: HomeAssistant) -> None:
    from pathlib import Path

    from homeassistant.components.automation.config import async_validate_config_item
    from homeassistant.components.blueprint import models
    from homeassistant.setup import async_setup_component
    from homeassistant.util import yaml as yaml_util

    assert await async_setup_component(hass, "automation", {})
    path = Path(__file__).resolve().parents[1] / "blueprints/automation/ha_vacuum_water_monitor/refill_reminder.yaml"
    from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA

    blueprint = models.Blueprint(yaml_util.load_yaml(str(path)), expected_domain="automation", schema=BLUEPRINT_SCHEMA)
    inputs = models.BlueprintInputs(blueprint, {"use_blueprint": {
        "path": "refill_reminder.yaml", "input": {"water_remaining": "sensor.robot_water_remaining"}}})
    inputs.validate()
    config = inputs.async_substitute()
    config["id"] = "refill_reminder_test"
    validated = await async_validate_config_item(hass, "refill_reminder_test", config)
    assert validated is not None and getattr(validated, "validation_error", None) is None


async def test_the_cards_refilled_button_clears_the_repair(hass: HomeAssistant, hass_ws_client) -> None:
    await _setup(hass)
    assert "awaiting_refill_vacuum_robot" in await _issues(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    assert (await client.receive_json())["success"]
    assert "awaiting_refill_vacuum_robot" not in await _issues(hass)


async def test_tank_empty_is_only_for_robots_without_an_empty_signal(hass: HomeAssistant, hass_ws_client) -> None:
    """5.9: the dock robot reports empty itself, so it gets no Tank empty button and the command is refused."""
    storage = await _setup(hass)
    with pytest.raises(AssertionError):
        _entity(hass, "button", "tank_empty")
    await storage.async_set_tank_state(VACUUM, {"used_ml": 3000, "initialized": True, "last_reset_ts": 1})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/mark_empty", "vacuum_entity": VACUUM})
    response = await client.receive_json()
    assert not response["success"] and response["error"]["code"] == "invalid_payload"
    assert not (await _tank(storage)).get("user_empty_active")


async def test_cleanings_left_sensor_and_health_track_record(hass: HomeAssistant, hass_ws_client) -> None:
    storage = await _setup(hass)
    now = dt_util.utcnow().timestamp() * 1000
    runs = [{"ts": now - i * 2 * 86_400_000, "started_ts": now - i * 2 * 86_400_000 - 3_600_000, "water": 400.0}
            for i in range(5)]
    history = [{"ts": now, "error_percent": 7.4, "accepted": True, "reason": None, "predicted_ml": 3061, "target_ml": 2850}]
    await storage.async_set_tank_state(VACUUM, {"used_ml": 1000, "initialized": True, "last_reset_ts": 1,
                                                "automatic_sessions": runs, "calibration_history": history})
    await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/health"})
    robot = next(r for r in (await client.receive_json())["result"]["robots"] if r["vacuum_entity"] == VACUUM)
    assert robot["last_tank"]["error_percent"] == 7.4
    assert robot["supply"]["water_per_cleaning_ml"] == 400
    assert robot["supply"]["days_left"] is not None
    sensor = hass.states.get(_entity(hass, "sensor", "cleanings_left"))
    assert sensor.attributes["water_per_cleaning_ml"] > 0
    assert sensor.attributes["basis_runs"] == 5
    assert int(sensor.state) >= 1


async def test_water_entities_attach_to_unique_source_device_without_taking_its_metadata(hass: HomeAssistant) -> None:
    """The supported robot registry owns its original metadata and receives VWM entities."""
    from homeassistant.helpers import device_registry as dr
    from copy import deepcopy

    await _setup(hass)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    source_entity = registry.async_get(VACUUM)
    assert source_entity and source_entity.device_id
    source = devices.async_get(source_entity.device_id)
    before = deepcopy((source.identifiers, source.name, source.name_by_user, source.area_id))
    owned = [entry for entry in registry.entities.values()
             if entry.platform == DOMAIN and f"_vacuum_robot_" in entry.unique_id]
    assert owned
    assert {entry.device_id for entry in owned} == {source_entity.device_id}
    current = devices.async_get(source_entity.device_id)
    assert (current.identifiers, current.name, current.name_by_user, current.area_id) == before


async def test_settings_broadcast_never_exposes_private_measurement_bank(hass, hass_ws_client):
    """An ordinary settings update must not put private samples on HA's event bus."""
    storage = await _setup(hass)
    private_sample = {"id": "private-marker", "device_id": VACUUM, "observed_ml": 123}
    await storage.async_set_settings({"local_measurements": {VACUUM: [private_sample]},
                                      "consumption_calibrations": {VACUUM: [{"private_fit": "marker"}]}})
    events = []
    unsub = hass.bus.async_listen(f"{DOMAIN}_state_changed", lambda event: events.append(event.data))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"sharing_intro_choice": "not_now"}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert events
    assert all("private-marker" not in repr(event) and "private_fit" not in repr(event) for event in events)
    assert (await storage.async_get_state())["settings"]["local_measurements"][VACUUM] == [private_sample]
    unsub()


async def test_capability_entities_follow_dock_signal_removal_and_return(hass: HomeAssistant, hass_ws_client) -> None:
    """A previously available action must not survive loss or return of its capability."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    registry = er.async_get(hass)
    source = registry.async_get("sensor.robot_dock_error")
    assert source is not None and source.device_id
    source_device, source_unique = source.device_id, source.unique_id
    roborock = hass.config_entries.async_entries("roborock")[0]

    async def report():
        await client.send_json_auto_id({"type": f"{DOMAIN}/health"})
        response = await client.receive_json()
        assert response["success"]
        return next(r for r in response["result"]["robots"] if r["vacuum_entity"] == VACUUM)

    initial = await report()
    assert initial["auto_refill_supported"] is True
    await client.send_json_auto_id({"type": f"{DOMAIN}/mark_empty", "vacuum_entity": VACUUM})
    assert not (await client.receive_json())["success"]
    switch = _entity(hass, "switch", "auto_refill")
    switch_unique = registry.async_get(switch).unique_id
    registry.async_update_entity(switch, name="My auto refill")
    assert hass.states.get(switch).state != "unavailable"
    registry.async_remove("sensor.robot_dock_error")
    hass.states.async_remove("sensor.robot_dock_error")
    await _settle(hass)
    without_source = await report()
    assert without_source["auto_refill_supported"] is False
    await client.send_json_auto_id({"type": f"{DOMAIN}/mark_empty", "vacuum_entity": VACUUM})
    assert (await client.receive_json())["success"]
    empty = _entity(hass, "button", "tank_empty")
    empty_unique = registry.async_get(empty).unique_id
    registry.async_update_entity(empty, name="My empty report")
    assert hass.states.get(empty).state != "unavailable"
    assert hass.states.get(switch).state == "unavailable"
    restored = registry.async_get_or_create("sensor", "roborock", source_unique, device_id=source_device,
        suggested_object_id="robot_dock_error", translation_key="dock_error", config_entry=roborock)
    assert restored.entity_id == "sensor.robot_dock_error"
    hass.states.async_set(restored.entity_id, "ok")
    await _settle(hass)
    returned = await report()
    assert returned["auto_refill_supported"] is True
    await client.send_json_auto_id({"type": f"{DOMAIN}/mark_empty", "vacuum_entity": VACUUM})
    assert not (await client.receive_json())["success"]
    assert hass.states.get(switch).state != "unavailable"
    assert hass.states.get(empty).state == "unavailable"
    assert registry.async_get(switch).unique_id == switch_unique and registry.async_get(switch).name == "My auto refill"
    assert registry.async_get(empty).unique_id == empty_unique and registry.async_get(empty).name == "My empty report"


async def test_policy_is_admin_only_and_controls_household_actions(hass, hass_ws_client, hass_admin_user):
    """Administrator saves policy; a household client can read but cannot administer or execute."""
    await _setup(hass)
    client = await hass_ws_client(hass)
    policy = {"schema": 1, "features": {"water": {
        "visible": {"mode": "household"}, "read": {"mode": "household"},
        "execute": {"mode": "admin"}}}}
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    saved = await client.receive_json()
    assert saved["success"], saved
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    denied = await client.receive_json()
    assert not denied["success"] and denied["error"]["code"] == "unauthorized"
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    denied = await client.receive_json()
    assert not denied["success"] and denied["error"]["code"] == "unauthorized"


async def test_policy_uses_distinct_users_native_permissions_scope_and_live_revocation(
    hass, hass_ws_client, hass_read_only_user, hass_read_only_access_token, local_auth, monkeypatch
):
    """Actual authenticated clients cannot elevate HA rights or keep a revoked subscription."""
    from homeassistant.auth.const import GROUP_ID_USER
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized
    from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

    storage = await _setup(hass)
    other = MockConfigEntry(domain="matter", title="Other robot")
    other.add_to_hass(hass)
    from homeassistant.helpers import device_registry as dr
    source = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id,
        identifiers={("matter", "r5-other")}, name="Other")
    second = er.async_get(hass).async_get_or_create("vacuum", "matter", "r5-other",
        device_id=source.id, config_entry=other, suggested_object_id="r5_other")
    hass.states.async_set(second.entity_id, "docked")
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 123})
    await storage.async_set_tank_state(second.entity_id, {"initialized": True, "used_ml": 999})
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    member = MockUser(name="Allowed", groups=[group]).add_to_hass(hass)
    denied_user = MockUser(name="Denied", groups=[group]).add_to_hass(hass)
    async def token(user):
        refresh = await hass.auth.async_create_refresh_token(user, client_id="https://r5-test.invalid/")
        return hass.auth.async_create_access_token(refresh)
    admin = await hass_ws_client(hass)
    allowed = await hass_ws_client(hass, await token(member))
    denied = await hass_ws_client(hass, await token(denied_user))
    read_only = await hass_ws_client(hass, hass_read_only_access_token)
    rule = {"mode": "selected_users", "user_ids": [member.id, hass_read_only_user.id], "entity_ids": [VACUUM]}
    policy = {"schema": 1, "features": {"water": {"visible": rule, "read": rule, "execute": rule},
                                         "settings": {"execute": {"mode": "admin"}}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    await allowed.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    state = await allowed.receive_json()
    assert state["success"] and VACUUM in state["result"]["tank_states"]
    assert second.entity_id not in state["result"]["tank_states"]
    await denied.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert not (await denied.receive_json())["success"]
    await read_only.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    assert not (await read_only.receive_json())["success"]
    await allowed.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": second.entity_id})
    assert not (await allowed.receive_json())["success"]
    # HA passes this real caller through its native button service.
    await hass.services.async_call("button", "press", {"entity_id": _entity(hass, "button", "refilled")},
                                   blocking=True, context=Context(user_id=member.id))
    assert (await _tank(storage))["used_ml"] == 0
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 123})
    for domain, service, payload in (
        ("number", "set_value", {"entity_id": _entity(hass, "number", "tank_capacity"), "value": 3000}),
        ("switch", "turn_off", {"entity_id": _entity(hass, "switch", "auto_refill")}),
    ):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(domain, service, payload, blocking=True, context=Context(user_id=member.id))
    before = await storage.async_get_state()
    with pytest.raises(Unauthorized):
        await hass.services.async_call(DOMAIN, "mark_refilled", {"entity_id": VACUUM}, blocking=True, context=Context())
    assert await storage.async_get_state() == before
    # Revoke while a real public action is paused immediately before Store IO.
    import asyncio
    entered, proceed = asyncio.Event(), asyncio.Event()
    original_reset = storage.async_reset_tank
    async def paused_reset(*args, **kwargs):
        entered.set()
        await proceed.wait()
        return await original_reset(*args, **kwargs)
    monkeypatch.setattr(storage, "async_reset_tank", paused_reset)
    await allowed.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    await asyncio.wait_for(entered.wait(), 3)
    policy["features"]["water"]["execute"] = {"mode": "admin"}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    proceed.set()
    assert not (await allowed.receive_json())["success"]
    assert (await _tank(storage))["used_ml"] == 123
    with pytest.raises(Unauthorized):
        await hass.services.async_call("button", "press", {"entity_id": _entity(hass, "button", "refilled")},
                                       blocking=True, context=Context(user_id=member.id))
    assert (await _tank(storage))["used_ml"] == 123

    await allowed.send_json_auto_id({"type": f"{DOMAIN}/subscribe"})
    subscription = await allowed.receive_json()
    assert subscription["success"]
    # Hold the already-read response, revoke, then prove it is not returned.
    from custom_components.ha_vacuum_water_monitor import websocket_api as vwm_ws
    original_filter = vwm_ws._filtered_result
    read_entered, release_read = asyncio.Event(), asyncio.Event()
    async def paused_filter(hass_, user_id, value):
        result = await original_filter(hass_, user_id, value)
        if user_id == member.id and isinstance(value, dict) and "tank_states" in value and "settings" in value:
            read_entered.set()
            await release_read.wait()
        return result
    monkeypatch.setattr(vwm_ws, "_filtered_result", paused_filter)
    await allowed.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    await asyncio.wait_for(read_entered.wait(), 3)
    policy["features"]["water"]["read"] = {"mode": "admin"}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    release_read.set()
    replies = [await allowed.receive_json(), await allowed.receive_json()]
    assert any(reply.get("event", {}).get("access_revoked") is True for reply in replies)
    assert any(reply.get("type") == "result" and not reply["success"] for reply in replies)
    await allowed.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert not (await allowed.receive_json())["success"]


async def test_entity_device_migration_preserves_user_registry_customizations(hass: HomeAssistant):
    """Fallback → source uses the same unique IDs, entity IDs, names and disabled flags."""
    from copy import deepcopy
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.entity_registry import RegistryEntryDisabler

    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 432,
                                               "refill_history": [{"used_before_ml": 876}]})
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    vacuum = entities.async_get(VACUUM)
    source_id = vacuum.device_id
    source = devices.async_get(source_id)
    source_before = deepcopy((source.identifiers, source.name, source.name_by_user, source.area_id))
    water = _entity(hass, "sensor", "water_remaining")
    entry_before = entities.async_get(water)
    entities.async_update_entity(water, name="My water level", disabled_by=RegistryEntryDisabler.USER)
    entities.async_update_entity(VACUUM, device_id=None)
    await _settle(hass)
    fallback = entities.async_get(water)
    assert fallback.device_id != source_id
    assert fallback.unique_id == entry_before.unique_id
    assert fallback.name == "My water level" and fallback.disabled_by == RegistryEntryDisabler.USER
    entities.async_update_entity(VACUUM, device_id=source_id)
    await _settle(hass)
    migrated = entities.async_get(water)
    assert migrated.entity_id == water and migrated.unique_id == entry_before.unique_id
    assert migrated.device_id == source_id
    assert migrated.name == "My water level" and migrated.disabled_by == RegistryEntryDisabler.USER
    current = devices.async_get(source_id)
    assert (current.identifiers, current.name, current.name_by_user, current.area_id) == source_before
    assert (await _tank(storage))["used_ml"] == 432
    assert (await _tank(storage))["refill_history"] == [{"used_before_ml": 876}]


async def test_five_sensor_contracts_have_accurate_classes_and_units(hass: HomeAssistant):
    """W28's historical count is not used to fabricate four extra sensors."""
    storage = await _setup(hass)
    from homeassistant.util import dt as dt_util
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "homeassistant", {})
    await storage.async_set_settings({"maintenance_items": [{"name": "Clean brush", "intervalDays": 30,
        "lastDone": int(dt_util.utcnow().timestamp() * 1000)}]})
    await hass.services.async_call("homeassistant", "update_entity",
        {"entity_id": _entity(hass, "sensor", "next_maintenance_due")}, blocking=True)
    checks = {
        "water_remaining": ("%", None, "measurement"),
        "water_used_since_refill": ("mL", None, "measurement"),
        "last_refill": (None, "timestamp", None),
        "next_maintenance_due": ("d", "duration", "measurement"),
        "cleanings_left": (None, None, "measurement"),
    }
    registry = er.async_get(hass)
    sensors = [entry for entry in registry.entities.values()
               if entry.platform == DOMAIN and entry.domain == "sensor" and "_vacuum_robot_" in entry.unique_id]
    assert len(sensors) == len(checks)
    for key, (unit, device_class, state_class) in checks.items():
        state = hass.states.get(_entity(hass, "sensor", key))
        assert state is not None
        assert state.attributes.get("unit_of_measurement") == unit
        assert state.attributes.get("device_class") == device_class
        assert state.attributes.get("state_class") == state_class
    remaining = hass.states.get(_entity(hass, "sensor", "water_remaining"))
    assert "source" in remaining.attributes and "uncertainty_kind" in remaining.attributes
    maintenance = hass.states.get(_entity(hass, "sensor", "next_maintenance_due"))
    assert maintenance.attributes["next_item"] == "Clean brush"
    assert maintenance.attributes["due_at"] and maintenance.attributes["interval_days"] == 30


async def test_repairs_health_share_first_interruption_source_and_time(hass, hass_ws_client):
    storage = await _setup(hass)
    incident = {"ts": 1791800000000, "reasons": ["accounting_context_changed"], "source": "area"}
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 240,
        "accounting_incomplete": True, "last_accounting_reason": "idle", "last_accounting_interruption": incident})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"sharing_intro_choice": "not_now"}})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/health"})
    health = (await client.receive_json())["result"]["robots"]
    report = next(r for r in health if r["vacuum_entity"] == VACUUM)
    check = next(c for c in report["checks"] if c["id"] == "accounting_paused")
    assert check["params"]["reason"] == "accounting_context_changed"
    assert check["params"]["source"] == "area" and check["params"]["occurred_at"] == incident["ts"]
    issues = await _issues(hass)
    issue = issues["accounting_paused_vacuum_robot"]
    assert issue.data["reason"] == check["params"]["reason"]
    assert issue.data["source"] == "area" and issue.data["occurred_at"] == incident["ts"]
    from custom_components.ha_vacuum_water_monitor import repairs
    flow = await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    placeholders = (await flow.async_step_init())["description_placeholders"]
    assert placeholders["reason"] == "accounting_context_changed" and placeholders["source"] == "area"
    assert placeholders["occurred_at"].startswith("2026-")
    assert (await _tank(storage))["last_accounting_interruption"] == incident


async def test_native_sensor_acl_is_independent_of_vwm_read_policy(hass, hass_ws_client, local_auth):
    """A sensor is a shared HA state; policy blocks VWM API, HA ACL controls it."""
    from homeassistant.auth.models import Group
    from pytest_homeassistant_custom_component.common import MockUser

    storage = await _setup(hass)
    sensor = _entity(hass, "sensor", "water_remaining")
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 123,
        "calibration_history": [{"private_marker": "never-global"}],
        "automatic_sessions": [{"ts": 123, "private_sample": "never-global"}]})
    groups = [Group(name="Sensor reader", policy={"entities": {"entity_ids": {sensor: {"read": True}}}}),
              Group(name="No sensor read", policy={"entities": {"entity_ids": {VACUUM: {"read": True}}}})]
    users = [MockUser(name="Sensor reader", groups=[groups[0]]).add_to_hass(hass),
             MockUser(name="No sensor", groups=[groups[1]]).add_to_hass(hass)]
    clients = []
    for user in users:
        refresh = await hass.auth.async_create_refresh_token(user, client_id="https://r5-test.invalid/")
        clients.append(await hass_ws_client(hass, hass.auth.async_create_access_token(refresh)))
    admin = await hass_ws_client(hass)
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": {"schema": 1,
        "features": {"water": {"read": {"mode": "admin"}}}}})
    assert (await admin.receive_json())["success"]
    await clients[0].send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    assert not (await clients[0].receive_json())["success"]
    for index, client in enumerate(clients):
        await client.send_json_auto_id({"type": "get_states"})
        states = (await client.receive_json())["result"]
        ids = {state["entity_id"] for state in states}
        assert (sensor in ids) is (index == 0)
        if index == 0:
            native = next(state for state in states if state["entity_id"] == sensor)
            assert "private_marker" not in repr(native) and "private_sample" not in repr(native)
            assert "calibration_factor" not in native["attributes"]


async def test_vwm_response_does_not_reveal_source_sensor_without_native_read(hass, hass_ws_client, local_auth):
    """Robot access does not imply access to a separately protected source."""
    from homeassistant.auth.models import Group
    from pytest_homeassistant_custom_component.common import MockUser

    storage = await _setup(hass)
    await storage.async_set_settings({"refill_settings": {VACUUM: {"lid_entity": "binary_sensor.private_lid"}}})
    group = Group(name="Robot only", policy={"entities": {"entity_ids": {VACUUM: {"read": True}}}})
    user = MockUser(name="Robot reader", groups=[group]).add_to_hass(hass)
    refresh = await hass.auth.async_create_refresh_token(user, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    response = await client.receive_json()
    assert response["success"]
    assert "binary_sensor.private_lid" not in repr(response["result"])
    assert VACUUM in repr(response["result"])


@pytest.mark.parametrize("test_phase", ["replacement", "route"])
@pytest.mark.parametrize("pause_point", ["before_resolve", "before_store"])
async def test_scoped_replacement_and_owner_change_cannot_modify_other_robot(hass, hass_ws_client, local_auth, monkeypatch, pause_point, test_phase):
    """Check actual Store targets even when routing changes after the precheck."""
    import asyncio
    from homeassistant.auth.const import GROUP_ID_USER
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
    from custom_components.ha_vacuum_water_monitor import robots

    storage = await _setup(hass)
    other = MockConfigEntry(domain="matter", title="Independent B")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id,
        identifiers={("matter", "r5-scope-b")}, name="Independent B")
    registry = er.async_get(hass)
    b = registry.async_get_or_create("vacuum", "matter", "r5-scope-b", config_entry=other,
        device_id=device.id, suggested_object_id="r5_scope_b").entity_id
    hass.states.async_set(b, "docked")
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 123})
    await storage.async_set_tank_state(b, {"initialized": True, "used_ml": 999})
    await storage.async_set_settings({"user_devices": [{"vacuum_entity": VACUUM}, {"vacuum_entity": b, "name": "B"}]})
    member = MockUser(name="A only", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    refresh = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))
    admin = await hass_ws_client(hass)
    rule = {"mode": "selected_users", "user_ids": [member.id], "entity_ids": [VACUUM]}
    policy = {"schema": 1, "features": {"water": {"read": rule, "execute": rule}, "settings": {"execute": rule}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    if test_phase == "replacement":
        await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"user_devices": [{"vacuum_entity": VACUUM}]}})
        assert not (await client.receive_json())["success"]
        assert any(item["vacuum_entity"] == b for item in (await storage.async_get_state())["settings"]["user_devices"])
        return

    entered, proceed = asyncio.Event(), asyncio.Event()
    target = robots if pause_point == "before_resolve" else storage
    name = "async_mark_refilled_with_owner" if pause_point == "before_resolve" else "async_reset_tank"
    original = getattr(target, name)
    async def pause(*args, **kwargs):
        entered.set()
        await proceed.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(target, name, pause)
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    await asyncio.wait_for(entered.wait(), 3)
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_robot_link", "vacuum_entity": VACUUM, "target": b})
    assert (await admin.receive_json())["success"]
    proceed.set()
    response = await client.receive_json()
    tanks = (await storage.async_get_state())["tank_states"]
    assert (tanks[b]["used_ml"], tanks[VACUUM]["used_ml"]) == (999, 123), response
    assert not response["success"]


@pytest.mark.parametrize("offline", [False, True])
async def test_scoped_grant_is_not_transferred_after_registry_id_reuse(hass, hass_ws_client, local_auth, offline):
    """A scope names a registry identity; an unrelated reused id gets no grant."""
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

    await _setup(hass)
    member = MockUser(name="A only", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    admin = await hass_ws_client(hass)
    rule = {"mode": "selected_users", "user_ids": [member.id], "entity_ids": [VACUUM]}
    policy = {"schema": 1, "features": {"water": {"read": rule, "execute": rule}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    registry = er.async_get(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    if offline:
        assert await hass.config_entries.async_unload(entry.entry_id)
    registry.async_update_entity(VACUUM, new_entity_id="vacuum.r5_a_renamed")
    hass.states.async_remove(VACUUM)
    hass.states.async_set("vacuum.r5_a_renamed", "docked")
    other = MockConfigEntry(domain="matter", title="Independent B")
    other.add_to_hass(hass)
    reused = registry.async_get_or_create("vacuum", "matter", "r5-reuse-b", config_entry=other,
        suggested_object_id="robot")
    assert reused.entity_id == VACUUM
    hass.states.async_set(VACUUM, "docked")
    if offline:
        assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    assert not (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    result = await client.receive_json()
    assert not result["success"] or VACUUM not in result["result"].get("tank_states", {})
    # Ordinary save preserves the old binding. An explicit two-save regrant
    # changes only this rule and authorizes the new registry identity.
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    assert not (await client.receive_json())["success"]
    rule["entity_ids"] = []
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    rule["entity_ids"] = [VACUUM]
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    assert (await client.receive_json())["success"]


async def test_measurement_execute_without_read_returns_only_acknowledgement(hass, hass_ws_client, local_auth):
    """Saving a sample does not grant read access to the fitted private bank."""
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser
    from custom_components.ha_vacuum_water_monitor.profiles import CONSUMPTION_SETTINGS

    storage = await _setup(hass)
    context = {"model_id": "roborock_s8_maxv_ultra", "sku": "EU", "dock_variant": "tank",
        "firmware": "1.0", "integration_id": "roborock", "integration_version": "1.0",
        "reservoir": "dock_clean", "action": "floor_mopping", "settings": dict.fromkeys(CONSUMPTION_SETTINGS, "not_applicable")}
    sessions = [{"ts": n, "area": 10, "context": context, "accounting_valid": True,
        "exposure_complete": True, "segments": 1} for n in (201, 202, 203)]
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 0, "automatic_sessions": sessions})
    admin = await hass_ws_client(hass)
    measurement = {"observed_ml": 100, "resolution_ml": 5, "instrument": "graduated_jug",
        "boundaries_confirmed": True, "uninterrupted": True, "purpose": "training"}
    for index in (0, 1):
        await admin.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": VACUUM,
            "session_index": index, "session_ts": sessions[index]["ts"], "measurement": measurement})
        assert (await admin.receive_json())["success"]
    member = MockUser(name="Execute only", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    refresh = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(refresh))
    policy = {"schema": 1, "features": {"measurements": {"read": {"mode": "admin"}, "execute": {"mode": "household"}}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/save_measurement", "vacuum_entity": VACUUM,
        "session_index": 2, "session_ts": sessions[2]["ts"], "measurement": measurement})
    response = await client.receive_json()
    assert response["success"] and response["result"]["saved"]
    assert "calibration" not in response["result"] and "sample_count" not in response["result"]
    assert not any(key in repr(response["result"]) for key in ("evidence", "context", "validation"))
    assert len((await storage.async_get_state())["settings"]["local_measurements"][VACUUM]) == 3


async def test_read_projection_rechecks_demotion_after_private_snapshot(hass, hass_ws_client, hass_admin_user, monkeypatch):
    """The final response must not use pre-demotion measurement/settings rights."""
    import asyncio
    from homeassistant.auth.const import GROUP_ID_USER
    from custom_components.ha_vacuum_water_monitor import websocket_api as vwm_ws

    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 12,
        "automatic_sessions": [{"private_marker": "private-session"}]})
    await storage.async_set_settings({"local_measurements": {VACUUM: [{"private_marker": "private-bank"}]}})
    client = await hass_ws_client(hass)
    policy = {"schema": 1, "features": {"measurements": {"read": {"mode": "admin"}},
        "settings": {"read": {"mode": "admin"}}}}
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await client.receive_json())["success"]
    ready, release = asyncio.Event(), asyncio.Event()
    original = vwm_ws._filtered_result
    async def pause(hass_, user_id, value):
        filtered = await original(hass_, user_id, value)
        if isinstance(value, dict) and "tank_states" in value and "settings" in value:
            ready.set()
            await release.wait()
        return filtered
    monkeypatch.setattr(vwm_ws, "_filtered_result", pause)
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_state"})
    await asyncio.wait_for(ready.wait(), 3)
    hass_admin_user.groups = [await hass.auth.async_get_group(GROUP_ID_USER)]
    assert not hass_admin_user.is_admin
    release.set()
    response = await client.receive_json()
    assert response["success"]
    assert "private-session" not in repr(response["result"])
    assert "private-bank" not in repr(response["result"])


@pytest.mark.parametrize("customization", ["disabled", "label"])
async def test_linked_fallback_cleanup_preserves_customized_device(hass, hass_ws_client, customization):
    """Link cleanup cannot destroy a user-disabled or labelled fallback."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await _setup(hass)
    entities = er.async_get(hass)
    entities.async_update_entity(VACUUM, device_id=None)
    await _settle(hass)
    sensor_id = _entity(hass, "sensor", "water_remaining")
    old = entities.async_get(sensor_id)
    devices = dr.async_get(hass)
    fallback = devices.async_get(old.device_id)
    assert fallback is not None
    if customization == "label":
        if not hasattr(fallback, "labels"):
            pytest.skip("HA version predates device labels")
        from homeassistant.helpers import label_registry as lr
        label = lr.async_get(hass).async_create(name="Keep")
        devices.async_update_device(fallback.id, labels={label.label_id})
    else:
        devices.async_update_device(fallback.id, disabled_by=dr.DeviceEntryDisabler.USER)
    second = MockConfigEntry(domain="matter", title="Independent B")
    second.add_to_hass(hass)
    device = devices.async_get_or_create(config_entry_id=second.entry_id, identifiers={("matter", "r5-label-b")})
    b = entities.async_get_or_create("vacuum", "matter", "r5-label-b", config_entry=second,
        device_id=device.id, suggested_object_id="r5_label_b").entity_id
    hass.states.async_set(b, "docked")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_robot_link", "vacuum_entity": VACUUM, "target": b})
    assert (await client.receive_json())["success"]
    await _settle(hass)
    assert devices.async_get(fallback.id) is not None
    assert entities.async_get(sensor_id) is not None
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_robot_link", "vacuum_entity": VACUUM, "target": "distinct"})
    assert (await client.receive_json())["success"]
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await _settle(hass)
    assert devices.async_get(fallback.id) is not None and entities.async_get(sensor_id) is not None


async def test_access_metadata_does_not_return_old_policy_after_last_await(hass, hass_ws_client, local_auth, monkeypatch):
    """Revocation while fetching the final principal must not return stale grants."""
    import asyncio
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser

    storage = await _setup(hass)
    member = MockUser(name="Metadata reader", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    admin = await hass_ws_client(hass)
    ready, release = asyncio.Event(), asyncio.Event()
    original_settings, original_user = storage.async_get_settings, hass.auth.async_get_user
    settings_reads = 0
    async def settings():
        nonlocal settings_reads
        result = await original_settings()
        settings_reads += 1
        return result
    async def get_user(user_id):
        if user_id == member.id and settings_reads >= 2 and not ready.is_set():
            ready.set()
            await release.wait()
        return await original_user(user_id)
    monkeypatch.setattr(storage, "async_get_settings", settings)
    monkeypatch.setattr(hass.auth, "async_get_user", get_user)
    await client.send_json_auto_id({"type": f"{DOMAIN}/get_feature_access"})
    await asyncio.wait_for(ready.wait(), 3)
    policy = {"schema": 1, "features": {"water": {"visible": {"mode": "admin"}, "read": {"mode": "admin"}}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    release.set()
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] in ("unauthorized", "feature_access_changed")


async def test_native_permission_revocation_during_store_guard_aborts_write(hass, hass_ws_client, local_auth, monkeypatch):
    """The last principal check fences the public action immediately before Store IO."""
    import asyncio
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser
    from custom_components.ha_vacuum_water_monitor import feature_access

    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 432})
    member = MockUser(name="Revoked during Store guard", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    ready, release = asyncio.Event(), asyncio.Event()
    original = feature_access.check_native_read
    async def pause(hass_, user_id, entities):
        result = await original(hass_, user_id, entities)
        if user_id == member.id and feature_access._write_guard.get() is not None:
            ready.set()
            await release.wait()
        return result
    monkeypatch.setattr(feature_access, "check_native_read", pause)
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": VACUUM})
    await asyncio.wait_for(ready.wait(), 3)
    member.groups = []
    release.set()
    assert not (await client.receive_json())["success"]
    assert (await _tank(storage))["used_ml"] == 432


async def test_policy_narrowing_before_full_replacement_does_not_remove_b(hass, hass_ws_client, local_auth, monkeypatch):
    """A policy narrowed after precheck is fenced before the replacement write."""
    import asyncio
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

    storage = await _setup(hass)
    other = MockConfigEntry(domain="matter", title="B")
    other.add_to_hass(hass)
    b = er.async_get(hass).async_get_or_create("vacuum", "matter", "f1-narrow-b", config_entry=other,
        suggested_object_id="f1_narrow_b").entity_id
    hass.states.async_set(b, "docked")
    await storage.async_set_settings({"user_devices": [{"vacuum_entity": VACUUM}, {"vacuum_entity": b, "name": "B"}]})
    member = MockUser(name="Initially wide", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    admin = await hass_ws_client(hass)
    ready, release = asyncio.Event(), asyncio.Event()
    original = storage.async_set_settings
    async def pause(patch, **kwargs):
        if "user_devices" in patch:
            ready.set()
            await release.wait()
        return await original(patch, **kwargs)
    monkeypatch.setattr(storage, "async_set_settings", pause)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "patch": {"user_devices": [{"vacuum_entity": VACUUM}]}})
    await asyncio.wait_for(ready.wait(), 3)
    rule = {"mode": "selected_users", "user_ids": [member.id], "entity_ids": [VACUUM]}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": {"schema": 1, "features": {"settings": {"execute": rule}}}})
    assert (await admin.receive_json())["success"]
    release.set()
    response = await client.receive_json()
    assert any(item["vacuum_entity"] == b for item in (await storage.async_get_state())["settings"]["user_devices"])
    assert not response["success"]


async def test_scoped_settings_refresh_accounts_for_independent_active_robot(hass, hass_ws_client, local_auth, monkeypatch):
    """A's scoped write must not block ordinary B accounting in the internal refresh."""
    from homeassistant.auth.const import GROUP_ID_USER
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
    from .test_ha_runtime import SIGNALS

    storage = await _setup(hass)
    upstream = MockConfigEntry(domain="roborock", title="Independent B")
    upstream.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=upstream.entry_id,
        identifiers={("roborock", "r5-refresh-b")}, manufacturer="Roborock",
        model="roborock.vacuum.a97", model_id="a97", name="Independent B")
    registry = er.async_get(hass)
    b = registry.async_get_or_create("vacuum", "roborock", "r5-refresh-b", config_entry=upstream,
        device_id=device.id, suggested_object_id="r5_refresh_b").entity_id
    for domain, key, _ in SIGNALS:
        registry.async_get_or_create(domain, "roborock", "r5_b_" + key, device_id=device.id,
            config_entry=upstream, suggested_object_id="r5_b_" + key, translation_key=key)
    hass.states.async_set(b, "cleaning", {"status": "cleaning"})
    hass.states.async_set("sensor.r5_b_status", "cleaning")
    hass.states.async_set("sensor.r5_b_cleaning_area", "0", {"unit_of_measurement": "m²"})
    hass.states.async_set("select.r5_b_mop_mode", "standard")
    hass.states.async_set("select.r5_b_mop_intensity", "standard")
    hass.states.async_set("sensor.r5_b_dock_error", "ok")
    hass.states.async_set("binary_sensor.r5_b_mop_attached", "on")
    await storage.async_set_tank_state(b, {"initialized": True, "used_ml": 0})
    await _settle(hass)
    before = (await storage.async_get_state())["tank_states"][b]["used_ml"]
    member = MockUser(name="Settings A only", groups=[await hass.auth.async_get_group(GROUP_ID_USER)]).add_to_hass(hass)
    token = await hass.auth.async_create_refresh_token(member, client_id="https://r5-test.invalid/")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    admin = await hass_ws_client(hass)
    rule = {"mode": "selected_users", "user_ids": [member.id], "entity_ids": [VACUUM]}
    policy = {"schema": 1, "features": {"settings": {"execute": rule}, "water": {"execute": rule}}}
    await admin.send_json_auto_id({"type": f"{DOMAIN}/set_feature_access", "policy": policy})
    assert (await admin.receive_json())["success"]
    ticker = hass.data[DOMAIN]["ticker"]
    original, emitted = ticker.run, False
    async def tick_with_new_producer(*args, **kwargs):
        nonlocal emitted
        if not emitted:
            emitted = True
            hass.states.async_set("sensor.r5_b_cleaning_area", "5", {"unit_of_measurement": "m²"})
        return await original(*args, **kwargs)
    monkeypatch.setattr(ticker, "run", tick_with_new_producer)
    await client.send_json_auto_id({"type": f"{DOMAIN}/set_settings", "partial": True,
        "patch": {"device_options": {VACUUM: {"capacity_ml": 3000}}}})
    response = await client.receive_json()
    assert response["success"] and response["result"]["bindings_refreshed"] is True
    assert emitted and (await storage.async_get_state())["tank_states"][b]["used_ml"] > before
    await client.send_json_auto_id({"type": f"{DOMAIN}/refresh_bindings"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": f"{DOMAIN}/reset_tank", "vacuum_entity": b})
    assert not (await client.receive_json())["success"]


@pytest.mark.parametrize("disabled", [False, True])
async def test_inactive_existing_switch_migrates_before_capability_returns(hass, disabled):
    """A retained legacy switch moves to its source while inactive or disabled."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.entity_registry import RegistryEntryDisabler

    storage = await _setup(hass)
    await storage.async_set_tank_state(VACUUM, {"initialized": True, "used_ml": 432,
        "refill_history": [{"used_before_ml": 876}]})
    entities, devices = er.async_get(hass), dr.async_get(hass)
    switch = _entity(hass, "switch", "auto_refill")
    old = entities.async_get(switch)
    upstream = entities.async_get(VACUUM).device_id
    entities.async_update_entity(switch, name="Keep my switch",
        disabled_by=RegistryEntryDisabler.USER if disabled else None)
    entities.async_remove("sensor.robot_dock_error")
    hass.states.async_remove("sensor.robot_dock_error")
    await _settle(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    legacy = devices.async_get_or_create(config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_vacuum_robot")}, name="Legacy")
    entities.async_update_entity(switch, device_id=legacy.id)
    assert entities.async_get(switch).device_id == legacy.id
    assert await hass.config_entries.async_reload(entry.entry_id)
    await _settle(hass)
    moved = entities.async_get(switch)
    assert moved is not None and moved.entity_id == switch and moved.unique_id == old.unique_id
    assert moved.device_id == upstream
    assert moved.name == "Keep my switch"
    assert (moved.disabled_by == RegistryEntryDisabler.USER) is disabled
    assert hass.states.get(switch) is None or hass.states.get(switch).state == "unavailable"
    assert (await _tank(hass.data[DOMAIN]["storage"]))["used_ml"] == 432
    assert (await _tank(hass.data[DOMAIN]["storage"]))["refill_history"] == [{"used_before_ml": 876}]
