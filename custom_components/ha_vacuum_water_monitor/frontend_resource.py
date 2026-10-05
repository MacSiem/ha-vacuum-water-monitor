"""Register the bundled card as a Lovelace resource when storage mode is used."""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def card_resource_url(path: str, version: str, content: bytes) -> str:
    """Refresh the browser module whenever bundled card bytes change."""
    return f"{path}?v={version}&h={sha256(content).hexdigest()[:12]}"


def _resources(hass: Any) -> Any | None:
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    return getattr(lovelace, "resources", None) or (
        lovelace.get("resources") if isinstance(lovelace, dict) else None
    )


def _mode(hass: Any) -> str | None:
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    for attribute in ("resource_mode", "mode"):
        value = getattr(lovelace, attribute, None)
        if value is not None:
            return value
    return lovelace.get("mode") if isinstance(lovelace, dict) else None


async def async_register_card_resource(hass: Any, url: str, filename: str) -> str:
    """Load the card in dashboards without duplicating a HACS resource.

    The caller uses the extra-JS fallback only when storage resources are not
    available (notably YAML mode). Existing HACS resources own their own URL.
    """
    resources = _resources(hass)
    if resources is None or not hasattr(resources, "async_create_item") or _mode(hass) == "yaml":
        return "extra_js_url"

    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True

    card_path = url.split("?", 1)[0]
    items = list(resources.async_items())
    ours = [item for item in items if item.get("url", "").split("?", 1)[0] == card_path]
    foreign = [
        item for item in items
        if item.get("url", "").split("?", 1)[0].rsplit("/", 1)[-1] == filename
        and item not in ours
    ]
    if foreign:
        for item in ours:
            await resources.async_delete_item(item["id"])
        return "existing_resource"
    if ours:
        first, *duplicates = ours
        if first.get("url") != url or first.get("type") != "module":
            await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
        for item in duplicates:
            await resources.async_delete_item(item["id"])
        return "resource"
    await resources.async_create_item({"res_type": "module", "url": url})
    return "resource"
