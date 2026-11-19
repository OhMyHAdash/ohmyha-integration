"""Constants for the OhMyHA integration."""

from __future__ import annotations

import os

DOMAIN = "ohmyha"

# Site OhMyHA. OHMYHA_SITE ne sert qu'aux tests (serveur de test local).
SITE = os.environ.get("OHMYHA_SITE", "https://ohmyha.com").rstrip("/")
ONLINE_URL = f"{SITE}/ohmyha.js"

# Le fichier téléchargé est rangé hors de /config/www et servi par l'intégration.
FILE_DIR = "ohmyha"
FILE_NAME = "ohmyha.js"
URL_BASE = "/ohmyha_files"

CONF_KEY = "key"
CONF_EMAIL = "email"
CONF_MODE = "mode"
CONF_VERSION = "version"
CONF_SHA256 = "sha256"
CONF_RESOURCE_ID = "resource_id"
CONF_REPLACED = "replaced"  # ancienne ressource retirée à la demande du client, remise à la suppression

MODE_LOCAL = "local"
MODE_ONLINE = "online"
MODE_KEEP = "keep"  # installation existante gardée telle quelle

DATA_STATIC = f"{DOMAIN}_static_registered"
DATA_EXTRA_JS = f"{DOMAIN}_extra_js"
