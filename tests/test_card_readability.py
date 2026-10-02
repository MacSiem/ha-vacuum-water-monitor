"""Informational captions must remain legible, including the later CSS fallback."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


class InformationalTextContrast(unittest.TestCase):
    def test_captions_have_normal_text_contrast_in_themes_and_fallbacks(self):
        source = (ROOT / "custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js").read_text()
        declarations = re.findall(r"--bento-text-muted:\s*var\(--([^,]+),\s*(#[0-9a-fA-F]{6})\)", source)
        # Base light, more specific dark host, then the later light render fallback.
        cases = [
            ("#ffffff", {"secondary-text-color": "#727272", "disabled-text-color": "#bdbdbd"}),
            ("#1c1c1c", {"secondary-text-color": "#9b9b9b", "disabled-text-color": "#5c5c5c"}),
            ("#f8fafc", {"secondary-text-color": "#727272", "disabled-text-color": "#bdbdbd"}),
        ]
        self.assertEqual(len(declarations), len(cases))
        for (theme_variable, fallback), (background, theme) in zip(declarations, cases):
            for foreground in (theme[theme_variable], fallback):
                with self.subTest(foreground=foreground, background=background):
                    low, high = sorted((luminance(foreground), luminance(background)))
                    self.assertGreaterEqual((high + 0.05) / (low + 0.05), 4.5)


if __name__ == "__main__":
    unittest.main()
