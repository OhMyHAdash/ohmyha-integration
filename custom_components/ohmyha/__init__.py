"""OhMyHA: installs the OhMyHA file (dashboards, themes, studio bridge) in Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import api, resource
from .const import (
    CONF_EMAIL,
    CONF_KEY,
    CONF_MODE,
    CONF_REPLACED,
    CONF_RESOURCE_ID,
    CONF_SHA256,
    CONF_VERSION,
    MODE_KEEP,
    MODE_LOCAL,
    MODE_ONLINE,
    ONLINE_URL,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    mode = entry.data.get(CONF_MODE, MODE_LOCAL)
    if mode == MODE_KEEP:
        _LOGGER.info("OhMyHA: installation existante gardée, rien n'est modifié")
        return True

    if mode == MODE_LOCAL:
        await resource.async_register_static(hass)
        if not await resource.async_file_ok(hass, entry.data.get(CONF_SHA256, "")):
            # file missing or changed on disk: download the same published version again
            try:
                data, info = await api.async_download(
                    async_get_clientsession(hass), entry.data[CONF_KEY], entry.data[CONF_EMAIL]
                )
            except api.OhMyHAError as err:
                raise ConfigEntryNotReady(f"OhMyHA file missing and download failed: {err}") from err
            await resource.async_write_file(hass, data)
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_VERSION: info["version"], CONF_SHA256: info["sha256"]}
            )
        url = resource.local_url(entry.data[CONF_VERSION])
    else:
        url = ONLINE_URL

    rid = await resource.async_set_resource(hass, url, entry.data.get(CONF_RESOURCE_ID))
    if rid != entry.data.get(CONF_RESOURCE_ID):
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_RESOURCE_ID: rid})

    entry.runtime_data = mode == MODE_LOCAL  # True = the update entity is set up
    if mode == MODE_LOCAL:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # what was set up, not entry.data: "Reconfigure" may have changed the mode just before the reload
    if getattr(entry, "runtime_data", False):
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Integration deleted: remove our resource and file, put back what we replaced."""
    if entry.data.get(CONF_MODE) == MODE_KEEP:
        return
    await resource.async_delete_resource(hass, entry.data.get(CONF_RESOURCE_ID))
    await resource.async_remove_file(hass)
    await resource.async_restore(hass, entry.data.get(CONF_REPLACED) or [])
