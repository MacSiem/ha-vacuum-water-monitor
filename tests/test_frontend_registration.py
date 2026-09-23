"""Regression checks for bundled-card registration requirements."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "custom_components/ha_vacuum_water_monitor/__init__.py"


class FrontendRegistrationTests(unittest.TestCase):
    def test_card_stat_runs_in_the_executor(self) -> None:
        source = INIT_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "await hass.async_add_executor_job(card_path.is_file)", source
        )

    def test_static_path_floor_and_version_surfaces_match(self) -> None:
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (
                ROOT
                / "custom_components/ha_vacuum_water_monitor/manifest.json"
            ).read_text(encoding="utf-8")
        )
        card = (
            ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js"
        ).read_bytes()

        self.assertEqual(hacs["homeassistant"], "2024.7.0")
        self.assertEqual(manifest["version"], "5.7.0-beta.4")
        self.assertIn('VERSION = "5.7.0-beta.4"', (ROOT / "custom_components/ha_vacuum_water_monitor/const.py").read_text(encoding="utf-8"))
        self.assertIn(b"v5.7.0-beta.4", card[:100])
        self.assertEqual((ROOT / "ha-vacuum-water-monitor.js").read_bytes(), card)

    def test_card_does_not_install_a_cross_card_injector(self) -> None:
        source = (ROOT / "ha-vacuum-water-monitor.js").read_text(encoding="utf-8")

        self.assertNotIn("__haToolsSplitDonateInjector", source)
        self.assertNotIn("deepFindAll(tag", source)
        self.assertNotIn("window._haToolsEsc", source)
        self.assertIn("const _esc = (s) => _escBase(_asText(s));", source)
        self.assertIn('data-source="own-card"', source)
        self.assertIn("buymeacoffee.com/macsiem", source)
        self.assertIn("${ownDonateFooter()}", source)


if __name__ == "__main__":
    unittest.main()
