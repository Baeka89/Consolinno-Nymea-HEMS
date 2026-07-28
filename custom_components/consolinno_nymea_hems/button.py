"""Button Plattform für Consolinno Nymea HEMS.

Zwei Fälle, komplett generisch aus den ActionType-Definitionen erzeugt:
- Aktion ganz ohne Parameter: Knopf löst die Aktion direkt aus.
- Aktion mit 2+ Parametern: die einzelnen Parameter werden über number/switch/
  select/text (Staging, siehe nymea_action_helpers.py) gemerkt; dieser Knopf
  sendet sie gesammelt als eine Aktion - genau wie der "Speichern"/"OK" Button
  in der Nymea-App.
"""
import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .nymea_action_helpers import (
    iter_standalone_actions,
    get_staged_params,
    get_staged_settings,
    build_device_info,
    build_system_device_info,
    action_entity_name,
    action_button_name,
    get_staged_pv_config,
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
    thing_class_action_cache = data.get("thing_class_action_cache", {})
    thing_class_settings_cache = data.get("thing_class_settings_cache", {})
    action_param_cache = data.get("action_param_cache", {})
    settings_param_cache = data.get("settings_param_cache", {})
    pv_configurations = data.get("pv_configurations", [])
    hems_pv_param_cache = data.get("hems_pv_param_cache", {})

    buttons = []
    for thing, action_def in iter_standalone_actions(coordinator.data, thing_class_action_cache):
        try:
            param_count = len(action_def.get("paramTypes", []))
            # Genau 1 Parameter wird direkt von number/switch/select/text
            # ausgelöst (siehe "immediate"-Logik dort) - dafür braucht es
            # keinen zusätzlichen Knopf.
            if param_count != 1:
                buttons.append(
                    NymeaActionButton(coordinator, client, thing, action_def, server_info, action_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Action-Button-Details für {thing.get('name')}: {e}")

    # Ein "Einstellungen speichern"-Button PRO THING (nicht pro Setting), da
    # Settings thing-weit sind - genau wie der "ANWENDEN"/"SPEICHERN"-Button
    # in der Nymea-App, der alle Settings eines Things zusammen sendet.
    for thing in coordinator.data or []:
        try:
            settings_defs = thing_class_settings_cache.get(thing.get("thingClassId"), [])
            if settings_defs:
                buttons.append(
                    NymeaSettingsButton(coordinator, client, thing, server_info, settings_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Settings-Button-Details für {thing.get('name')}: {e}")

    # Ein "PV-Einstellungen speichern"-Button pro PV-Konfiguration (Hems-API).
    for pv_config in pv_configurations:
        pv_thing_id = pv_config.get("pvThingId")
        pv_thing = find_thing_by_id(coordinator.data, pv_thing_id) or {"id": pv_thing_id, "name": t("pv_fallback_name")}
        buttons.append(
            NymeaHemsPvButton(coordinator, client, pv_thing, pv_config, server_info, hems_pv_param_cache)
        )

    # System-Buttons (Configurations-API, siehe nymea_client.py) - system-weit,
    # nicht an ein Thing gebunden, daher am virtuellen "Consolinno HEMS System"-
    # Gerät. Methodennamen sind vermutet - siehe introspect()-Diagnose in
    # __init__.py, die das beim nächsten Test bestätigt/korrigiert.
    buttons.append(NymeaSystemActionButton(coordinator, client, "restart_nymea_service", t("restart_nymea_service"), server_info))
    buttons.append(NymeaSystemActionButton(coordinator, client, "restart_system", t("restart_system"), server_info))
    buttons.append(NymeaSystemActionButton(coordinator, client, "shutdown_system", t("shutdown_system"), server_info))

    _LOGGER.debug("consolinno_nymea_hems.button: %d Buttons werden hinzugefügt", len(buttons))
    async_add_entities(buttons)


class NymeaActionButton(CoordinatorEntity, ButtonEntity):
    """Löst eine eigenständige Aktion aus - ohne Parameter direkt, mit mehreren
    Parametern gesammelt aus den zugehörigen Staging-Entities."""

    def __init__(self, coordinator, client, thing, action_def, server_info, action_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._action_type_id = action_def.get("id")
        self._action_param_cache = action_param_cache

        self._attr_name = action_button_name(thing, action_def)
        self._attr_unique_id = f"nymea_actionbtn_{self._thing_id}_{self._action_type_id}"
        self._attr_device_info = build_device_info(thing, server_info)

    async def async_press(self) -> None:
        try:
            params = get_staged_params(self._action_param_cache, self._thing_id, self._action_type_id)
            await self._client.execute_action(self._thing_id, self._action_type_id, params)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Ausführen der Aktion für {self.name}: {e}")


class NymeaSettingsButton(CoordinatorEntity, ButtonEntity):
    """Sendet alle gestagten Settings eines Things gesammelt an
    Integrations.SetThingSettings - entspricht dem "SPEICHERN"/"ANWENDEN"
    Button in der Nymea-App (z.B. Batteriekapazität + Invertiere Flussrichtung
    zusammen, oder alle 5 PV-Einstellungen zusammen)."""

    def __init__(self, coordinator, client, thing, server_info, settings_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._settings_param_cache = settings_param_cache

        settings_thing_name = thing.get("name", t("unknown_thing"))
        self._attr_name = f"{settings_thing_name} {t('save_settings')}"
        self._attr_unique_id = f"nymea_setbtn_{self._thing_id}"
        self._attr_device_info = build_device_info(thing, server_info)

    async def async_press(self) -> None:
        try:
            settings = get_staged_settings(self._settings_param_cache, self._thing_id)
            await self._client.set_thing_settings(self._thing_id, settings)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Speichern der Einstellungen für {self.name}: {e}")


class NymeaHemsPvButton(CoordinatorEntity, ButtonEntity):
    """Sendet die komplette PV-Konfiguration (Hems-API) auf einmal.

    WICHTIG: Hems.SetPvConfiguration erwartet das VOLLSTÄNDIGE Objekt, nicht
    nur die geänderten Felder. Wir nehmen daher die zuletzt vom Gateway
    bekannte Konfiguration als Basis und überschreiben nur die Felder, die der
    Nutzer über die number/select/switch-Entities tatsächlich geändert hat.
    """

    def __init__(self, coordinator, client, pv_thing, pv_config, server_info, hems_pv_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._pv_thing_id = pv_config.get("pvThingId")
        self._original_config = dict(pv_config)
        self._hems_pv_param_cache = hems_pv_param_cache

        pv_thing_display_name = pv_thing.get("name", t("pv_fallback_name"))
        self._attr_name = f"{pv_thing_display_name} {t('save_pv_settings')}"
        self._attr_unique_id = f"nymea_pvbtn_{self._pv_thing_id}"
        self._attr_device_info = build_device_info(pv_thing, server_info)

    async def async_press(self) -> None:
        try:
            merged_config = dict(self._original_config)
            staged = get_staged_pv_config(self._hems_pv_param_cache, self._pv_thing_id)
            merged_config.update(staged)
            await self._client.set_pv_configuration(merged_config)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Speichern der PV-Einstellungen für {self.name}: {e}")


class NymeaSystemActionButton(CoordinatorEntity, ButtonEntity):
    """System-weite Aktion ohne Parameter (Reboot/Restart/Shutdown), über die
    Configurations-API. Nicht an ein Thing gebunden, daher am virtuellen
    "Consolinno HEMS System"-Gerät."""

    _ACTIONS = {
        "restart_nymea_service": "restart_nymea_service",
        "restart_system": "initiate_reboot",
        "shutdown_system": "initiate_shutdown",
    }

    def __init__(self, coordinator, client, action_key: str, name: str, server_info):
        super().__init__(coordinator)
        self._client = client
        self._action_key = action_key
        self._attr_name = name
        self._attr_unique_id = f"nymea_sysaction_{action_key}"
        self._attr_device_info = build_system_device_info(server_info)
        if action_key in ("restart_nymea_service", "restart_system"):
            self._attr_device_class = ButtonDeviceClass.RESTART
        else:
            self._attr_icon = "mdi:power"

    async def async_press(self) -> None:
        method_name = self._ACTIONS.get(self._action_key)
        client_method = getattr(self._client, method_name, None)
        if client_method is None:
            _LOGGER.error(f"Unbekannte Systemaktion: {self._action_key}")
            return
        try:
            await client_method()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Ausführen der Systemaktion '{self.name}': {e}")