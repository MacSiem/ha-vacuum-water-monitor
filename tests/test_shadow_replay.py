"""Offline check of the read-only shadow replay used for live-test comparisons."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vwm_shadow_capture", ROOT / "scripts/shadow_capture.py")
shadow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shadow)
discovery, calc, tick = shadow.modules()

ENTITIES = [{"entity_id": "vacuum.sample_0", "platform": "roborock", "device_id": "device_0"}] + [
    {"entity_id": entity, "platform": "roborock", "device_id": "device_0", "translation_key": key}
    for entity, key in (("sensor.sample_1", "status"), ("sensor.sample_2", "cleaning_area"),
                        ("select.sample_3", "mop_mode"), ("select.sample_4", "mop_intensity"),
                        ("sensor.sample_5", "dock_error"), ("binary_sensor.sample_6", "mop_attached"))]
DEVICES = [{"id": "device_0", "manufacturer": "Roborock", "model": "roborock.vacuum.a97", "model_id": "a97"}]


def S(state, **attributes):
    return types.SimpleNamespace(state=state, attributes=attributes)


def recorded_session():
    t = 1_789_000_000_000
    events = [(t, "vacuum.sample_0", S("docked", status="charging")), (t, "sensor.sample_1", S("charging")),
              (t, "sensor.sample_2", S("0", unit_of_measurement="m²")), (t, "select.sample_3", S("standard")),
              (t, "select.sample_4", S("intense")), (t, "sensor.sample_5", S("ok")), (t, "binary_sensor.sample_6", S("on"))]
    t += 60_000
    events += [(t, "vacuum.sample_0", S("cleaning", status="cleaning")), (t, "sensor.sample_1", S("cleaning"))]
    for step in range(1, 21):  # 0.5 m² every 12 s, like Roborock's cleaning_area updates
        events.append((t + step * 12_000, "sensor.sample_2", S(str(step * 0.5), unit_of_measurement="m²")))
    t += 21 * 12_000
    events += [(t, "sensor.sample_1", S("going_to_wash_the_mop")), (t + 20_000, "sensor.sample_1", S("washing_the_mop")),
               (t + 90_000, "sensor.sample_1", S("charging")), (t + 90_000, "vacuum.sample_0", S("docked", status="charging")),
               (t + 200_000, "sensor.sample_5", S("water_empty")), (t + 400_000, "sensor.sample_5", S("ok"))]
    return sorted(events, key=lambda row: row[0]), t


class ShadowReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        states = {}
        descriptors = discovery.discover_descriptors(ENTITIES, DEVICES, states)
        cls.devices = calc.build_vacuum_devices({}, {}, descriptors)

    def test_event_replay_reports_sessions_against_the_reference_counter(self):
        events, end = recorded_session()
        reference = [(events[0][0], 1000.0), (end, 1100.0), (end + 30_000, 1240.0), (end + 500_000, 0.0)]
        report = shadow.replay(events, self.devices, calc, tick, compare=reference)
        vacuum = report["vacuums"][0]
        self.assertEqual(report["mode"], "event_driven")
        self.assertEqual(vacuum["profile"], "roborock_s8_maxv_ultra")
        session = vacuum["sessions"][0]
        self.assertAlmostEqual(session["area_m2"], 10.0)
        self.assertAlmostEqual(session["vwm_ml"], 10 * 6 * 1.3 + 150, places=1)
        self.assertEqual(session["reference_ml"], 240.0)
        self.assertIn("difference_percent", session)
        self.assertEqual([t["to"] for t in report["dock_error_transitions"]], ["ok", "water_empty", "ok"])
        self.assertEqual(report["water_levels_while_cleaning"].get("intense", 0) > 0, True)
        self.assertEqual(vacuum["refills"][0]["source"], "dock_cleared")
        self.assertEqual(vacuum["empty_tanks"], [], "an empty after a short cycle is an anchor, not a calibration tank")

    def test_heartbeat_only_replay_is_available_for_comparison(self):
        events, _ = recorded_session()
        report = shadow.replay(events, self.devices, calc, tick, poll_seconds=60)
        self.assertEqual(report["mode"], "poll_60s")
        self.assertTrue(report["vacuums"][0]["sessions"])

    def test_report_never_contains_real_identifiers(self):
        events, _ = recorded_session()
        text = repr(shadow.replay(events, self.devices, calc, tick))
        self.assertNotIn("vacuum.", text.replace("vacuum.sample", ""))


if __name__ == "__main__":
    unittest.main()
