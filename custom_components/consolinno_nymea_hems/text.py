"""Text Plattform für Consolinno Nymea HEMS.

Genereller Fallback für Action-Parameter, deren Typ wir nicht als Zahl,
Boolean oder Auswahlliste erkennen (z.B. freier Text). Sorgt dafür, dass
auch ein unbekannter zukünftiger Parametertyp automatisch eine bedienbare
Entity bekommt, statt stillschweigend ignoriert zu werden.
"""
import logging

from homeassistant.components.text import TextEntity
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
    action_entity_name,
    settings_entity_name,
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

    texts = []
    for thing, action_def in iter_standalone_actions(coordinator.data, thing_class_action_cache):
        try:
            param_defs = action_def.get("paramTypes", [])
            text_params = [p for p in param_defs if classify_param(p) == "text"]
            immediate = len(param_defs) == 1
            for param_def in text_params:
                texts.append(
                    NymeaActionText(
                        coordinator, client, thing, action_def, param_def,
                        server_info, action_param_cache, immediate=immediate,
                    )
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Action-Text-Details für {thing.get('name')}: {e}")

    # Fallback für Settings mit unbekanntem Typ, damit auch dort nichts verloren geht.
    for thing, settings_def in iter_thing_settings(coordinator.data, thing_class_settings_cache):
        try:
            if classify_param(settings_def) == "text":
                texts.append(
                    NymeaSettingsText(coordinator, client, thing, settings_def, server_info, settings_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Settings-Text-Details für {thing.get('name')}: {e}")

    _LOGGER.debug("consolinno_nymea_hems.text: %d Text-Entities werden hinzugefügt", len(texts))
    async_add_entities(texts)


class NymeaActionText(CoordinatorEntity, TextEntity):
    """Generische text-Entity als Fallback für unbekannte Action-Parametertypen."""

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
        self._attr_unique_id = f"nymea_actiontxt_{self._thing_id}_{self._action_type_id}_{self._param_id}"

        self._default = get_param_default(param_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def native_value(self):
        val = get_staged_value(
            self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, self._default
        )
        return str(val) if val is not None else ""

    async def async_set_value(self, value: str) -> None:
        set_staged_value(self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, value)
        self.async_write_ha_state()

        if self._immediate:
            try:
                params = get_staged_params(self._action_param_cache, self._thing_id, self._action_type_id)
                await self._client.execute_action(self._thing_id, self._action_type_id, params)
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error(f"Fehler beim Ausführen der Aktion für {self.name}: {e}")


class NymeaSettingsText(CoordinatorEntity, TextEntity):
    """Fallback text-Entity für Settings mit unbekanntem Typ. Immer Staging."""

    def __init__(self, coordinator, client, thing, settings_def, server_info, settings_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._param_id = settings_def.get("id")
        self._settings_param_cache = settings_param_cache

        self._attr_name = settings_entity_name(thing, settings_def)
        self._attr_unique_id = f"nymea_settxt_{self._thing_id}_{self._param_id}"

        current = get_current_setting_value(thing, self._param_id)
        self._default = current if current is not None else get_param_default(settings_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def native_value(self):
        val = get_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, self._default)
        return str(val) if val is not None else ""

    async def async_set_value(self, value: str) -> None:
        set_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, value)
        self.async_write_ha_state()