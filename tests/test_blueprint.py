"""The refill reminder blueprint is valid YAML and targets this integration's sensor."""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "blueprints/automation/ha_vacuum_water_monitor/refill_reminder.yaml"


class _Input(str):
    pass


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: _Input(loader.construct_scalar(node)))


class BlueprintTests(unittest.TestCase):
    def setUp(self):
        self.data = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=_Loader)

    def test_metadata_and_inputs(self):
        meta = self.data["blueprint"]
        self.assertEqual(meta["domain"], "automation")
        self.assertTrue(meta["source_url"].endswith("refill_reminder.yaml"))
        self.assertEqual(meta["homeassistant"]["min_version"], "2025.1.0")
        entity_filter = meta["input"]["water_remaining"]["selector"]["entity"]["filter"][0]
        self.assertEqual(entity_filter, {"integration": "ha_vacuum_water_monitor", "domain": "sensor"})
        self.assertEqual(meta["input"]["threshold"]["default"], 20)

    def test_every_input_is_used(self):
        used = set()

        def walk(value):
            if isinstance(value, _Input):
                used.add(str(value))
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk({k: v for k, v in self.data.items() if k != "blueprint"})
        self.assertEqual(used, set(self.data["blueprint"]["input"]))

    def test_trigger_waits_a_minute_below_the_threshold(self):
        trigger = self.data["triggers"][0]
        self.assertEqual(trigger["trigger"], "numeric_state")
        self.assertEqual(trigger["for"], "00:01:00")


if __name__ == "__main__":
    unittest.main()
