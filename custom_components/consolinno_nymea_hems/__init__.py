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
from homeassistant.helpers.storage import Store
from homeassistant.exceptions import ConfigEntryNotReady

# Import der Konstanten aus der lokalen const.py
from .const import (
    DOMAIN, 
    CONF_POLL_INTERVAL, 
    DEFAULT_POLL_INTERVAL, 
    CONF_SSL,
    DEFAULT_TUNNEL_PROXY_TEMPLATE,
)
from .nymea_client import NymeaClient, ha_language_to_nymea_locale
from .nymea_action_helpers import set_integration_language

_LOGGER = logging.getLogger(__name__)

# Für die persistente Ablage des zuletzt bekannten Fernverbindungs-Templates
# (siehe async_setup_entry) - überlebt HA-Neustarts, damit man nicht nach
# jedem Neustart einmalig über die Nymea-App aktivieren muss.
TUNNEL_PROXY_STORAGE_VERSION = 1

# Alle Plattformen der Integration. binary_sensor/select/button/text kamen mit
# der generischen Action-Unterstützung dazu (siehe nymea_action_helpers.py).
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.TEXT,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Consolinno Nymea HEMS from a config entry."""
    
    # Abrufen des Poll-Intervalls mit Fallback auf den Standardwert aus der const.py
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL, 
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    )

    # WICHTIG für mehrsprachige Entity-Namen: Nymea übersetzt alle
    # Anzeige-Namen (States/Actions/Settings/Thing-Klassen) selbst, wenn wir
    # beim Verbindungsaufbau die passende locale mitschicken (siehe
    # nymea_client.py). Wir nutzen dafür die in HA eingestellte Sprache -
    # ändert sich also HAs Systemsprache, ändert sich (nach einem Neuladen der
    # Integration) automatisch auch die Sprache der Nymea-Anzeige-Namen.
    nymea_locale = ha_language_to_nymea_locale(hass.config.language)

    # Setzt die Sprache für unsere EIGENEN Textbausteine (siehe
    # nymea_action_helpers.py) - "Einstellung:", "ausführen", Himmelsrichtungen
    # etc., die nicht von Nymea selbst kommen.
    set_integration_language(hass.config.language)

    # BUGFIX: Der Options-Flow (config_flow.py) schreibt geänderte Werte nach
    # entry.options - das ist der HA-Standardweg und war hier bereits korrekt
    # für CONF_POLL_INTERVAL umgesetzt (siehe oben), aber NICHT für Host/Port/
    # Zugangsdaten/SSL. Die wurden bisher immer direkt aus entry.data gelesen,
    # weshalb eine über "Optionen" geänderte IP-Adresse beim Reload komplett
    # ignoriert wurde (es wurde weiterhin die alte, ursprüngliche IP aus
    # entry.data verwendet) - inklusive Konfigurationsfehler, falls die alte
    # IP inzwischen nicht mehr erreichbar ist. Jetzt: entry.options hat
    # Vorrang, entry.data dient nur noch als Fallback (z.B. für Felder, die
    # nie über die Optionen geändert wurden).
    resolved_host = entry.options.get(CONF_HOST, entry.data[CONF_HOST])
    nymea_client = NymeaClient(
        host=resolved_host,
        port=entry.options.get(CONF_PORT, entry.data.get(CONF_PORT, 2222)),
        username=entry.options.get(CONF_USERNAME, entry.data[CONF_USERNAME]),
        password=entry.options.get(CONF_PASSWORD, entry.data[CONF_PASSWORD]),
        ssl_enabled=entry.options.get(CONF_SSL, entry.data.get(CONF_SSL, True)),
        locale=nymea_locale,
    )

    # BUGFIX: Mutable Holder für die Fernverbindungs-Konfiguration. Vorher
    # wurde diese nur EINMALIG beim Setup abgerufen - eine Änderung in der
    # Nymea-App (z.B. Fernverbindung dort ein-/ausschalten) kam nie in HA an,
    # da nie erneut nachgefragt wurde. Jetzt wird sie bei JEDEM periodischen
    # Refresh (alle poll_interval Sekunden) mit aktualisiert. Als Dict-Holder
    # (nicht als einfacher Wert), damit switch.py eine Referenz halten und
    # den jeweils aktuellsten Wert live auslesen kann, statt eine an Setup-
    # Zeit eingefrorene Kopie zu benutzen.
    # "last_known_template" bleibt auch dann erhalten, wenn "config" wieder
    # auf {} zurückfällt (Verbindung getrennt) - siehe async_update_data()
    # unten. Dadurch kann switch.py die Fernverbindung auch dann aus HA neu
    # aktivieren, wenn sie gerade aus ist, statt nur bei bereits aktiver
    # Verbindung (das war der eigentliche Bug: async_turn_on() konnte vorher
    # nur klappen, wenn die Verbindung schon an war).
    #
    # PERSISTENZ: last_known_template wird zusätzlich in einem HA-Store
    # abgelegt, damit es auch einen Neustart von Home Assistant übersteht -
    # ohne das müsste man nach JEDEM Neustart einmal in der Nymea-App
    # einschalten, bevor HA wieder aktivieren kann. Gibt es noch keinen
    # gespeicherten Wert (allererster Start), dient DEFAULT_TUNNEL_PROXY_TEMPLATE
    # (empirisch bestätigte, konstante Werte) als Startpunkt - wird aber sofort
    # durch einen echten, beobachteten Wert überschrieben, sobald einer kommt.
    tunnel_proxy_store = Store(
        hass, TUNNEL_PROXY_STORAGE_VERSION, f"{DOMAIN}_tunnel_proxy_{entry.entry_id}"
    )
    stored_template = await tunnel_proxy_store.async_load()
    tunnel_proxy_state: dict = {
        "config": {},
        "last_known_template": stored_template or dict(DEFAULT_TUNNEL_PROXY_TEMPLATE),
    }

    async def async_update_data():
        """Zentrales Update-Management für alle Plattformen."""
        try:
            things = await nymea_client.get_things()
            _LOGGER.debug(
                "consolinno_nymea_hems: Refresh liefert %d Things (Verbindung: %s)",
                len(things or []), nymea_client._is_connected,
            )
            # DIAGNOSE: Inhalt eines konkreten Things mitloggen (nicht nur die
            # Anzahl), um zu prüfen, ob die States darin wirklich befüllt sind
            # oder das Thing z.B. mit leerem "states": [] zurückkommt.
            battery = next((t for t in (things or []) if "batter" in str(t.get("name", "")).lower()), None)
            if battery:
                sample_states = battery.get("states", [])[:3]
                _LOGGER.debug(
                    "consolinno_nymea_hems: Battery-Thing '%s' (id=%s) hat %d states. Beispiele: %s",
                    battery.get("name"), battery.get("id"), len(battery.get("states", [])), sample_states,
                )
            else:
                _LOGGER.warning("consolinno_nymea_hems: Kein Thing mit 'batter' im Namen gefunden!")

            # Fernverbindungs-Konfiguration bei JEDEM Refresh mit aktualisieren
            # (separates try/except, damit ein Fehler hier nicht den ganzen
            # Coordinator-Refresh scheitern lässt).
            try:
                configurations = await nymea_client.get_configurations()
                tunnel_configs = configurations.get("tunnelProxyServerConfigurations", [])
                new_config = tunnel_configs[0] if tunnel_configs else {}

                config_changed = new_config != tunnel_proxy_state.get("config")

                # DIAGNOSE: Nur bei tatsächlicher ÄNDERUNG deutlich loggen (nicht
                # bei jedem Zyklus, sonst spammt das Log alle paar Sekunden).
                # So sieht man beim Umschalten in der Nymea-App exakt, welche
                # rohen Felder sich ändern (address/port/sslEnabled/...) - z.B.
                # ob es dort ein verstecktes "enabled"-Feld gibt oder ob wirklich
                # nur das Vorhandensein/Fehlen des Objekts der Schalter ist.
                if config_changed:
                    _LOGGER.debug(
                        "consolinno_nymea_hems: Fernverbindungs-Konfiguration hat sich geändert! "
                        "Vorher: %s -> Jetzt: %s",
                        tunnel_proxy_state.get("config"), new_config,
                    )

                tunnel_proxy_state["config"] = new_config

                # Nur überschreiben, wenn wir gerade eine ECHTE Konfiguration
                # gesehen haben - beim Verschwinden ({}) bleibt der zuletzt
                # bekannte, gültige Wert bewusst erhalten (siehe switch.py:
                # NymeaCloudConnectionSwitch.async_turn_on()).
                if new_config:
                    tunnel_proxy_state["last_known_template"] = dict(new_config)
                    # Nur bei tatsächlicher Änderung schreiben (kein Store-I/O
                    # bei jedem Poll-Zyklus, wenn sich nichts getan hat).
                    if config_changed:
                        await tunnel_proxy_store.async_save(dict(new_config))
            except Exception as tunnel_err:
                _LOGGER.debug(
                    "consolinno_nymea_hems: Configuration.GetConfigurations (Refresh) fehlgeschlagen: %s",
                    tunnel_err,
                )

            return things
        except Exception as err:
            _LOGGER.error("Fehler beim Abrufen der Daten von Nymea: %s", err)
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
        # BUGFIX: async_request_refresh() statt async_refresh() - nutzt HAs
        # eingebauten Debouncer. Jetzt, wo Notifications tatsächlich aktiviert
        # sind (siehe nymea_client.py authenticate()), können sehr viele
        # Notifications kurz hintereinander eintreffen (z.B. bei sich schnell
        # ändernden Leistungswerten) - ohne Debounce würde das zu einer Flut
        # von vollen GetThings-Aufrufen führen. async_request_refresh() bündelt
        # mehrere Anfragen innerhalb kurzer Zeit zu einem einzigen Refresh.
        hass.async_create_task(coordinator.async_request_refresh())

    nymea_client.set_event_callback(handle_nymea_event)

    try:
        await nymea_client.connect()
        await nymea_client.authenticate()
    except Exception as err:
        _LOGGER.error("Verbindung oder Authentifizierung fehlgeschlagen: %s", err)
        # BUGFIX: Vorher wurde hier "return False" genutzt. Das markiert den
        # Config Entry als endgültig fehlgeschlagen - Home Assistant versucht
        # dann NICHT automatisch erneut, es braucht ein manuelles Neuladen durch
        # den Nutzer. ConfigEntryNotReady sorgt dafür, dass HA bei vorübergehenden
        # Verbindungsproblemen (z.B. Gateway kurz nicht erreichbar) selbstständig
        # mit ansteigenden Wartezeiten neu verbindet, ohne Nutzereingriff.
        raise ConfigEntryNotReady(
            f"Verbindung zu Nymea HEMS ({resolved_host}) fehlgeschlagen: {err}"
        ) from err

    # Erstes Refresh abwarten, damit Daten für die Sensoren bereitstehen
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug(
        "consolinno_nymea_hems: Erstes Coordinator-Refresh - Erfolg: %s, Anzahl Things: %d",
        coordinator.last_update_success,
        len(coordinator.data or []),
    )

    # Thing-Klassen (inkl. stateTypes/actionTypes/displayName/writable) EINMALIG zentral
    # abrufen. Vorher haben sensor.py, switch.py und number.py jeweils unabhängig
    # voneinander dieselbe Abfrage pro Thing gemacht (bis zu 3x Netzwerk-Roundtrips
    # pro Gerät).
    thing_class_cache: dict[str, list] = {}
    # Eigenständige Aktionen (ohne zustandsgleiches Gegenstück) pro Thing-Klasse.
    thing_class_action_cache: dict[str, list] = {}
    # Settings (settingsTypes) pro Thing-Klasse - eigenes Nymea-Konzept, getrennt
    # von States/Actions: persistente Konfigurationswerte, siehe nymea_action_helpers.py.
    thing_class_settings_cache: dict[str, list] = {}
    unique_class_ids = {
        thing.get("thingClassId")
        for thing in (coordinator.data or [])
        if thing.get("thingClassId")
    }
    for class_id in unique_class_ids:
        try:
            cls_data = await nymea_client.get_thing_class_details(class_id)
            class_def = cls_data[0] if cls_data else {}
            state_types = class_def.get("stateTypes", [])
            thing_class_cache[class_id] = state_types
            thing_class_settings_cache[class_id] = class_def.get("settingsTypes", [])

            # WICHTIG für Flexibilität: Bei Nymea hat jeder schreibbare Zustand
            # (writable stateType) automatisch eine gleichnamige/gleich-ID'te
            # Aktion. Diese "Zwillings-Aktionen" sind bereits über die schreibbaren
            # Zustände in number.py/switch.py abgedeckt (via SetThingState) - wir
            # wollen sie hier NICHT nochmal als eigene Action-Entity anlegen, sonst
            # gäbe es doppelte Entities für denselben Wert.
            state_type_ids = {st.get("id") for st in state_types}
            action_types = class_def.get("actionTypes", [])
            action_type_ids = {at.get("id") for at in action_types}
            thing_class_action_cache[class_id] = [
                at for at in action_types if at.get("id") not in state_type_ids
            ]

            # BUGFIX: Ob ein State schreibbar ist, wird von Nymea nicht zuverlässig
            # über ein eigenes "writable"-Feld auf dem StateType signalisiert,
            # sondern dadurch, dass eine Action mit EXAKT DERSELBEN ID existiert
            # (bestätigt anhand der Screenshots, z.B. "Minimale Ladung" State
            # und "Setze minimalen Batteriestand" Action teilen sich eine ID).
            # Bisher wurde nur das (praktisch nie gesetzte) "writable"-Feld
            # geprüft, wodurch schreibbare States nie als number/switch, sondern
            # nur als read-only Sensor auftauchten. Wir setzen writable jetzt
            # zusätzlich (ODER-verknüpft, damit ein echtes API-Feld weiterhin
            # respektiert wird) anhand der Zwillings-Action-ID.
            for st in state_types:
                if st.get("id") in action_type_ids:
                    st["writable"] = True

            # DIAGNOSE: Zeigt beim Start (bzw. Reload) im Log genau, was pro
            # ThingClass vom Gateway zurückkam. Damit lässt sich live prüfen,
            # ob z.B. settingsTypes tatsächlich mitgeliefert werden.
            _LOGGER.debug(
                "Nymea ThingClass %s ('%s') geladen: %d states, %d eigenständige actions, %d settings",
                class_id,
                class_def.get("name", "?"),
                len(state_types),
                len(thing_class_action_cache[class_id]),
                len(thing_class_settings_cache[class_id]),
            )
            if not thing_class_settings_cache[class_id]:
                _LOGGER.debug(
                    "ThingClass %s hat KEINE settingsTypes gefunden. Vorhandene Felder in der Antwort: %s",
                    class_id, list(class_def.keys()),
                )

            # Zusätzliche Diagnose: paramTypes-Namen mitloggen. Falls settingsTypes
            # leer ist, aber die Nymea-App trotzdem eine "Einstellungen"-Ansicht
            # zeigt (z.B. PV-Einstellungen beim Inverter), stecken die Werte
            # vermutlich in paramTypes (Thing-Parameter, änderbar per Reconfigure).
            param_type_names = [p.get("name") for p in class_def.get("paramTypes", [])]
            _LOGGER.debug("ThingClass %s paramTypes: %s", class_id, param_type_names)
        except Exception as err:
            _LOGGER.error("Fehler beim Laden der Thing-Klasse %s: %s", class_id, err)
            thing_class_cache[class_id] = []
            thing_class_action_cache[class_id] = []
            thing_class_settings_cache[class_id] = []

    # Hems-API (separate Namespace, siehe nymea_client.py): PV-Konfiguration und
    # Überlastschutz (HousholdPhaseLimit) abrufen. Log bewusst drin gelassen,
    # da er die rohen Feldnamen zeigt, falls sich am Gateway mal was ändert.
    pv_configurations: list = []
    household_phase_limit = None

    try:
        pv_configurations = await nymea_client.get_pv_configurations()
        _LOGGER.debug("consolinno_nymea_hems: Hems.GetPvConfigurations Rohantwort: %s", pv_configurations)
    except Exception as err:
        _LOGGER.error("consolinno_nymea_hems: Hems.GetPvConfigurations fehlgeschlagen: %s", err)

    try:
        phase_limit_raw = await nymea_client.call_hems_method("GetHousholdPhaseLimit")
        household_phase_limit = phase_limit_raw.get("housholdPhaseLimit")
        _LOGGER.debug(
            "consolinno_nymea_hems: Hems.GetHousholdPhaseLimit Rohantwort: %s", phase_limit_raw
        )
    except Exception as err:
        _LOGGER.error("consolinno_nymea_hems: Hems.GetHousholdPhaseLimit fehlgeschlagen: %s", err)

    # Fernverbindung: kein einmaliger Abruf mehr nötig - tunnel_proxy_state
    # wurde oben bereits vom ersten Coordinator-Refresh befüllt und wird ab
    # jetzt bei jedem weiteren Refresh automatisch aktuell gehalten.

    # DIAGNOSE: Die exakten Methodennamen für Fernverbindung ein/ausschalten
    # sowie Reboot/Shutdown/Dienst-Neustart sind vermutet (siehe Kommentare in
    # nymea_client.py). JSONRPC.Introspect liefert die vom Gateway selbst
    # dokumentierte, GARANTIERT korrekte Methodenliste - wir filtern hier nur
    # nach den für uns relevanten Namen, um das Log nicht zu fluten.
    try:
        introspection = await nymea_client.introspect()
        _LOGGER.debug(
            "consolinno_nymea_hems: Introspect Top-Level-Schlüssel: %s",
            list(introspection.keys()),
        )
        # "methods" ist die vermutete Struktur - falls das nicht stimmt, zeigt
        # zumindest die Zeile oben die tatsächlichen Schlüssel zum Nachschauen.
        all_methods = list(introspection.get("methods", {}).keys())

        # Alle Namespace-Präfixe (z.B. "Integrations", "Hems", "System", ...)
        # als Übersicht, welche Bereiche es überhaupt gibt.
        namespaces = sorted({m.split(".")[0] for m in all_methods if "." in m})
        _LOGGER.debug("consolinno_nymea_hems: Alle Namespaces laut Introspect: %s", namespaces)

        # ALLE Methoden im JSONRPC-Namespace komplett (nicht gefiltert!) - dort
        # war bisher IsCloudConnected vermutet, aber offenbar falsch benannt.
        jsonrpc_methods = sorted(m for m in all_methods if m.startswith("JSONRPC."))
        _LOGGER.debug("consolinno_nymea_hems: Alle JSONRPC.*-Methoden: %s", jsonrpc_methods)

        # Und zur Sicherheit auch komplett ungefiltert alle System.*-Methoden,
        # falls die Fernverbindung doch dort statt unter JSONRPC.* liegt.
        system_methods = sorted(m for m in all_methods if m.startswith("System."))
        _LOGGER.debug("consolinno_nymea_hems: Alle System.*-Methoden: %s", system_methods)

        # Fernverbindung heißt laut Introspect "TunnelProxy" (nicht Cloud/Remote)!
        # Komplette Configuration.*-Methodenliste, um zu sehen, ob es einen
        # Get/Status-Aufruf gibt, den unser Stichwort-Filter übersehen hat.
        configuration_methods = sorted(m for m in all_methods if m.startswith("Configuration."))
        _LOGGER.debug("consolinno_nymea_hems: Alle Configuration.*-Methoden: %s", configuration_methods)

        # Typdefinition von TunnelProxyServerConfiguration, um zu sehen, welche
        # Felder beim Aktivieren (SetTunnelProxyServerConfiguration) nötig sind.
        types = introspection.get("types", {})
        tunnel_type = types.get("TunnelProxyServerConfiguration")
        _LOGGER.debug(
            "consolinno_nymea_hems: Typdefinition TunnelProxyServerConfiguration: %s", tunnel_type
        )

        relevant = [
            m for m in all_methods
            if "cloud" in m.lower() or "reboot" in m.lower()
            or "shutdown" in m.lower() or "restart" in m.lower()
            or "remote" in m.lower() or "p2p" in m.lower()
            or "tunnel" in m.lower() or "aws" in m.lower()
            or "proxy" in m.lower() or "relay" in m.lower()
        ]
        _LOGGER.debug("consolinno_nymea_hems: Relevante Methoden laut Introspect: %s", relevant)

        # DIAGNOSE für Push statt Polling: Alle Configuration.*-Notifications,
        # um zu sehen, ob Nymea bei einer Änderung der TunnelProxyServer-
        # Konfiguration (z.B. Umschalten in der App) von SICH AUS eine
        # Notification schickt - dann bräuchten wir für diesen Wert gar kein
        # Polling mehr, genau wie bei den States (siehe handle_nymea_event).
        all_notifications = list(introspection.get("notifications", {}).keys())
        configuration_notifications = sorted(
            n for n in all_notifications if "configuration" in n.lower() or "tunnel" in n.lower()
        )
        _LOGGER.debug(
            "consolinno_nymea_hems: Configuration-bezogene Notifications: %s", configuration_notifications
        )
        _LOGGER.debug("consolinno_nymea_hems: ALLE Notifications: %s", sorted(all_notifications))
    except Exception as err:
        _LOGGER.error("consolinno_nymea_hems: JSONRPC.Introspect fehlgeschlagen: %s", err)

    # Daten zentral speichern
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": nymea_client,
        "coordinator": coordinator,
        "server_info": nymea_client._server_info,
        "thing_class_cache": thing_class_cache,
        "thing_class_action_cache": thing_class_action_cache,
        "thing_class_settings_cache": thing_class_settings_cache,
        # Zwischenspeicher für Aktionen mit mehreren Parametern: hier merken sich
        # die einzelnen Parameter-Entities ihren zuletzt gesetzten Wert, bis die
        # zugehörige Button-Entity die Aktion mit allen Werten zusammen auslöst.
        # Struktur: action_param_cache[thing_id][action_type_id][param_id] = value
        "action_param_cache": {},
        # Analoger Zwischenspeicher für Settings (thing-weit statt pro Action,
        # siehe nymea_action_helpers.py _SETTINGS_SENTINEL).
        "settings_param_cache": {},
        # Hems-API (separate Namespace, siehe nymea_client.py):
        # Rohe PV-Konfigurationen (Liste, ein Eintrag pro PV-Thing) - dient als
        # Ausgangswert und Vorlage beim Speichern (SetPvConfiguration erwartet
        # das komplette Objekt, nicht nur das geänderte Feld).
        "pv_configurations": pv_configurations,
        "household_phase_limit": household_phase_limit,
        "tunnel_proxy_state": tunnel_proxy_state,
        # Staging-Cache für PV-Einstellungen, analog zu settings_param_cache,
        # aber pro pvThingId statt pro normalem Thing.
        "hems_pv_param_cache": {},
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