#!/usr/bin/env python3
"""Fail-closed validator for the versioned vacuum model dataset."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vwm_catalog_profiles",
    ROOT / "custom_components/ha_vacuum_water_monitor/profiles.py",
)
assert spec and spec.loader
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)
CatalogValidationError = profiles.CatalogValidationError
load_catalog = profiles.load_catalog


def main() -> int:
    try:
        catalog = load_catalog(ROOT / "custom_components/ha_vacuum_water_monitor/model_profiles.json")
    except CatalogValidationError as error:
        print(f"invalid catalog: {error}", file=sys.stderr)
        return 1
    print(f"catalog valid: {len(catalog)} profiles; labelled estimates only, no published rates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
