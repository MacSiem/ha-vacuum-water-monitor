"""Canonical vacuum model profiles and deterministic profile resolution."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from datetime import date
from urllib.parse import urlparse
from pathlib import Path
import re
from typing import Any


class CatalogValidationError(ValueError):
    """Raised when the shipped model catalog cannot be used safely."""


_CATALOG_PATH = Path(__file__).with_name("model_profiles.json")
_RESERVOIRS = {"dock_clean", "dock_dirty", "robot_clean", "robot_dirty", "detergent"}
_TRACKED_RESERVOIRS = _RESERVOIRS | {"legacy_tank"}

# Exact values written by the pre-5.2 card when it expanded BRAND_PROFILES into
# HA Store.  This is migration data, not another resolver: it is used only to
# distinguish generated legacy values from genuinely divergent authored ones.
_LEGACY_CARD_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "roborock_s8_maxv_ultra": {
        "label": "Roborock S8 MaxV Ultra",
        "icon": "🦤",
        "water_total_ml": 3000,
        "vacuum_entity": "vacuum.roborock_s8_maxv_ultra",
        "dock_error_sensor": "sensor.roborock_s8_maxv_ultra_dock_error",
        "main_brush_sensor": "sensor.roborock_s8_maxv_ultra_main_brush_time_left",
        "side_brush_sensor": "sensor.roborock_s8_maxv_ultra_side_brush_time_left",
        "filter_time_sensor": "sensor.roborock_s8_maxv_ultra_filter_time_left",
        "sensor_dirty_sensor": "sensor.roborock_s8_maxv_ultra_sensor_time_left",
        "dock_brush_sensor": "sensor.roborock_s8_maxv_ultra_dock_maintenance_brush_time_left",
        "dock_strainer_sensor": "sensor.roborock_s8_maxv_ultra_dock_strainer_time_left",
        "dock_clean_water_sensor": "binary_sensor.roborock_s8_maxv_ultra_dock_clean_water_box",
        "dock_dirty_water_sensor": "binary_sensor.roborock_s8_maxv_ultra_dock_dirty_water_box",
        "water_shortage_sensor": "binary_sensor.roborock_s8_maxv_ultra_water_shortage",
        "mop_attached_sensor": "binary_sensor.roborock_s8_maxv_ultra_mop_attached",
        "mop_drying_sensor": "binary_sensor.roborock_s8_maxv_ultra_mop_drying",
        "area_sensor": "sensor.roborock_s8_maxv_ultra_cleaning_area",
        "duration_sensor": "sensor.roborock_s8_maxv_ultra_cleaning_time",
        "last_clean_start": "sensor.roborock_s8_maxv_ultra_last_clean_begin",
        "last_clean_end": "sensor.roborock_s8_maxv_ultra_last_clean_end",
        "charge_sensor": "sensor.roborock_s8_maxv_ultra_battery",
        "mop_mode_entity": "select.roborock_s8_maxv_ultra_mop_mode",
        "mop_intensity_entity": "select.roborock_s8_maxv_ultra_mop_intensity",
    },
    "roborock_q7": {
        "label": "Roborock Q7",
        "icon": "🦤",
        "water_total_ml": 200,
        "vacuum_entity": "vacuum.roborock_q7",
        "main_brush_sensor": "sensor.roborock_q7_main_brush_time_left",
        "side_brush_sensor": "sensor.roborock_q7_side_brush_time_left",
        "filter_time_sensor": "sensor.roborock_q7_filter_time_left",
        "charge_sensor": "sensor.roborock_q7_battery",
    },
    "dreame_l20_ultra": {
        "label": "Dreame L20 Ultra",
        "icon": "🤖",
        "water_total_ml": 4000,
        "vacuum_entity": "vacuum.dreame_l20_ultra",
        "charge_sensor": "sensor.dreame_l20_ultra_battery",
    },
    "irobot_j7": {
        "label": "iRobot j7+",
        "icon": "🦤",
        "water_total_ml": 0,
        "vacuum_entity": "vacuum.irobot_j7",
        "charge_sensor": "sensor.irobot_j7_battery_level",
    },
    "ecovacs": {
        "label": "Ecovacs (generic)",
        "icon": "🤖",
        "water_total_ml": 240,
        "vacuum_entity": "vacuum.ecovacs",
    },
    "generic": {"label": "Generic Vacuum", "icon": "🦤", "water_total_ml": 0},
}


def normalize_identifier(value: Any) -> str:
    """Normalize an HA/vendor identifier without relying on display labels."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower().replace("+", " plus ")).strip("_")
    return normalized


