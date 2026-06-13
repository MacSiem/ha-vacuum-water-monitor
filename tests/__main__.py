"""Run the repository's pure-python tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

suite = unittest.defaultTestLoader.discover(
    str(Path(__file__).resolve().parent), pattern="test_*.py"
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
