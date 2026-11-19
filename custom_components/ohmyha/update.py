"""Update entity: a new OhMyHA file version is installed only when the user clicks Install."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from . import api, resource
from .const import CONF_EMAIL, CONF_KEY, CONF_RESOURCE_ID, CONF_SHA256, CONF_VERSION, DOMAIN, SITE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    session = async_get_clientsession(hass)

    async def _fetch() -> dict[str, Any]:
        try:
            return await api.async_get_info(session)
        except api.CannotConnect as err:
            raise UpdateFailed(str(err)) from err

    coord = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name="OhMyHA", update_method=_fetch, update_interval=timedelta(hours=12)
    )
    await coord.async_refresh()
    async_add_entities([OhMyHAFileUpdate(coord, entry)])


class OhMyHAFileUpdate(CoordinatorEntity, UpdateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "file"
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    _attr_title = "OhMyHA"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_file"
        self._attr_release_url = f"{SITE}/local"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OhMyHA",
            "manufacturer": "OhMyHA",
            "entry_type": "service",
            "configuration_url": f"{SITE}/studio",
        }
        self._attr_in_progress = False

    @property
    def installed_version(self) -> str | None:
        return self._entry.data.get(CONF_VERSION)

    @property
    def latest_version(self) -> str | None:
        return (self.coordinator.data or {}).get("version") or self.installed_version

    @property
    def release_summary(self) -> str | None:
        d = self.coordinator.data or {}
        if not d.get("sha256"):
            return None
        return f"SHA-256 {d['sha256'][:16]}… (vérifiée au téléchargement). Après l'installation, recharge la page (Ctrl+F5)."

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        self._attr_in_progress = True
        self.async_write_ha_state()
        try:
            data, info = await api.async_download(
                async_get_clientsession(self.hass), self._entry.data[CONF_KEY], self._entry.data[CONF_EMAIL]
            )
        except api.InvalidAuth as err:
            raise HomeAssistantError("Clé OhMyHA refusée : supprime et rajoute l'intégration avec ta clé.") from err
        except api.OhMyHAError as err:
            raise HomeAssistantError(f"Mise à jour OhMyHA impossible : {err}") from err
        finally:
            self._attr_in_progress = False
        await resource.async_write_file(self.hass, data)
        rid = await resource.async_set_resource(
            self.hass, resource.local_url(info["version"]), self._entry.data.get(CONF_RESOURCE_ID)
        )
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_VERSION: info["version"], CONF_SHA256: info["sha256"], CONF_RESOURCE_ID: rid},
        )
        self.async_write_ha_state()
