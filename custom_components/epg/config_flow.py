"""Config flow for HA-EPG (fork: open-epg + custom XMLTV URL)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Final
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from bs4 import BeautifulSoup

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CUSTOM_URL,
    CONF_SOURCE_TYPE,
    DOMAIN,
    SOURCE_CUSTOM_URL,
    SOURCE_OPEN_EPG,
)

_LOGGER: Final = logging.getLogger(__name__)

DEFAULT_CUSTOM_URL = "http://homeassistant.local:8123/local/epg/humax-epg.xml"


async def fetch_text(hass: HomeAssistant, url: str) -> str | None:
    """Fetch URL body as text."""
    session = async_get_clientsession(hass)
    try:
        response = await session.get(url)
        response.raise_for_status()
        return await response.text()
    except aiohttp.ClientError as error:
        _LOGGER.error("Error fetching %s: %s", url, error)
        return None


async def _fetch_open_epg_channel_lines(hass: HomeAssistant, user_data: dict):
    """Fetch open-epg channel list lines."""
    raw_name = user_data["file_name"]
    file = "".join(raw_name.split()).lower()
    if re.search(r"\d$", raw_name):
        url = f"https://www.open-epg.com/files/{file}.xml.txt"
    else:
        url = f"https://www.open-epg.com/merged/{file}.xml.txt"
    channels = await fetch_text(hass, url)
    return channels.splitlines() if channels else None


async def _fetch_xmltv_channel_names(hass: HomeAssistant, url: str) -> list[str] | None:
    """Parse display-name values from an XMLTV document."""
    data = await fetch_text(hass, url)
    if not data or "channel" not in data:
        return None
    soup = BeautifulSoup(data, "xml")
    names: set[str] = set()
    for channel in soup.find_all("channel"):
        dn = channel.find("display-name")
        if dn and dn.text.strip():
            names.add(dn.text.strip())
        elif channel.get("id"):
            names.add(channel["id"])
    return sorted(names) if names else None


def _cache_path_for_custom(url: str) -> str:
    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    return os.path.join(os.path.dirname(__file__), f"userfiles/custom_{digest}.xml")


class EPGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EPG."""

    VERSION = 2

    def __init__(self):
        self.user_data: dict = {}
        self.available_channels: list = []

    async def async_step_user(self, user_input=None):
        """Choose data source."""
        errors = {}
        if user_input is not None:
            self.user_data[CONF_SOURCE_TYPE] = user_input[CONF_SOURCE_TYPE]
            if user_input[CONF_SOURCE_TYPE] == SOURCE_CUSTOM_URL:
                return await self.async_step_custom_url()
            return await self.async_step_open_epg()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SOURCE_TYPE, default=SOURCE_CUSTOM_URL
                    ): vol.In(
                        {
                            SOURCE_CUSTOM_URL: "Custom XMLTV URL (e.g. Humax)",
                            SOURCE_OPEN_EPG: "open-epg.com",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_custom_url(self, user_input=None):
        """Configure a local / remote XMLTV URL."""
        errors = {}
        if user_input is not None:
            url = user_input[CONF_CUSTOM_URL].strip()
            channels = await _fetch_xmltv_channel_names(self.hass, url)
            if not channels:
                errors["base"] = "invalid_custom_url"
            else:
                self.available_channels = channels
                self.user_data.update(user_input)
                self.user_data[CONF_CUSTOM_URL] = url
                self.user_data["file_name"] = (
                    urlparse(url).path.rsplit("/", 1)[-1] or "custom.xml"
                )
                self.user_data["generated"] = False
                self.user_data["file_path"] = _cache_path_for_custom(url)
                return await self.async_step_channels()

        return self.async_show_form(
            step_id="custom_url",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOM_URL, default=DEFAULT_CUSTOM_URL): str,
                    vol.Required("full_schedule", default=True): bool,
                    vol.Required("ignore_timezone_offset", default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_open_epg(self, user_input=None):
        """Configure open-epg.com source (upstream behaviour)."""
        errors = {}
        schema = vol.Schema(
            {
                vol.Required("file_name"): str,
                vol.Required("full_schedule", default=False): bool,
                vol.Required("generated", default=False): bool,
                vol.Required("ignore_timezone_offset", default=False): bool,
            }
        )
        if user_input is not None:
            if not user_input.get("generated"):
                self.available_channels = await _fetch_open_epg_channel_lines(
                    self.hass, user_input
                )
                if not self.available_channels:
                    errors["base"] = "invalid_file_name"
                    return self.async_show_form(
                        step_id="open_epg", data_schema=schema, errors=errors
                    )
            self.user_data.update(user_input)
            self.user_data[CONF_SOURCE_TYPE] = SOURCE_OPEN_EPG
            return await self.async_step_channels()

        return self.async_show_form(
            step_id="open_epg", data_schema=schema, errors=errors
        )

    async def async_step_channels(self, user_input=None):
        """Channel multi-select."""
        errors = {}
        source = self.user_data.get(CONF_SOURCE_TYPE, SOURCE_OPEN_EPG)

        if self.user_data.get("generated") and source == SOURCE_OPEN_EPG:
            file_name = os.path.basename(self.user_data["file_name"])
            self.user_data["file_path"] = os.path.join(
                os.path.dirname(__file__), f"userfiles/{file_name}.xml"
            )
            return self.async_create_entry(
                title=file_name,
                data=self.user_data,
                options=self.user_data,
            )

        if user_input is not None:
            self.user_data["selected_channels"] = user_input["channels"]
            if source == SOURCE_CUSTOM_URL:
                title = f"XMLTV ({self.user_data['file_name']})"
            else:
                file_name = os.path.basename(self.user_data["file_name"])
                self.user_data["file_path"] = os.path.join(
                    os.path.dirname(__file__),
                    f"userfiles/{''.join(file_name.split()).lower()}.xml",
                )
                title = file_name
            return self.async_create_entry(
                title=title,
                data=self.user_data,
                options=self.user_data,
            )

        if source == SOURCE_CUSTOM_URL:
            channel_options = list(self.available_channels)
        else:
            channel_options = list(
                {
                    channel.split(";")[0]
                    for channel in self.available_channels
                    if channel.strip()
                    and not channel.startswith("In total this list")
                }
            )
        channel_options.sort()
        data_schema = vol.Schema(
            {vol.Required("channels", default=[]): cv.multi_select(channel_options)}
        )
        return self.async_show_form(
            step_id="channels", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return EPGOptionsFlowHandler(config_entry)


class EPGOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — keeps open-epg path; custom URL reconfigure via re-add for now."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow (HA 2025.12+: store as _config_entry)."""
        self._config_entry = config_entry
        self.defult_data = dict(config_entry.options or config_entry.data)
        self.user_data: dict = {}
        self.available_channels: list = []

    @property
    def config_entry(self):
        return self._config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        errors = {}
        source = self.defult_data.get(CONF_SOURCE_TYPE, SOURCE_OPEN_EPG)

        if source == SOURCE_CUSTOM_URL:
            if user_input is not None:
                url = user_input[CONF_CUSTOM_URL].strip()
                channels = await _fetch_xmltv_channel_names(self.hass, url)
                if not channels:
                    errors["base"] = "invalid_custom_url"
                else:
                    self.available_channels = channels
                    self.user_data.update(self.defult_data)
                    self.user_data.update(user_input)
                    self.user_data[CONF_CUSTOM_URL] = url
                    self.user_data[CONF_SOURCE_TYPE] = SOURCE_CUSTOM_URL
                    self.user_data["file_path"] = _cache_path_for_custom(url)
                    self.user_data["file_name"] = (
                        urlparse(url).path.rsplit("/", 1)[-1] or "custom.xml"
                    )
                    return await self.async_step_channels()

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_CUSTOM_URL,
                            default=self.defult_data.get(
                                CONF_CUSTOM_URL, DEFAULT_CUSTOM_URL
                            ),
                        ): str,
                        vol.Required(
                            "full_schedule",
                            default=self.defult_data.get("full_schedule", True),
                        ): bool,
                        vol.Required(
                            "ignore_timezone_offset",
                            default=self.defult_data.get(
                                "ignore_timezone_offset", False
                            ),
                        ): bool,
                    }
                ),
                errors=errors,
            )

        if user_input is not None:
            self.user_data.update(user_input)
            self.user_data[CONF_SOURCE_TYPE] = SOURCE_OPEN_EPG
            return await self.async_step_channels()

        options_schema = vol.Schema(
            {
                vol.Required(
                    "file_name", default=self.defult_data.get("file_name")
                ): str,
                vol.Required(
                    "full_schedule",
                    default=self.defult_data.get("full_schedule", False),
                ): bool,
                vol.Required(
                    "generated", default=self.defult_data.get("generated", False)
                ): bool,
                vol.Required(
                    "ignore_timezone_offset",
                    default=self.defult_data.get("ignore_timezone_offset", False),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

    async def async_step_channels(self, user_input=None):
        """Channel selection for options."""
        errors = {}
        selected_channels = self.defult_data.get("selected_channels", [])
        source = self.user_data.get(
            CONF_SOURCE_TYPE, self.defult_data.get(CONF_SOURCE_TYPE, SOURCE_OPEN_EPG)
        )

        if self.user_data.get("generated") and source == SOURCE_OPEN_EPG:
            file_name = os.path.basename(self.user_data["file_name"])
            self.user_data["file_path"] = os.path.join(
                os.path.dirname(__file__), f"userfiles/{file_name}.xml"
            )
            return self.async_create_entry(title="", data=self.user_data)

        if user_input is not None:
            self.user_data["selected_channels"] = user_input["channels"]
            if source != SOURCE_CUSTOM_URL:
                file_name = os.path.basename(self.user_data["file_name"])
                self.user_data["file_path"] = os.path.join(
                    os.path.dirname(__file__),
                    f"userfiles/{''.join(file_name.split()).lower()}.xml",
                )
            entry = self.hass.config_entries.async_get_entry(self.config_entry.entry_id)
            if entry:
                self.hass.config_entries.async_update_entry(
                    entry, data=self.user_data, options=self.user_data
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_create_entry(title="", data=self.user_data)

        if not self.available_channels:
            if source == SOURCE_CUSTOM_URL:
                self.available_channels = await _fetch_xmltv_channel_names(
                    self.hass, self.user_data[CONF_CUSTOM_URL]
                )
            else:
                self.available_channels = await _fetch_open_epg_channel_lines(
                    self.hass, self.user_data
                )
            if not self.available_channels:
                errors["base"] = "no_channels"
                return self.async_show_form(
                    step_id="channels",
                    data_schema=vol.Schema({}),
                    errors=errors,
                )

        if source == SOURCE_CUSTOM_URL:
            channel_options = list(self.available_channels)
        else:
            channel_options = list(
                {
                    channel.split(";")[0]
                    for channel in self.available_channels
                    if channel.strip()
                    and not channel.startswith("In total this list")
                }
            )
        channel_options.sort()
        data_schema = vol.Schema(
            {
                vol.Required("channels", default=selected_channels): cv.multi_select(
                    channel_options
                )
            }
        )
        return self.async_show_form(
            step_id="channels", data_schema=data_schema, errors=errors
        )
