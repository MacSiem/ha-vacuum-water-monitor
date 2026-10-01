"""Behavioral checks for Lovelace resource registration."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE = Path(__file__).resolve().parents[1] / "custom_components/ha_vacuum_water_monitor/frontend_resource.py"
SPEC = importlib.util.spec_from_file_location("vwm_frontend_resource", MODULE)
assert SPEC and SPEC.loader
frontend_resource = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontend_resource)

URL = "/ha_vacuum_water_monitor/ha-vacuum-water-monitor.js?v=5.9.0-beta.6"
FILENAME = "ha-vacuum-water-monitor.js"


class FakeResources:
    def __init__(self, items=(), loaded=True):
        self.items = [dict(item) for item in items]
        self.loaded = loaded
        self.events = []

    async def async_load(self):
        self.events.append("load")

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        self.events.append(("create", data))
        self.items.append({"id": "new", "type": data["res_type"], "url": data["url"]})

    async def async_update_item(self, id_, data):
        self.events.append(("update", id_, data))
        for item in self.items:
            if item["id"] == id_:
                item.update({"type": data["res_type"], "url": data["url"]})

    async def async_delete_item(self, id_):
        self.events.append(("delete", id_))
        self.items = [item for item in self.items if item["id"] != id_]


class FrontendResourceTests(unittest.TestCase):
    def register(self, resources=None, mode="storage"):
        lovelace = SimpleNamespace(resources=resources, resource_mode=mode)
        hass = SimpleNamespace(data={"lovelace": lovelace})
        return asyncio.run(frontend_resource.async_register_card_resource(hass, URL, FILENAME))

    def test_storage_mode_creates_one_module_resource(self):
        resources = FakeResources(loaded=False)
        self.assertEqual(self.register(resources), "resource")
        self.assertEqual(resources.events, ["load", ("create", {"res_type": "module", "url": URL})])
        self.assertEqual(self.register(resources), "resource")
        self.assertEqual(len(resources.items), 1)

    def test_existing_resource_is_updated_and_duplicates_removed(self):
        resources = FakeResources([
            {"id": "a", "type": "module", "url": URL.split("?")[0] + "?v=old"},
            {"id": "b", "type": "module", "url": URL.split("?")[0] + "?v=older"},
        ])
        self.assertEqual(self.register(resources), "resource")
        self.assertEqual(resources.items, [{"id": "a", "type": "module", "url": URL}])
        self.assertEqual([e[0] for e in resources.events], ["update", "delete"])

    def test_hacs_resource_prevents_double_loading(self):
        resources = FakeResources([
            {"id": "ours", "type": "module", "url": URL},
            {"id": "hacs", "type": "module", "url": "/hacsfiles/ha-vacuum-water-monitor/" + FILENAME},
        ])
        self.assertEqual(self.register(resources), "existing_resource")
        self.assertEqual([item["id"] for item in resources.items], ["hacs"])

    def test_yaml_mode_uses_extra_js_fallback(self):
        resources = FakeResources()
        self.assertEqual(self.register(resources, "yaml"), "extra_js_url")
        self.assertEqual(resources.events, [])


if __name__ == "__main__":
    unittest.main()
