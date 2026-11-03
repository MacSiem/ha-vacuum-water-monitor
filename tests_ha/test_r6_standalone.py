"""Public standalone entry point survives reload without repeating its intro."""
from homeassistant.components import frontend, persistent_notification
from homeassistant.core import HomeAssistant

from .test_ha_runtime import DOMAIN, _setup


async def test_standalone_panel_and_intro_reload(hass: HomeAssistant, hass_ws_client) -> None:
    storage = await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    panel = next(p for p in hass.data[frontend.DATA_PANELS].values()
                 if (p.config or {}).get("_panel_custom", {}).get("name") == "vwm-standalone-panel")
    assert panel.require_admin is False
    assert (await storage.async_get_state())["settings"]["standalone_intro_shown"] is True
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "persistent_notification/get"})
    first = await client.receive_json()
    intro = next(item for item in first["result"] if item["notification_id"] == "ha_vacuum_water_monitor_intro")
    assert f"/{panel.frontend_url_path}" in intro["message"]
    persistent_notification.async_dismiss(hass, "ha_vacuum_water_monitor_intro")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert any((p.config or {}).get("_panel_custom", {}).get("name") == "vwm-standalone-panel"
               for p in hass.data[frontend.DATA_PANELS].values())
    await client.send_json({"id": 2, "type": "persistent_notification/get"})
    after = await client.receive_json()
    assert all(item["notification_id"] != "ha_vacuum_water_monitor_intro" for item in after["result"])


async def test_dashboard_backup_is_private_durable_and_admin_only(hass, hass_ws_client, hass_read_only_access_token):
    await _setup(hass)
    admin = await hass_ws_client(hass)
    member = await hass_ws_client(hass, hass_read_only_access_token)
    before = {"views": [{"title": "private dashboard", "cards": []}], "future": {"keep": True}}
    after = {"views": [{"title": "private dashboard", "cards": [{"type": "custom:ha-vacuum-water-monitor"}]}], "future": {"keep": True}}
    await admin.send_json({"id": 10, "type": f"{DOMAIN}/dashboard_backup_prepare", "target": None, "before": before, "after": after})
    response = await admin.receive_json()
    assert response["success"]
    backup_id = response["result"]["id"]
    await member.send_json({"id": 11, "type": f"{DOMAIN}/dashboard_backup_get", "backup_id": backup_id})
    assert (await member.receive_json())["success"] is False
    await member.send_json({"id": 12, "type": f"{DOMAIN}/dashboard_backup_list"})
    assert (await member.receive_json())["success"] is False
    # Reload the integration and construct a fresh adapter to read the on-disk snapshot.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    hass.data[DOMAIN].pop("_dashboard_backups")
    await admin.send_json({"id": 13, "type": f"{DOMAIN}/dashboard_backup_get", "backup_id": backup_id})
    saved = await admin.receive_json()
    assert saved["success"] and saved["result"]["before"] == before and saved["result"]["after"] == after
    await admin.send_json({"id": 14, "type": f"{DOMAIN}/dashboard_backup_list"})
    listed = await admin.receive_json()
    assert listed["success"] and any(item["id"] == backup_id for item in listed["result"]["backups"])


async def test_supported_robot_produces_qualified_forecast_inputs(hass, hass_ws_client):
    """The band input comes from actual resolver, health and recorded sessions."""
    from homeassistant.util import dt as dt_util
    from .test_ha_runtime import VACUUM

    storage = await _setup(hass)
    now = dt_util.utcnow().timestamp() * 1000
    runs = [{"ts": now - i * 2 * 86_400_000,
             "started_ts": now - i * 2 * 86_400_000 - 3_600_000, "water": 400.0}
            for i in range(5)]
    await storage.async_set_tank_state(VACUUM, {"used_ml": 1000, "initialized": True,
                                                "last_reset_ts": 1, "automatic_sessions": runs})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 21, "type": f"{DOMAIN}/list_vacuums"})
    reports = await client.receive_json()
    robot = next(x for x in reports["result"]["vacuums"] if x["entity_id"] == VACUUM)
    assert robot["profile_key"] == "roborock_s8_maxv_ultra"
    await client.send_json({"id": 22, "type": f"{DOMAIN}/health"})
    health = await client.receive_json()
    report = next(x for x in health["result"]["robots"] if x["vacuum_entity"] == VACUUM)
    assert report["capacity_ml"] == 4000
    assert report["supply"]["basis_runs"] == 5
    assert report["supply"]["days_left"] is not None
    assert isinstance(report["uncertainty_percent"], (int, float)) and report["uncertainty_percent"] > 0


async def test_dashboard_backup_real_write_failure_is_not_acknowledged(hass, hass_ws_client, monkeypatch):
    from homeassistant.helpers.storage import Store
    from homeassistant.util.file import WriteError

    await _setup(hass)
    client = await hass_ws_client(hass)
    async def failed_write(*_args, **_kwargs):
        raise WriteError("synthetic low-level disk error")
    with monkeypatch.context() as fault:
        fault.setattr(Store, "_async_write_data", failed_write)
        await client.send_json({"id": 31, "type": f"{DOMAIN}/dashboard_backup_prepare", "target": None,
                                "before": {"views": []}, "after": {"views": []}})
        failed = await client.receive_json()
    assert failed["success"] is False and failed["error"]["code"] == "backup_failed"
    await client.send_json({"id": 32, "type": f"{DOMAIN}/dashboard_backup_list"})
    result = await client.receive_json()
    assert result["success"] and result["result"]["backups"] == []
