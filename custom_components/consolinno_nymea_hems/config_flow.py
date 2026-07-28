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
from .nymea_client import NymeaClient, ha_language_to_nymea_locale

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

            client = NymeaClient(
                host=user_input[CONF_HOST],
                port=user_input.get(CONF_PORT, DEFAULT_PORT),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                ssl_enabled=user_input.get(CONF_SSL, DEFAULT_SSL),
                locale=ha_language_to_nymea_locale(self.hass.config.language),
            )
            try:
                await client.authenticate()

                return self.async_create_entry(
                    title=f"Consolinno Nymea HEMS ({user_input[CONF_HOST]})",
                    data=user_input
                )
            except ValueError:
                # NymeaClient.authenticate() wirft ValueError gezielt bei
                # falschen Zugangsdaten (Gateway war erreichbar, Login aber nicht ok).
                _LOGGER.error("Ungültige Zugangsdaten für Nymea HEMS (%s)", user_input[CONF_HOST])
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.error("Connection error to Nymea HEMS: %s", err)
                errors["base"] = "cannot_connect"
            finally:
                # Verbindung des Test-Clients in jedem Fall schließen, sonst bleiben
                # Socket + Listener-/Keepalive-Tasks bei jedem Einrichtungsversuch offen.
                await client.close_connection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SSL, default=DEFAULT_SSL): bool,
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): cv.positive_int,
            }),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return NymeaHEMOptionsFlowHandler(config_entry)


class NymeaHEMOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Consolinno Nymea HEMS."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Wir weisen das entry manuell zu, da super().__init__ in dieser HA Version 
        # keine Argumente akzeptiert.
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Wir nutzen das gespeicherte _config_entry
        entry = self._config_entry
        options = entry.options
        data = entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_HOST, 
                    default=options.get(CONF_HOST, data.get(CONF_HOST, ""))
                ): str,
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
                ): cv.positive_int,
            }),
        )