def load_catalog(path: Path | str = _CATALOG_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate a catalog, failing closed on malformed records."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise CatalogValidationError(f"Unable to load model profile catalog: {err}") from err
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise CatalogValidationError("Catalog must contain a non-empty profiles object")

    validated: dict[str, dict[str, Any]] = {}
    aliases: set[str] = set()
    for key, record in profiles.items():
        if normalize_identifier(key) != key:
            raise CatalogValidationError(f"Profile key must be normalized: {key!r}")
        if not isinstance(record, dict):
            raise CatalogValidationError(f"Profile {key!r} must be an object")
        identifiers = record.get("identifiers")
        if not isinstance(identifiers, list) or not identifiers or not all(
            isinstance(value, str) and normalize_identifier(value) for value in identifiers
        ):
            raise CatalogValidationError(f"Profile {key!r} has invalid identifiers")
        normalized_identifiers = [normalize_identifier(value) for value in identifiers]
        all_identifiers = set(normalized_identifiers) | {key}
        if aliases.intersection(all_identifiers):
            raise CatalogValidationError(f"Profile {key!r} reuses a catalog identifier")
        aliases.update(all_identifiers)

        reservoirs = record.get("reservoirs_ml")
        if not isinstance(reservoirs, dict) or set(reservoirs) != _RESERVOIRS:
            raise CatalogValidationError(
                f"Profile {key!r} reservoirs_ml must declare all reservoirs"
            )
        for reservoir, capacity in reservoirs.items():
            if capacity is not None and not _positive_number(capacity):
                raise CatalogValidationError(
                    f"Profile {key!r} reservoir {reservoir!r} must be positive or null"
                )
        tracked_reservoir = record.get("tracked_reservoir")
        if tracked_reservoir is not None and tracked_reservoir not in _TRACKED_RESERVOIRS:
            raise CatalogValidationError(f"Profile {key!r} has invalid tracked_reservoir")
        tracked_capacity = record.get("tracked_capacity_ml")
        if tracked_capacity is not None and not _positive_number(tracked_capacity):
            raise CatalogValidationError(f"Profile {key!r} tracked_capacity_ml must be positive or null")
        if (tracked_reservoir is None) != (tracked_capacity is None):
            raise CatalogValidationError(f"Profile {key!r} must pair tracked reservoir and capacity")
        if (
            tracked_reservoir in _RESERVOIRS
            and reservoirs[tracked_reservoir] != tracked_capacity
        ):
            raise CatalogValidationError(
                f"Profile {key!r} tracked_capacity_ml must match tracked_reservoir"
            )
        accounting = record.get("accounting")
        if not isinstance(accounting, dict) or not isinstance(
            accounting.get("usage_ml_per_m2"), dict
        ):
            raise CatalogValidationError(f"Profile {key!r} has invalid accounting")
        for rate in accounting["usage_ml_per_m2"].values():
            if not _positive_number(rate):
                raise CatalogValidationError(f"Profile {key!r} has invalid usage rate")
        minute_rates = accounting.get("usage_ml_per_active_minute", {})
        if not isinstance(minute_rates, dict) or any(
            not _positive_number(rate) for rate in minute_rates.values()
        ):
            raise CatalogValidationError(
                f"Profile {key!r} has invalid active-minute usage rate"
            )
        wash_volume = accounting.get("wash_volume_ml")
        if wash_volume is not None and not _positive_number(wash_volume):
            raise CatalogValidationError(f"Profile {key!r} has invalid wash volume")
        if accounting.get("evidence") != "not_published":
            raise CatalogValidationError(f"Profile {key!r} has invalid accounting evidence")
        if accounting["usage_ml_per_m2"] or minute_rates or wash_volume is not None:
            raise CatalogValidationError(
                f"Profile {key!r} must not ship an unverified consumption rate"
            )
        uncertainty = accounting.get("uncertainty_percent")
        if uncertainty is not None and (
            not _positive_number(uncertainty) or uncertainty > 100
        ):
            raise CatalogValidationError(
                f"Profile {key!r} has invalid uncertainty_percent"
            )
        if accounting.get("rate_signal") is not None:
            raise CatalogValidationError(f"Profile {key!r} has invalid rate_signal")
        if record.get("capability") not in {"calibration_required", "manual_only"}:
            raise CatalogValidationError(f"Profile {key!r} has invalid capability")
        if record.get("confidence") not in {"high", "medium", "low"}:
            raise CatalogValidationError(f"Profile {key!r} requires confidence")
        provenance = record.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            raise CatalogValidationError(f"Profile {key!r} requires provenance")
        for source in provenance:
            if not isinstance(source, dict) or not all(
                isinstance(source.get(field), str) and source[field]
                for field in ("source_type", "url", "claim", "last_verified")
            ):
                raise CatalogValidationError(f"Profile {key!r} has invalid provenance")
        for field in ("model_ids", "regional_skus", "observed_ha_identifiers", "integration_adapters", "available_signals", "unsupported_unknowns"):
            if not isinstance(record.get(field), list):
                raise CatalogValidationError(f"Profile {key!r} requires {field}")
        if not isinstance(record.get("sample_count"), int) or isinstance(record["sample_count"], bool) or record["sample_count"] < 0:
            raise CatalogValidationError(f"Profile {key!r} invalid sample_count")
        try:
            verified = date.fromisoformat(record["last_verified"])
            cutoff = date.fromisoformat(payload["cutoff_date"])
            if verified > cutoff:
                raise ValueError("after cutoff")
            for source in provenance:
                if date.fromisoformat(source["last_verified"]) > cutoff:
                    raise ValueError("source after cutoff")
                if urlparse(source["url"]).scheme not in {"https", "http"} or not urlparse(source["url"]).netloc:
                    raise ValueError("invalid source URL")
        except (KeyError, ValueError, TypeError) as error:
            raise CatalogValidationError(f"Profile {key!r} invalid date or URL") from error
        validated[key] = deepcopy(record)
    return validated


def resolve_profile(device: dict[str, Any] | None, catalog: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve one profile using explicit configuration before registry metadata."""
    device = device if isinstance(device, dict) else {}
    catalog = CATALOG if catalog is None else catalog
    manufacturer = normalize_identifier(device.get("manufacturer"))
    if manufacturer:
        equivalents = {"tp_link": "tapo", "tplink": "tapo", "roborock_technology_co_ltd": "roborock"}
        manufacturer = equivalents.get(manufacturer, manufacturer)
        catalog = {k:r for k,r in catalog.items() if normalize_identifier(r.get("manufacturer")) == manufacturer}
    indexes = _catalog_indexes(catalog)

    locked = _first_profile(
        indexes,
        device.get("profile_override"),
        device.get("locked_profile"),
        device.get("brand_profile") if device.get("profile_locked") else None,
    ) if device.get("profile_locked") else None
    if locked:
        return _resolved(catalog[locked], locked, "locked_override", "high")

    for source, confidence, values in (
        ("model_id", "high", (device.get("model_id"),)),
        ("model", "high", (device.get("model"),)),
        ("catalog_identifier", "medium", _identifier_values(device)),
        ("resolved_profile", "high", (device.get("profile_key"),)),
        ("legacy_brand_profile", "medium", (device.get("brand_profile"),)),
        ("entity_alias", "low", (device.get("entity_id"), device.get("vacuum_entity"))),
    ):
        profile_key = _first_profile(indexes, *values)
        if profile_key:
            return _resolved(catalog[profile_key], profile_key, source, confidence)
    return {
        "profile_key": None,
        "profile_source": "unknown",
        "profile_confidence": "none",
            "capability": "unknown",
            "evidence": None,
            "sources": [],
            "provenance": [],
        "tracked_reservoir": None,
        "tracked_capacity_ml": None,
        "reservoirs_ml": {},
        "usage_ml_per_m2": {},
        "usage_ml_per_active_minute": {},
        "wash_volume_ml": None,
        "accounting_evidence": None,
        "uncertainty_percent": None,
    }


def _identifier_values(device: dict[str, Any]) -> tuple[Any, ...]:
    values = device.get("catalog_identifiers")
    if isinstance(values, (list, tuple)):
        return tuple(values)
    return (device.get("identifier"), device.get("catalog_identifier"))


def _catalog_indexes(catalog: dict[str, dict[str, Any]]) -> dict[str, str]:
    indexes: dict[str, str] = {}
    for key, record in catalog.items():
        indexes[normalize_identifier(key)] = key
        for identifier in record["identifiers"]:
            indexes[normalize_identifier(identifier)] = key
    return indexes


def _first_profile(indexes: dict[str, str], *values: Any) -> str | None:
    for value in values:
        normalized = normalize_identifier(value)
        if normalized in indexes:
            return indexes[normalized]
        if normalized.startswith("vacuum_") and normalized[7:] in indexes:
            return indexes[normalized[7:]]
    return None


def _resolved(record: dict[str, Any], key: str, source: str, confidence: str) -> dict[str, Any]:
    accounting = record["accounting"]
    area_rates = _with_default_rate(dict(accounting["usage_ml_per_m2"]))
    minute_rates = dict(accounting.get("usage_ml_per_active_minute", {}))
    return {
        "profile_key": key,
        "profile_source": source,
        "profile_confidence": confidence,
        "capability": record["capability"],
        "evidence": accounting["evidence"],
        "sources": [item["url"] for item in record["provenance"]],
        "provenance": deepcopy(record["provenance"]),
        "tracked_reservoir": record["tracked_reservoir"],
        "tracked_capacity_ml": record["tracked_capacity_ml"],
        "reservoirs_ml": dict(record["reservoirs_ml"]),
        "usage_ml_per_m2": area_rates,
        "usage_ml_per_active_minute": minute_rates,
        "wash_volume_ml": accounting["wash_volume_ml"],
        "accounting_evidence": accounting["evidence"],
        "uncertainty_percent": None,
        "rate_signal": None,
        "time_accounting_evidence": "not_published",
        "estimated_m2_per_active_minute": None,
    }


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _with_default_rate(rates: dict[str, float]) -> dict[str, float]:
    """Use the declared middle mode when an integration exposes no mode."""
    if not rates or "default" in rates:
        return rates
    for key in ("medium", "standard", "moderate", "balanced"):
        if key in rates:
            return {**rates, "default": rates[key]}
    ordered = sorted(rates.values())
    return {**rates, "default": ordered[len(ordered) // 2]}


def legacy_profile_defaults(profile_key: Any) -> dict[str, Any]:
    """Return exact pre-5.2 card expansion defaults for migration only."""
    normalized = normalize_identifier(profile_key)
    defaults = deepcopy(_LEGACY_CARD_PROFILE_DEFAULTS.get(normalized, {}))
    canonical = _catalog_indexes(CATALOG).get(normalized)
    if canonical:
        record = CATALOG[canonical]
        accounting = record["accounting"]
        defaults.setdefault("tracked_capacity_ml", record["tracked_capacity_ml"])
        defaults.setdefault("tracked_reservoir", record["tracked_reservoir"])
        defaults.setdefault("usage_ml_per_m2", accounting["usage_ml_per_m2"])
        defaults.setdefault(
            "usage_ml_per_active_minute",
            accounting.get("usage_ml_per_active_minute", {}),
        )
        defaults.setdefault("rate_signal", accounting.get("rate_signal", "mop_mode"))
        defaults.setdefault("water_per_m2", {})
        defaults.setdefault("intensity_factor", {})
        defaults.setdefault("wash_volume_ml", accounting.get("wash_volume_ml"))
        defaults.setdefault("mop_wash_ml", None)
        defaults.setdefault("accounting_evidence", accounting.get("evidence"))
        defaults.setdefault("evidence", accounting.get("evidence"))
    return defaults


CATALOG = load_catalog()

# Consumption applicability is intentionally separate from capacity/model lookup.
# These axes are the v1 dataset contract; absent values never mean 'any'.
CONSUMPTION_SETTINGS = (
    'mop_mode', 'water_level', 'route', 'passes', 'wash_mode', 'wash_frequency',
    'wash_temperature', 'adaptive_mode', 'detergent_mode', 'cleaning_mode',
    'task_scope', 'suction_level', 'carpet_policy',
)
CONSUMPTION_AXES = (
    'model_id', 'sku', 'dock_variant', 'firmware', 'integration_id',
    'integration_version', 'reservoir', 'action',
)
_METHOD_UNITS = {'area': 'ml/m2', 'time': 'ml/min', 'action': 'ml/action', 'whole_cycle': 'ml/cycle'}
_METHOD_SIGNALS = {'area': 'area_m2', 'time': 'time_minutes', 'action': 'action_count', 'whole_cycle': 'cycle_count'}


def _known_context(context: Any) -> bool:
    if not isinstance(context, dict):
        return False
    def known(value):
        return isinstance(value, str) and value.strip() and value.lower() not in {'unknown', 'unavailable', 'none'}
    settings = context.get('settings')
    return (all(known(context.get(k)) for k in CONSUMPTION_AXES)
            and context.get('reservoir') in _RESERVOIRS
            and isinstance(settings, dict) and set(settings) == set(CONSUMPTION_SETTINGS)
            and all(known(v) for v in settings.values()))


def _compatible_context(left: dict, right: dict) -> bool:
    return (_known_context(left) and _known_context(right)
            and all(left[k] == right[k] for k in CONSUMPTION_AXES)
            and left['settings'] == right['settings'])


def _valid_consumption_record(record: Any, *, personal: bool = False) -> bool:
    if not isinstance(record, dict) or not _known_context(record.get('context')):
        return False
    method = record.get('method')
    if not isinstance(method, str) or method not in _METHOD_UNITS or record.get('unit') != _METHOD_UNITS[method]:
        return False
    if not _positive_number(record.get('coefficient')) or record.get('unknowns') != []:
        return False
    if not isinstance(record.get('scope'), str) or record.get('scope') not in {'floor_only', 'wash_only', 'whole_cycle'}:
        return False
    evidence_ids, provenance = record.get('evidence_ids'), record.get('provenance')
    if (not isinstance(record.get('id'), str) or not record['id']
            or not isinstance(evidence_ids, list) or not evidence_ids
            or any(not isinstance(v, str) or not v for v in evidence_ids)
            or not isinstance(provenance, list) or not provenance
            or any(not isinstance(v, dict) or not v.get('claim') for v in provenance)):
        return False
    if not isinstance(record.get('review'), dict) or record['review'].get('status') == 'revoked':
        return False
    if not personal:
        if record.get('accounting_contract') != 'v2' or record.get('evidence_class') != 'empirical':
            return False
        scopes = {'floor_only': {'area', 'time'}, 'wash_only': {'action'}, 'whole_cycle': {'whole_cycle'}}
        if method not in scopes[record['scope']]:
            return False
        for source in provenance:
            try:
                if source.get('type') == 'synthetic' or urlparse(source.get('url', '')).scheme != 'https':
                    return False
                date.fromisoformat(source['date'])
            except (KeyError, ValueError, TypeError):
                return False
        review = record.get('review') or {}
        validation = record.get('validation') or {}
        if not isinstance(review, dict) or not isinstance(validation, dict):
            return False
        if review.get('status') != 'approved' or not review.get('reviewer') or record.get('confidence') != 'validated':
            return False
        training, holdout = validation.get('training_ids'), validation.get('validation_ids')
        if not isinstance(training, list) or not isinstance(holdout, list) or not training or not holdout:
            return False
        if any(not isinstance(v, str) for v in training + holdout) or set(training) & set(holdout):
            return False
        if len(set(training)) < 3 or len(set(holdout)) < 5:
            return False
        if not _positive_number(validation.get('device_count')) or validation['device_count'] < 3:
            return False
        for key in ('max_error_ml', 'max_relative_error'):
            value = validation.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return False
    elif not record.get('device_id'):
        return False
    domain = record.get('exposure_domain')
    return (isinstance(domain, dict) and _positive_number(domain.get('min'))
            and _positive_number(domain.get('max')) and domain['min'] <= domain['max'])


def _valid_labeled_estimate(record: Any) -> bool:
    """Accept display-only estimates; they never become accounting profiles."""
    if not isinstance(record, dict) or record.get('kind') != 'estimate':
        return False
    context, quantity = record.get('context'), record.get('quantity')
    required = ('id', 'label', 'source_type', 'confidence', 'basis_kind', 'method')
    if (record.get('estimate_readiness') != 'labeled_runtime_estimate'
            or any(not isinstance(record.get(key), str) or not record[key] for key in required)
            or not isinstance(record.get('basis_ids'), list) or not record['basis_ids']
            or any(not isinstance(value, str) or not value for value in record['basis_ids'])
            or not isinstance(context, dict)
            or not all(isinstance(context.get(key), str) and context[key] for key in ('model_id', 'reservoir', 'action'))
            or not isinstance(quantity, dict) or quantity.get('unit') != 'ml/action'
            or not _positive_number(quantity.get('value'))
            or not isinstance(record.get('limitations'), list) or not record['limitations']
            or not isinstance(record.get('provenance'), list) or not record['provenance']
            or not isinstance(record.get('unknowns'), list) or not record['unknowns']):
        return False
    return all(isinstance(item, str) and item for item in record['limitations']) and all(
        isinstance(item, dict) and isinstance(item.get('claim'), str) and item['claim']
        for item in record['provenance'])


def _estimate_matches(context: dict, estimate_context: dict) -> bool:
    """Match every stated constraint, while null dataset fields remain unstated."""
    for key, value in estimate_context.items():
        if key == 'settings':
            if not isinstance(value, dict):
                return False
            actual = context.get('settings')
            if not isinstance(actual, dict):
                return False
            if any(required is not None and actual.get(name) != required for name, required in value.items()):
                return False
        elif value is not None and context.get(key) != value:
            return False
    return True


def resolve_consumption_profile(context: dict, signals: dict | None = None,
                                calibration: dict | None = None, dataset: dict | None = None) -> dict:
    """Select evidence for one reservoir/action without guessing missing axes.

    Callers supply canonical observed context, not display labels or model aliases.
    Configured physical sensors remain authoritative through gaps. v1 has no
    equivalence/fallback contract, so an inapplicable model remains unknown.
    """
    signals = signals if isinstance(signals, dict) else {}
    context = context if isinstance(context, dict) else {}
    dataset = dataset if isinstance(dataset, dict) else CONSUMPTION_SNAPSHOT
    def unknown(reason):
        return {'source': 'unknown', 'method': None, 'reason': reason, 'profile_id': None,
                'coefficient': None, 'evidence_ids': [], 'validation': None,
                'dataset_version': dataset.get('dataset_version')}
    if signals.get('volume_sensor_configured'):
        if not context.get('reservoir') or signals.get('reservoir') != context.get('reservoir'):
            return unknown('real_sensor_reservoir_unverified')
        volume = signals.get('volume_ml')
        if type(volume) not in (int, float) or not math.isfinite(volume) or volume < 0:
            return unknown('real_sensor_unavailable')
        return {**unknown(None), 'source': 'real_sensor', 'method': 'volume', 'volume_ml': volume}
    if not _known_context(context):
        return unknown('incomplete_context')
    personal_records = calibration if isinstance(calibration, list) else [calibration]
    candidates = [(r, 'device_calibration') for r in personal_records
                  if _valid_consumption_record(r, personal=True)
                  and r['device_id'] == context.get('device_id')
                  and _compatible_context(context, r['context'])]
    if candidates:
        pass
    else:
        if type(dataset.get('schema_version')) is not int or dataset['schema_version'] != 2:
            return unknown('legacy_evidence_only' if dataset.get('schema_version') == 1 else 'dataset_schema_unsupported')
        records = dataset.get('profiles')
        records = records if isinstance(records, list) else []
        candidates = [(r, 'verified_model') for r in records
                      if _valid_consumption_record(r) and _compatible_context(context, r['context'])]
        if not candidates:
            estimates = dataset.get('estimates')
            estimates = estimates if isinstance(estimates, list) else []
            compatible_estimates = [record for record in estimates
                                    if _valid_labeled_estimate(record)
                                    and _estimate_matches(context, record['context'])]
            if len(compatible_estimates) == 1:
                record = compatible_estimates[0]
                return {**unknown(None), 'source': 'manufacturer_data', 'method': 'action',
                        'estimate_id': record['id'], 'label': record['label'],
                        'source_type': record['source_type'], 'confidence': record['confidence'],
                        'estimate_method': record['method'], 'basis_ids': deepcopy(record['basis_ids']),
                        'limitations': deepcopy(record['limitations']), 'quantity': deepcopy(record['quantity']),
                        'provenance': deepcopy(record['provenance'])}
            return unknown('context_mismatch' if records or estimates else 'no_compatible_profile')
    eligible = []
    for record, source in candidates:
        exposure = signals.get(_METHOD_SIGNALS[record['method']])
        domain = record['exposure_domain']
        if _positive_number(exposure) and domain['min'] <= exposure <= domain['max']:
            eligible.append((record, source))
    if not eligible:
        return unknown('exposure_outside_validated_domain')
    if len(eligible) != 1:
        return unknown('ambiguous_profiles')
    record, source = eligible[0]
    return {'source': source, 'method': record['method'], 'reason': None,
            'profile_id': record['id'], 'coefficient': record['coefficient'],
            'unit': record['unit'], 'scope': record['scope'],
            'evidence_ids': deepcopy(record['evidence_ids']),
            'provenance': deepcopy(record['provenance']),
            'confidence': 'device_calibrated' if source == 'device_calibration' else record['confidence'],
            'validation': deepcopy(record.get('validation')),
            'exposure_domain': deepcopy(record['exposure_domain']),
            'dataset_version': dataset.get('dataset_version'), 'source_revision': dataset.get('source_revision')}


def _load_consumption_snapshot():
    try:
        value = json.loads(Path(__file__).with_name('consumption_snapshot.json').read_text(encoding='utf-8'))
        if isinstance(value, dict) and type(value.get('schema_version')) is int and value.get('schema_version') in {1, 2} and isinstance(value.get('profiles'), list):
            value.setdefault('estimates', [])
            return value
    except (OSError, ValueError):
        pass
    return {'schema_version': 1, 'profiles': [], 'estimates': [], 'dataset_version': None}


CONSUMPTION_SNAPSHOT = _load_consumption_snapshot()
