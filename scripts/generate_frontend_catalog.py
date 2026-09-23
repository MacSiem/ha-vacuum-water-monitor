#!/usr/bin/env python3
"""Generate the read-only card catalog from validated backend records.

Capacities and labelled estimates come from the backend resolver, so the card
shows exactly what the integration accounts with: every rate carries its basis
and uncertainty, and unknown values stay null (rendered as "unknown").
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components/ha_vacuum_water_monitor"
_spec = importlib.util.spec_from_file_location("vwm_frontend_catalog_profiles", PKG / "profiles.py")
profiles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profiles)

BASIS_LABELS = {
    "fleet_posterior": "Learned from calibrated devices of this model",
    "owner_device": "Measured accounting on an owner's device of this model",
    "manufacturer_declared": "Manufacturer-declared quantity",
    "review_measured": "Independent review measurement",
    "family_transfer": "Transferred from a closely related model",
    "class_prior": "Typical for this mop system; calibrates automatically",
    "generic_prior": "Generic mopping estimate; calibrates automatically",
}


def _display_rates(rates):
    """Show per-mode bands; a prior with only a default is shown as 'any mode'."""
    rates = dict(rates or {})
    bands = {k: v for k, v in rates.items() if k != "default"}
    if bands:
        return bands
    return {"any mode": rates["default"]} if "default" in rates else {}


def build_client_catalog():
    catalog = json.loads((PKG / "model_profiles.json").read_text())["profiles"]
    client = {}
    for key, record in catalog.items():
        caps = record["reservoirs_ml"]
        resolved = profiles.resolve_profile({"profile_key": key})
        basis = resolved.get("estimate_basis")
        client[key] = {
            "label": record["manufacturer"] + " " + record["model"],
            "tank_ml": resolved["tracked_capacity_ml"],
            "tracked_reservoir": resolved["tracked_reservoir"],
            "robot_tank_ml": caps["robot_clean"],
            "dock_clean_tank_ml": caps["dock_clean"],
            "dock_dirty_tank_ml": caps["dock_dirty"],
            "robot_clean_tank_ml": caps["robot_clean"],
            "robot_dirty_tank_ml": caps["robot_dirty"],
            "detergent_tank_ml": caps["detergent"],
            "mop_system": resolved.get("mop_system") or "unknown",
            "estimate_basis": basis,
            "estimate_label": BASIS_LABELS.get(basis),
            "uncertainty_percent": resolved.get("uncertainty_percent"),
            "water_per_m2": _display_rates(resolved.get("usage_ml_per_m2")) if basis else {},
            "mop_wash_ml": resolved.get("wash_volume_ml") if basis else None,
            "source_urls": [s["url"] for s in record["provenance"]],
            "data_quality": record["verification_status"],
            "notes": (BASIS_LABELS.get(basis, "") + ". " if basis else "")
            + "Unknown capacities stay unknown; the device calibrates its own scale from empty-tank signals.",
        }
    client["generic"] = {
        "label": "Unknown model", "tank_ml": None, "robot_tank_ml": None, "water_per_m2": {},
        "mop_wash_ml": None, "estimate_basis": None, "uncertainty_percent": None,
        "notes": "Model not recognised: set the tank capacity to enable percentages.",
    }
    return client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    client = build_client_catalog()
    source = (ROOT / "ha-vacuum-water-monitor.js").read_text()
    generated = re.sub(
        r"const CALIBRATION_DATA = \{.*?\n\};",
        lambda _: "const CALIBRATION_DATA = " + json.dumps(client, ensure_ascii=False, indent=2) + ";",
        source, count=1, flags=re.S)
    targets = [ROOT / "ha-vacuum-water-monitor.js", PKG / "www/ha-vacuum-water-monitor.js"]
    if args.check:
        if any(t.read_text() != generated for t in targets):
            raise SystemExit("Frontend catalog drift; run scripts/generate_frontend_catalog.py")
    else:
        for target in targets:
            target.write_text(generated)
    print("Frontend catalog parity PASS")


if __name__ == "__main__":
    main()
