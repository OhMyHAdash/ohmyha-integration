"""Talks to ohmyha.com: version info and key-checked download of the 100 % local file."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp

from .const import SITE

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=60)


class OhMyHAError(Exception):
    """Base error."""


class CannotConnect(OhMyHAError):
    """ohmyha.com unreachable."""


class InvalidAuth(OhMyHAError):
    """Key or e-mail refused."""


class BadFile(OhMyHAError):
    """Downloaded file does not match the published SHA-256."""


async def async_get_info(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Return {"version", "sha256", "bytes", "date"} of the current local file."""
    try:
        async with session.get(f"{SITE}/api/local", timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect(str(err)) from err
    if not data or not data.get("ok") or not data.get("version") or not data.get("sha256"):
        raise CannotConnect("no version published")
    return data


async def async_download(
    session: aiohttp.ClientSession, key: str, email: str, lang: str = "fr"
) -> tuple[bytes, dict[str, Any]]:
    """Download the file with the licence key, check it against the published SHA-256."""
    info = await async_get_info(session)
    body = {"key": key, "email": email, "v": info["version"], "lang": lang}
    try:
        async with session.post(f"{SITE}/api/local/download", json=body, timeout=TIMEOUT) as resp:
            if resp.status in (401, 403):
                raise InvalidAuth()
            resp.raise_for_status()
            data = await resp.read()
    except InvalidAuth:
        raise
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect(str(err)) from err
    sha = hashlib.sha256(data).hexdigest()
    if sha != info["sha256"]:
        _LOGGER.error("OhMyHA: SHA-256 %s différent de l'empreinte publiée %s, fichier refusé", sha, info["sha256"])
        raise BadFile(sha)
    return data, info
