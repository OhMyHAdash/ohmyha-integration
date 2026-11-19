"""Config flow: optional licence key + e-mail. With a key the 100 % local file is downloaded, checked and added as a
resource; without one (visitor who has not bought yet) the online version is added. The key can be added later
with "Reconfigure"."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import api, resource
from .const import (
    CONF_EMAIL,
    CONF_KEY,
    CONF_MODE,
    CONF_REPLACED,
    CONF_SHA256,
    CONF_VERSION,
    DOMAIN,
    MODE_KEEP,
    MODE_LOCAL,
    MODE_ONLINE,
    SITE,
)


_LOGGER = logging.getLogger(__name__)


def _norm_key(k: str) -> str:
    k = k.strip()
    return k.upper() if k[:5].upper() in ("OHMY-", "BETA-") or k[:8].upper() == "GRATUIT-" else k


class OhMyHAConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the OhMyHA setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._existing: list[dict[str, Any]] = []

    async def _async_check(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Check key + e-mail. No key and no e-mail = online version, nothing to check."""
        key = _norm_key(user_input.get(CONF_KEY) or "")
        email = (user_input.get(CONF_EMAIL) or "").strip()
        mode = user_input.get(CONF_MODE, MODE_LOCAL)
        if not key and not email:
            return {CONF_KEY: "", CONF_EMAIL: "", CONF_MODE: MODE_ONLINE}, {}
        if not key or not email:
            return {}, {"base": "key_and_email"}
        session = async_get_clientsession(self.hass)
        lang = "fr" if (self.hass.config.language or "fr").startswith("fr") else "en"
        try:
            data, info = await api.async_download(session, key, email, lang)
        except api.InvalidAuth:
            return {}, {"base": "invalid_auth"}
        except api.BadFile:
            return {}, {"base": "bad_file"}
        except api.CannotConnect:
            return {}, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("OhMyHA: erreur inattendue")
            return {}, {"base": "unknown"}
        out = {CONF_KEY: key, CONF_EMAIL: email, CONF_MODE: mode}
        if mode == MODE_LOCAL:
            await resource.async_write_file(self.hass, data)
            out[CONF_VERSION] = info["version"]
            out[CONF_SHA256] = info["sha256"]
        return out, {}

    def _schema(self, values: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_KEY, default=values.get(CONF_KEY) or ""): TextSelector(),
                vol.Optional(CONF_EMAIL, default=values.get(CONF_EMAIL) or ""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.EMAIL)
                ),
                vol.Required(CONF_MODE, default=values.get(CONF_MODE) or MODE_LOCAL): SelectSelector(
                    SelectSelectorConfig(
                        options=[MODE_LOCAL, MODE_ONLINE],
                        translation_key="mode",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data, errors = await self._async_check(user_input)
            if not errors:
                self._existing = await resource.async_find_existing(self.hass)
                if self._existing:
                    return await self.async_step_existing()
                return self._create()
        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(user_input or {}),
            errors=errors,
            description_placeholders={"site": SITE},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add the licence key later (online -> 100 % local), change it, or switch mode."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_MODE) == MODE_KEEP:
            return self.async_abort(reason="keep_mode")
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._async_check(user_input)
            if not errors:
                new = {k: v for k, v in entry.data.items() if k not in (CONF_VERSION, CONF_SHA256)}
                new.update(data)
                if new[CONF_MODE] != MODE_LOCAL:
                    await resource.async_remove_file(self.hass)
                return self.async_update_reload_and_abort(entry, data=new)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(user_input or dict(entry.data)),
            errors=errors,
            description_placeholders={"site": SITE},
        )

    async def async_step_existing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An OhMyHA resource added by hand already exists: keep it (default) or let the integration take over."""
        if user_input is not None:
            if user_input["choice"] == "replace":
                self._data[CONF_REPLACED] = [
                    {"url": i.get("url"), "type": i.get("type", "module")} for i in self._existing
                ]
                await resource.async_delete_by_id(self.hass, [i["id"] for i in self._existing])
            else:
                self._data[CONF_MODE] = MODE_KEEP
                await resource.async_remove_file(self.hass)
                self._data.pop(CONF_VERSION, None)
                self._data.pop(CONF_SHA256, None)
            return self._create()
        return self.async_show_form(
            step_id="existing",
            data_schema=vol.Schema(
                {
                    vol.Required("choice", default="keep"): SelectSelector(
                        SelectSelectorConfig(
                            options=["keep", "replace"], translation_key="choice", mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            description_placeholders={"urls": ", ".join(str(i.get("url")) for i in self._existing)},
        )

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(title="OhMyHA", data=self._data)
