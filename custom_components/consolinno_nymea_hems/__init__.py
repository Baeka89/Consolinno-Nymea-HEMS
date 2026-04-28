"""Vollständige __init__.py für Consolinno Nymea HEMS"""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform, 
    CONF_HOST, 
    CONF_PORT, 
    CONF_USERNAME, 
    CONF_PASSWORD
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Import der Konstanten aus der lokalen const.py
from .const import (
    DOMAIN, 
    CONF_POLL_INTERVAL, 
    DEFAULT_POLL_INTERVAL, 
    CONF_SSL
)
from .nymea_client import NymeaClient

_LOGGER = logging.getLogger(__name__)

# Liste der Plattformen - zum Testen ist hier SENSOR aktiv. 
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Consolinno Nymea HEMS from a config entry."""
    
    # Abrufen des Poll-Intervalls mit Fallback auf den Standardwert aus der const.py
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL, 
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    )

    # Initialisierung des Nymea Clients
    nymea_client = NymeaClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, 2222),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        ssl_enabled=entry.data.get(CONF_SSL, True),
    )

    async def async_update_data():
        """Zentrales Update-Management für alle Plattformen."""
        try:
            return await nymea_client.get_things()
        except Exception as err:
            raise UpdateFailed(f"Fehler beim Abrufen der Daten von Nymea: {err}")

    # Koordinator erstellt die Update-Logik
    coordinator = DataUpdateCoordinator(
        hass, 
        _LOGGER, 
        name=f"{DOMAIN}_coordinator",
        update_method=async_update_data,
        update_interval=timedelta(seconds=poll_interval),
    )

    # Callback für Push-Benachrichtigungen
    @callback
    def handle_nymea_event(event_data):
        _LOGGER.debug("Nymea Push erhalten, aktualisiere Daten")
        hass.async_create_task(coordinator.async_refresh())

    nymea_client.set_event_callback(handle_nymea_event)

    try:
        await nymea_client.connect()
        await nymea_client.authenticate()
    except Exception as err:
        _LOGGER.error("Verbindung oder Authentifizierung fehlgeschlagen: %s", err)
        return False

    # Erstes Refresh abwarten, damit Daten für die Sensoren bereitstehen
    await coordinator.async_config_entry_first_refresh()

    # Daten zentral speichern
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": nymea_client,
        "coordinator": coordinator,
        "server_info": nymea_client._server_info,
    }

    # Listener für Änderungen in den Konfigurations-Optionen
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Plattformen laden (sensor.py, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Neu laden bei Options-Änderung."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entladen der Integration und Schließen der Verbindung."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        await data["client"].close_connection()
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok