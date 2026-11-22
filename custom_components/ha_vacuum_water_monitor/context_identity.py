"""Stable comparison of observed settings; entity IDs remain ACL locators."""
from __future__ import annotations
from typing import Any

def canonical_context(value: Any) -> Any:
    """Remove renameable locator only from source-observation identity."""
    if isinstance(value, list):
        return [canonical_context(item) for item in value]
    if isinstance(value, dict):
        observation = 'source_entity' in value and 'source' in value and 'value' in value
        return {key: canonical_context(item) for key, item in value.items()
                if not (observation and key == 'source_entity')}
    return value
