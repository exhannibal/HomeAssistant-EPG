"""Constants for the EPG integration (fork: custom XMLTV URL support)."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME

DOMAIN: Final = "epg"

CONF_LANG: Final = "lang"
CONF_TITLE: Final = "title"
CONF_URL: Final = "url"
CONF_SENSOR_NAME: Final = "sensor_name"
CONF_SOURCE_TYPE: Final = "source_type"
CONF_CUSTOM_URL: Final = "custom_url"

SOURCE_OPEN_EPG: Final = "open_epg"
SOURCE_CUSTOM_URL: Final = "custom_url"

DEFAULT_NAME: Final = "epg"
UPDATE_TOPIC: Final = f"{DOMAIN}_update"

ICON: Final = "mdi:television-guide"

MIN_TIME_BETWEEN_UPDATES: Final = timedelta(days=1)
# Humax / local XMLTV caches refresh more often than open-epg daily files
MIN_TIME_BETWEEN_UPDATES_CUSTOM: Final = timedelta(hours=6)

CHANNEL_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_SENSOR_NAME): cv.string,
        vol.Optional(CONF_URL): cv.string,
    }
)
