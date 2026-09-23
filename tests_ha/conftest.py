"""Home Assistant runtime tests (pytest-homeassistant-custom-component).

Run from the repository root:
    python -m pytest tests_ha -o asyncio_mode=auto -p no:cacheprovider
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Bind the repository's custom_components namespace before Home Assistant adds
# its testing config (which ships a regular custom_components package) to sys.path.
import custom_components  # noqa: E402,F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ from the repository root."""
    yield
