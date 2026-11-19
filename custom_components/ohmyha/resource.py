"""Serve the local file and register it as a Lovelace resource (storage mode) or extra module (YAML mode)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.core import HomeAssistant

from .const import DATA_EXTRA_JS, DATA_STATIC, FILE_DIR, FILE_NAME, URL_BASE

_LOGGER = logging.getLogger(__name__)


def file_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(FILE_DIR, FILE_NAME))


def local_url(version: str) -> str:
    return f"{URL_BASE}/{FILE_NAME}?v={version}"


async def async_write_file(hass: HomeAssistant, data: bytes) -> None:
    path = file_path(hass)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    await hass.async_add_executor_job(_write)


async def async_file_ok(hass: HomeAssistant, sha256: str) -> bool:
    import hashlib

    path = file_path(hass)

    def _check() -> bool:
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256

    return await hass.async_add_executor_job(_check)


async def async_remove_file(hass: HomeAssistant) -> None:
    path = file_path(hass)

    def _rm() -> None:
        if path.is_file():
            path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass

    await hass.async_add_executor_job(_rm)


async def async_register_static(hass: HomeAssistant) -> None:
    """Serve /config/ohmyha/ under /ohmyha_files (once per HA run)."""
    if hass.data.get(DATA_STATIC):
        return
    path = file_path(hass).parent
    await hass.async_add_executor_job(lambda: path.mkdir(parents=True, exist_ok=True))
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths([StaticPathConfig(URL_BASE, str(path), False)])
    except ImportError:  # HA < 2024.7
        hass.http.register_static_path(URL_BASE, str(path), False)
    hass.data[DATA_STATIC] = True


def _lovelace(hass: HomeAssistant) -> tuple[str | None, Any]:
    ll = hass.data.get("lovelace")
    if ll is None:
        return None, None
    if isinstance(ll, dict):  # HA < 2025.2
        return ll.get("resource_mode", ll.get("mode")), ll.get("resources")
    return getattr(ll, "resource_mode", None), getattr(ll, "resources", None)


async def async_list_resources(hass: HomeAssistant) -> list[dict[str, Any]]:
    _, res = _lovelace(hass)
    if res is None:
        return []
    if hasattr(res, "async_get_info"):
        await res.async_get_info()  # loads the storage collection
    return list(res.async_items() or [])


def is_ohmyha_url(url: str) -> bool:
    u = (url or "").split("?", 1)[0].lower()
    return u.endswith("/ohmyha.js") or u.endswith("/ohmyha-local.js")


async def async_find_existing(hass: HomeAssistant, own_id: str | None = None) -> list[dict[str, Any]]:
    """OhMyHA resources not managed by this integration (manual install from the guide)."""
    out = []
    for item in await async_list_resources(hass):
        if item.get("id") == own_id or str(item.get("url", "")).startswith(URL_BASE + "/"):
            continue
        if is_ohmyha_url(str(item.get("url", ""))):
            out.append(item)
    return out


def storage_mode(hass: HomeAssistant) -> bool:
    mode, res = _lovelace(hass)
    return res is not None and mode != "yaml" and hasattr(res, "async_create_item")


async def async_set_resource(hass: HomeAssistant, url: str, item_id: str | None) -> str | None:
    """Create or update our resource. Returns its id (None in YAML mode, where an extra module is used)."""
    if not storage_mode(hass):
        old = hass.data.pop(DATA_EXTRA_JS, None)
        if old and old != url:
            remove_extra_js_url(hass, old)
        if old != url:
            add_extra_js_url(hass, url)
        hass.data[DATA_EXTRA_JS] = url
        _LOGGER.info("OhMyHA: ressources Lovelace en YAML, fichier chargé comme module du frontend (%s)", url)
        return None
    _, res = _lovelace(hass)
    items = {i["id"]: i for i in await async_list_resources(hass)}
    if item_id and item_id in items:
        if items[item_id].get("url") != url:
            await res.async_update_item(item_id, {"res_type": "module", "url": url})
        return item_id
    for i in items.values():  # same URL already there (re-install): reuse it
        if i.get("url") == url:
            return i["id"]
    item = await res.async_create_item({"res_type": "module", "url": url})
    return item["id"]


async def async_delete_resource(hass: HomeAssistant, item_id: str | None) -> None:
    url = hass.data.pop(DATA_EXTRA_JS, None)
    if url:
        remove_extra_js_url(hass, url)
    if not item_id or not storage_mode(hass):
        return
    _, res = _lovelace(hass)
    if any(i["id"] == item_id for i in await async_list_resources(hass)):
        await res.async_delete_item(item_id)


async def async_delete_by_id(hass: HomeAssistant, ids: list[str]) -> None:
    if not storage_mode(hass):
        return
    _, res = _lovelace(hass)
    have = {i["id"] for i in await async_list_resources(hass)}
    for i in ids:
        if i in have:
            await res.async_delete_item(i)


async def async_restore(hass: HomeAssistant, items: list[dict[str, Any]]) -> None:
    if not items or not storage_mode(hass):
        return
    _, res = _lovelace(hass)
    have = {i.get("url") for i in await async_list_resources(hass)}
    for i in items:
        if i.get("url") and i["url"] not in have:
            await res.async_create_item({"res_type": i.get("type", "module"), "url": i["url"]})
