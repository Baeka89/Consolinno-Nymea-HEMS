"""Config flow for Consolinno Nymea HEMS integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
)
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_SSL,
    CONF_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_POLL_INTERVAL,
)
from .nymea_client import NymeaClient

_LOGGER = logging.getLogger(__name__)

class NymeaHEMConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Consolinno Nymea HEMS."""

    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            try:
                client = NymeaClient(
                    host=user_input[CONF_HOST],
                    port=user_input.get(CONF_PORT, DEFAULT_PORT),
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    ssl_enabled=user_input.get(CONF_SSL, DEFAULT_SSL)
                )
                await client.authenticate()
                
                return self.async_create_entry(
                    title=f"Consolinno Nymea HEMS ({user_input[CONF_HOST]})",
                    data=user_input
                )
            except Exception as err:
                _LOGGER.error("Connection error to Nymea HEMS at %s: %s", user_input[CONF_HOST], err)
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_SSL, default=DEFAULT_SSL): bool,
            vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): cv.positive_int,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return NymeaHEMOptionsFlowHandler(config_entry)


class NymeaHEMOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Consolinno Nymea HEMS."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Wir speichern das entry explizit, so wie es async_get_options_flow übergibt.
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        """Manage the options."""
        if user_input is not None:
            # Update des Titels bei Host-Wechsel
            new_host = user_input.get(CONF_HOST)
            if new_host:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, 
                    title=f"Consolinno Nymea HEMS ({new_host})"
                )
            return self.async_create_entry(title="", data=user_input)

        # Aktuelle Werte sicher abrufen
        options = self.config_entry.options
        data = self.config_entry.data

        current_host = options.get(CONF_HOST, data.get(CONF_HOST, ""))
        current_interval = options.get(
            CONF_POLL_INTERVAL, 
            data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=current_host): str,
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=current_interval,
                ): cv.positive_int,
            }),
        )