"""The normal tick collects exposure independently of a configured water rate."""
from test_tick import tick, _Hass, _State


def test_normal_tick_records_completed_wash_and_wet_area():
    device = {"vacuum_entity": "vacuum.test", "measurement_identity": "robot-1",
              "status_sensor": "sensor.status", "area_sensor": "sensor.area",
              "cleaning_mode_entity": "select.clean", "mop_mode_entity": "select.mop",
              "mop_intensity_entity": "select.water", "wash_mode_entity": "select.wash",
              "wash_completed_sensor": "sensor.completed", "tracked_reservoir": "dock_clean",
              "dock_variant": "dock-1", "firmware": "1", "integration_adapter": "test",
              "integration_version": "1", "split_no_unmeasured_transfer": True}
    def step(state, ts, status, area, count):
        values = {"vacuum.test": _State("docked" if status == "docked" else "cleaning"),
                  "sensor.status": _State(status), "sensor.area": _State(str(area), {"unit_of_measurement": "m²"}),
                  "select.clean": _State("mopping"), "select.mop": _State("standard"),
                  "select.water": _State("medium"), "select.wash": _State("standard"),
                  "sensor.completed": _State(str(count))}
        return tick.tick_device(_Hass(values), device, state, now_ts=ts)[0]
    state = step({}, 1_000_000, "mopping", 0, 0)
    state = step(state, 1_060_000, "mopping", 2, 0)
    state = step(state, 1_120_000, "washing_mop", 2, 0)
    state = step(state, 1_180_000, "mopping", 2, 1)
    state = step(state, 1_240_000, "mopping", 3, 1)
    state = step(state, 1_300_000, "docked", 3, 1)
    sample = state["automatic_sessions"][0]["split_observation"]
    assert sample["area_m2"] == 3
    assert sample["wash_count"] == 1
    assert "observed_ml" not in sample


def test_sensor_observations_use_a_persistent_fourth_holdout_and_reject_rise():
    observer = tick.split_observation
    device = {"vacuum_entity": "vacuum.test", "tracked_reservoir": "dock_clean",
              "wash_completed_sensor": "sensor.completed", "split_no_unmeasured_transfer": True,
              "water_volume_sensor": "sensor.tank"}
    context = {"dock_variant": "dock", "firmware": "1", "integration_id": "test", "integration_version": "1"}
    settings = {"cleaning_mode": "mopping", "mop_mode": "standard", "water_level": "medium", "wash_mode_entity": "standard"}
    state = {"last_water_volume_ml": 500.0, "session_exposure_complete": True}
    def cycle(start, increase=False):
        state["session_start_ts"] = start
        for offset, area, washing, count, volume in [(0, 0., False, 0., 500.), (1, 2., False, 0., 480.),
                                                     (2, 2., True, 0., 470.), (3, 2., False, 1., 490. if increase else 450.)]:
            observer.observe(state, device, context, settings, now=start + offset * 1000, area=area,
                             wet=True, cleaning=not washing, washing=washing, completed=count,
                             volume=volume, resolution=1., volume_binding_ok=True,
                             max_interval=2000, max_area=10.)
        record = {}
        observer.finish(state, record, "docked")
        return record
    for i in range(4):
        assert "split_observation" in cycle(10000 + i * 10000)
    assert [s["purpose"] for s in state["split_sensor_measurements"]] == ["training"] * 3 + ["validation"]
    assert "split_observation" not in cycle(60000, increase=True)
    assert len(state["split_sensor_measurements"]) == 4
