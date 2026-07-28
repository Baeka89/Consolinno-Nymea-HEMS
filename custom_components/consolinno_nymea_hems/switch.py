import asyncio
import logging
import uuid
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .nymea_action_helpers import (
    iter_standalone_actions,
    iter_thing_settings,
    classify_param,
    get_param_default,
    get_current_setting_value,
    get_staged_value,
    set_staged_value,
    get_staged_params,
    get_staged_setting,
    set_staged_setting,
    build_device_info,
    build_system_device_info,
    action_entity_name,
    settings_entity_name,
    get_staged_pv_value,
    set_staged_pv_value,
    find_thing_by_id,
    t,
    thing_name,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    server_info = data.get("server_info", {})
    # In __init__.py einmalig zentral abgerufen (statt hier erneut vom Gateway zu holen)
    thing_class_cache = data.get("thing_class_cache", {})
    thing_class_action_cache = data.get("thing_class_action_cache", {})
    thing_class_settings_cache = data.get("thing_class_settings_cache", {})
    action_param_cache = data.get("action_param_cache", {})
    settings_param_cache = data.get("settings_param_cache", {})
    pv_configurations = data.get("pv_configurations", [])
    hems_pv_param_cache = data.get("hems_pv_param_cache", {})
    tunnel_proxy_state = data.get("tunnel_proxy_state", {"config": {}})

    switches = []
    if coordinator.data:
        for thing in coordinator.data:
            try:
                st_types = thing_class_cache.get(thing.get("thingClassId"), [])

                for state in thing.get("states", []):
                    # Wir prüfen: Ist es ein Boolean (potenzieller Schalter)
                    if isinstance(state.get("value"), bool):
                        st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)

                        # Nur wirklich schreibbare Booleans als Schalter anlegen.
                        # Nur-lesbare Booleans (z.B. "connected", "reachable") landen
                        # stattdessen als binary_sensor.py, da sie sich nicht schalten lassen.
                        if st_def and st_def.get("writable"):
                            switches.append(NymeaHEMSwitch(coordinator, client, thing, state, st_def, server_info))
            except Exception as e:
                _LOGGER.error(f"Fehler beim Laden der Schalter-Details für {thing.get('name')}: {e}")

    # Generische Aktions-Parameter: boolesche Parameter eigenständiger Aktionen
    # werden automatisch als switch angelegt (siehe number.py für Details zum Prinzip).
    for thing, action_def in iter_standalone_actions(coordinator.data, thing_class_action_cache):
        try:
            param_defs = action_def.get("paramTypes", [])
            bool_params = [p for p in param_defs if classify_param(p) == "bool"]
            immediate = len(param_defs) == 1
            for param_def in bool_params:
                switches.append(
                    NymeaActionSwitch(
                        coordinator, client, thing, action_def, param_def,
                        server_info, action_param_cache, immediate=immediate,
                    )
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Action-Switch-Details für {thing.get('name')}: {e}")

    # Generische Settings-Parameter: boolesche Settings (z.B. "Invertiere
    # Batterie Flussrichtung") werden automatisch als switch angelegt.
    # Immer Staging, siehe number.py (NymeaSettingsNumber) für das Prinzip.
    for thing, settings_def in iter_thing_settings(coordinator.data, thing_class_settings_cache):
        try:
            if classify_param(settings_def) == "bool":
                switches.append(
                    NymeaSettingsSwitch(coordinator, client, thing, settings_def, server_info, settings_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Settings-Switch-Details für {thing.get('name')}: {e}")

    # Hems-API: controllableLocalSystem (Teil der PV-Konfiguration).
    for pv_config in pv_configurations:
        if "controllableLocalSystem" in pv_config:
            pv_thing_id = pv_config.get("pvThingId")
            pv_thing = find_thing_by_id(coordinator.data, pv_thing_id) or {"id": pv_thing_id, "name": t("pv_fallback_name")}
            switches.append(
                NymeaHemsPvBoolSwitch(
                    coordinator, pv_thing, pv_config, "controllableLocalSystem",
                    t("pv_locally_controllable"), server_info, hems_pv_param_cache,
                )
            )

    # Fernverbindung - über Configuration.GetConfigurations/TunnelProxyServer,
    # siehe nymea_client.py. Immer anlegen (auch wenn aktuell keine
    # Konfiguration hinterlegt ist), damit man sie zumindest sieht.
    switches.append(NymeaCloudConnectionSwitch(coordinator, client, tunnel_proxy_state, server_info))

    _LOGGER.debug("consolinno_nymea_hems.switch: %d Switches werden hinzugefügt", len(switches))
    async_add_entities(switches)

class NymeaHEMSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, client, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", t("unknown_thing"))
        self._state_type_id = state.get("stateTypeId")
        
        # Klarnamen-Logik wie bei den Sensoren
        display_name = st_def.get("displayName") if st_def else self._state_type_id
        self._attr_name = f"{self._thing_name} {display_name}"
        self._attr_unique_id = f"nymea_sw_{self._thing_id}_{self._state_type_id}"

        # UUID Bereinigung für via_device (Wichtig: Klammern entfernen!)
        server_uuid = server_info.get("uuid", "").replace("{", "").replace("}", "")

        # Geräte-Zuweisung (identisch zur sensor.py)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._thing_id)},
            "name": self._thing_name,
            "manufacturer": "Consolinno",
            "model": t("hems_device_model"),
        }
        
        # Verknüpfung zur Übersicht als "Parent", falls UUID vorhanden
        if server_uuid:
            self._attr_device_info["via_device"] = (DOMAIN, f"nymea_overview_{server_uuid}")

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        for thing in self.coordinator.data:
            if thing.get("id") == self._thing_id:
                for s in thing.get("states", []):
                    if s.get("stateTypeId") == self._state_type_id:
                        return bool(s.get("value"))
        return False

    async def async_turn_on(self, **kwargs):
        """Schaltet den State auf True."""
        await self._client.set_thing_state(self._thing_id, self._state_type_id, True)
        # Sofortiges Update anfordern
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Schaltet den State auf False."""
        await self._client.set_thing_state(self._thing_id, self._state_type_id, False)
        # Sofortiges Update anfordern
        await self.coordinator.async_request_refresh()


class NymeaActionSwitch(CoordinatorEntity, SwitchEntity):
    """Generische switch-Entity für einen booleschen Parameter einer eigenständigen Aktion.

    Siehe number.py (NymeaActionNumber) für das Prinzip Immediate vs. Staging.
    """

    def __init__(self, coordinator, client, thing, action_def, param_def, server_info,
                 action_param_cache, immediate: bool):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._action_type_id = action_def.get("id")
        self._param_id = param_def.get("id")
        self._action_param_cache = action_param_cache
        self._immediate = immediate

        self._attr_name = action_entity_name(thing, action_def, param_def if len(action_def.get("paramTypes", [])) > 1 else None)
        self._attr_unique_id = f"nymea_actionsw_{self._thing_id}_{self._action_type_id}_{self._param_id}"

        self._default = get_param_default(param_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def is_on(self) -> bool:
        return bool(get_staged_value(
            self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, self._default
        ))

    async def _set_value(self, value: bool):
        set_staged_value(self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, value)
        self.async_write_ha_state()

        if self._immediate:
            try:
                params = get_staged_params(self._action_param_cache, self._thing_id, self._action_type_id)
                await self._client.execute_action(self._thing_id, self._action_type_id, params)
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error(f"Fehler beim Ausführen der Aktion für {self.name}: {e}")

    async def async_turn_on(self, **kwargs):
        await self._set_value(True)

    async def async_turn_off(self, **kwargs):
        await self._set_value(False)


class NymeaSettingsSwitch(CoordinatorEntity, SwitchEntity):
    """Generische switch-Entity für ein boolesches Setting eines Things.

    Immer Staging (nie sofort ausgelöst) - siehe NymeaSettingsNumber in
    number.py für das Prinzip.
    """

    def __init__(self, coordinator, client, thing, settings_def, server_info, settings_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._param_id = settings_def.get("id")
        self._settings_param_cache = settings_param_cache

        self._attr_name = settings_entity_name(thing, settings_def)
        self._attr_unique_id = f"nymea_setsw_{self._thing_id}_{self._param_id}"

        current = get_current_setting_value(thing, self._param_id)
        self._default = current if current is not None else get_param_default(settings_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def is_on(self) -> bool:
        return bool(get_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, self._default))

    async def async_turn_on(self, **kwargs):
        set_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        set_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, False)
        self.async_write_ha_state()


class NymeaHemsPvBoolSwitch(CoordinatorEntity, SwitchEntity):
    """Boolesches Feld der PV-Konfiguration (Hems-API) - immer gestaged, wird
    über 'PV-Einstellungen speichern' (button.py) übertragen."""

    def __init__(self, coordinator, pv_thing, pv_config, field, label, server_info, hems_pv_param_cache):
        super().__init__(coordinator)
        self._pv_thing_id = pv_config.get("pvThingId")
        self._field = field
        self._hems_pv_param_cache = hems_pv_param_cache
        self._default = pv_config.get(field)

        pv_thing_display_name = pv_thing.get("name", t("pv_fallback_name"))
        self._attr_name = f"{pv_thing_display_name} {t('pv_setting_prefix')}: {label}"
        self._attr_unique_id = f"nymea_pvsw_{self._pv_thing_id}_{field}"
        self._attr_device_info = build_device_info(pv_thing, server_info)

    @property
    def is_on(self) -> bool:
        return bool(get_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, self._field, self._default))

    async def async_turn_on(self, **kwargs):
        set_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, self._field, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        set_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, self._field, False)
        self.async_write_ha_state()


class NymeaCloudConnectionSwitch(CoordinatorEntity, SwitchEntity):
    """Fernverbindung überwachen und ein-/ausschalten.

    Läuft über Configuration.SetTunnelProxyServerConfiguration /
    DeleteTunnelProxyServerConfiguration (bestätigt per JSONRPC.Introspect -
    NICHT über "Cloud", das war eine falsche Vermutung). Eine
    TunnelProxyServerConfiguration enthält echte Server-Zugangsdaten
    (address/port/sslEnabled/...) - wir senden beim Wieder-Einschalten GENAU
    DIE zuletzt bekannte, echte Konfiguration erneut, statt Werte zu erfinden.

    BUGFIX: tunnel_proxy_state ist ein MUTABLER Holder (siehe __init__.py),
    der bei JEDEM Coordinator-Refresh live aktualisiert wird. Vorher wurde
    die Konfiguration nur einmalig beim Setup abgerufen, wodurch ein
    Umschalten in der Nymea-App nie in HA ankam, bevor die Integration neu
    geladen wurde. is_on liest jetzt bei jeder Abfrage live aus dem Holder.
    """

    def __init__(self, coordinator, client, tunnel_proxy_state: dict, server_info):
        super().__init__(coordinator)
        self._client = client
        self._tunnel_proxy_state = tunnel_proxy_state
        self._attr_name = t("remote_connection")
        self._attr_unique_id = "nymea_tunnelproxy_connection"
        self._attr_device_info = build_system_device_info(server_info)
        # Für die verzögerte Bestätigungs-Abfrage, siehe _schedule_confirmation().
        self._pending_confirm_task = None

    @property
    def is_on(self) -> bool:
        # Immer live aus dem Holder lesen (wird bei jedem Coordinator-Refresh
        # aktualisiert) - so kommt ein Umschalten in der Nymea-App automatisch
        # beim nächsten Refresh in HA an, ohne Neuladen der Integration.
        return bool(self._tunnel_proxy_state.get("config"))

    @property
    def icon(self):
        return "mdi:cloud-check" if self.is_on else "mdi:cloud-off-outline"

    def _schedule_confirmation(self, delay: float = 5.0):
        """Plant EINMALIG eine verzögerte Nachprüfung beim Gateway ein.

        Grund: Das optimistische Setzen (siehe async_turn_on/async_turn_off)
        zeigt den Zustand sofort ohne Flackern an, kann aber nicht erkennen,
        wenn der Befehl beim Gateway aus irgendeinem Grund NICHT wirklich
        greift (z.B. weil der Tunnel zum Proxy-Server nicht zustande kommt).
        Ohne diese Nachprüfung würde man das erst beim nächsten regulären
        Poll-Intervall bemerken (Standard 60s), falls dafür auch keine Push-
        Benachrichtigung kommt.

        WICHTIG: Der Delay ist bewusst gewählt, um NICHT mit der internen
        Verarbeitung der Nymea-Box zu kollidieren - das war die Ursache des
        ursprünglichen Flacker-Bugs (SOFORTIGES Refresh direkt nach dem
        Set/Delete-Aufruf). Ein Refresh erst nach ein paar Sekunden liest den
        bereits eingeschwungenen, echten Zustand und bestätigt entweder
        unseren optimistischen Wert (keine sichtbare Änderung) oder korrigiert
        ihn zurecht, falls der Vorgang wirklich fehlgeschlagen ist.
        """
        if self._pending_confirm_task and not self._pending_confirm_task.done():
            self._pending_confirm_task.cancel()

        async def _confirm():
            await asyncio.sleep(delay)
            await self.coordinator.async_request_refresh()

        self._pending_confirm_task = self.hass.async_create_task(_confirm())

    async def async_turn_on(self, **kwargs):
        current_config = self._tunnel_proxy_state.get("config")

        if current_config:
            # Bereits an - im Zweifel exakt dieselbe Konfiguration erneut senden.
            target_config = current_config
        else:
            # Verbindung ist aktuell aus. Wir verwenden NICHT mehr "current_config"
            # (das ist hier immer leer), sondern das zuletzt bekannte, ECHTE
            # Template (address/port/sslEnabled/authenticationEnabled/
            # ignoreSslErrors) - bestätigt über mehrere Aktivierungen hinweg als
            # konstant. Nur die id wird - wie von der Nymea-App selbst beobachtet
            # (jede Aktivierung erzeugt eine frische UUID) - hier neu generiert.
            template = self._tunnel_proxy_state.get("last_known_template")
            if not template:
                _LOGGER.error(
                    "Fernverbindung kann nicht über Home Assistant erstmalig aktiviert werden: "
                    "keine bekannte Server-Konfiguration vorhanden. Bitte einmalig in der "
                    "Nymea-App einschalten - danach übernimmt Home Assistant den Zustand "
                    "automatisch und kann ihn dauerhaft (auch wieder ausschalten/einschalten) steuern."
                )
                return

            target_config = dict(template)
            target_config["id"] = "{" + str(uuid.uuid4()) + "}"

        try:
            await self._client.set_tunnel_proxy_server_configuration(target_config)
        except Exception as e:
            _LOGGER.error(f"Fehler beim Aktivieren der Fernverbindung: {e}")
            return

        # Optimistisch sofort lokal übernehmen, statt direkt danach zwanghaft
        # neu vom Gateway zu lesen (async_request_refresh()). GENAU DAS war
        # die Ursache für das kurze "Flackern" (an -> kurz aus -> wieder an):
        # das erzwungene Sofort-Refresh traf die Nymea-Box, während sie die
        # Änderung noch intern verarbeitet hat, und las dabei einen
        # Zwischenzustand. Die eigentliche Bestätigung kommt ohnehin automatisch
        # etwas später über die normale Push-Benachrichtigung
        # (Configuration.TunnelProxyServerConfigurationChanged), die den
        # Coordinator dann ganz regulär aktualisiert (siehe handle_nymea_event
        # in __init__.py) - dort wird bei Bedarf auch korrigiert.
        self._tunnel_proxy_state["config"] = target_config
        self._tunnel_proxy_state["last_known_template"] = dict(target_config)
        self.async_write_ha_state()
        self._schedule_confirmation()

    async def async_turn_off(self, **kwargs):
        current_config = self._tunnel_proxy_state.get("config")
        if not current_config or not current_config.get("id"):
            _LOGGER.error("Fernverbindung kann nicht deaktiviert werden: keine ID bekannt.")
            return
        try:
            await self._client.delete_tunnel_proxy_server_configuration(current_config["id"])
        except Exception as e:
            _LOGGER.error(f"Fehler beim Deaktivieren der Fernverbindung: {e}")
            return

        # Optimistisch sofort auf "aus" setzen - siehe async_turn_on() für die
        # Begründung (kein erzwungenes Sofort-Refresh mehr, das die Ursache
        # des Flackerns war).
        self._tunnel_proxy_state["config"] = {}
        self.async_write_ha_state()
        self._schedule_confirmation()