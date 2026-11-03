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
    assert hass.states.get(number).attributes["source"] == "model"
    assert hass.states.get(switch).state == "on"


async def test_tank_size_entity_is_the_one_source(hass: HomeAssistant) -> None:
    storage = await _setup(hass)
    number = _entity(hass, "number", "tank_capacity")
    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 3000}, blocking=True)
    await hass.async_block_till_done()
    settings = (await storage.async_get_state())["settings"]
    assert settings["device_options"][VACUUM] == {"capacity_ml": 3000.0}
    assert float(hass.states.get(number).state) == 3000
    assert hass.states.get(number).attributes["source"] == "user_option"
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
    sensor = next(state for state in hass.states.async_all("sensor") if state.attributes.get("basis_runs") is not None)
    assert sensor.attributes["water_per_cleaning_ml"] == 400
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
    assert hass.states.get(switch).state != "unavailable"
    registry.async_remove("sensor.robot_dock_error")
    hass.states.async_remove("sensor.robot_dock_error")
    await _settle(hass)
    without_source = await report()
    assert without_source["auto_refill_supported"] is False
    await client.send_json_auto_id({"type": f"{DOMAIN}/mark_empty", "vacuum_entity": VACUUM})
    assert (await client.receive_json())["success"]
    empty = _entity(hass, "button", "tank_empty")
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
