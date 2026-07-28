"""Select Plattform für Consolinno Nymea HEMS.

Bildet Parameter von eigenständigen Nymea-Aktionen ab, die eine feste Liste
erlaubter Werte (allowedValues) haben - z.B. eine Dropdown-Auswahl wie
"Ausrichtung". Wird komplett generisch aus den ActionType-Definitionen
erzeugt, siehe number.py für das Immediate-vs-Staging-Prinzip.
"""
import logging

from homeassistant.components.select import SelectEntity
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
    get_staged_pv_value,
    set_staged_pv_value,
    find_thing_by_id,
    t,
    thing_name,
)

_LOGGER = logging.getLogger(__name__)

# Feste, universelle Himmelsrichtungs-Zuordnung (Grad in 45°-Schritten) für die
# PV-Ausrichtung - anders als bei Nymea-eigenen allowedValues ist das hier kein
# vom Hersteller änderbarer Wert, sondern eine stabile geografische Konvention.
# WICHTIG: als Funktion (nicht als Modul-Konstante), damit sie IMMER die
# aktuell eingestellte Sprache nutzt - eine Konstante würde beim Modul-Import
# eingefroren, bevor set_integration_language() überhaupt gelaufen ist.
_PV_ALIGNMENT_DEGREES = [0, 45, 90, 135, 180, 225, 270, 315]
_PV_ALIGNMENT_KEYS = [
    "north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest",
]


def pv_alignment_options() -> dict:
    """Grad -> übersetzter Himmelsrichtungs-Name, in der aktuellen Sprache."""
    return {deg: t(key) for deg, key in zip(_PV_ALIGNMENT_DEGREES, _PV_ALIGNMENT_KEYS)}


def pv_alignment_name_to_degrees() -> dict:
    """Übersetzter Himmelsrichtungs-Name -> Grad, in der aktuellen Sprache."""
    return {v: k for k, v in pv_alignment_options().items()}


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

    selects = []
    for thing, action_def in iter_standalone_actions(coordinator.data, thing_class_action_cache):
        try:
            param_defs = action_def.get("paramTypes", [])
            select_params = [p for p in param_defs if classify_param(p) == "select"]
            immediate = len(param_defs) == 1
            for param_def in select_params:
                selects.append(
                    NymeaActionSelect(
                        coordinator, client, thing, action_def, param_def,
                        server_info, action_param_cache, immediate=immediate,
                    )
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Action-Select-Details für {thing.get('name')}: {e}")

    # Generische Settings-Parameter mit fester Werteliste (z.B. "Ausrichtung").
    for thing, settings_def in iter_thing_settings(coordinator.data, thing_class_settings_cache):
        try:
            if classify_param(settings_def) == "select":
                selects.append(
                    NymeaSettingsSelect(coordinator, client, thing, settings_def, server_info, settings_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Settings-Select-Details für {thing.get('name')}: {e}")

    # Hems-API: PV-Ausrichtung (alignment, in Grad) als Himmelsrichtungs-Dropdown.
    for pv_config in pv_configurations:
        if "alignment" in pv_config:
            pv_thing_id = pv_config.get("pvThingId")
            pv_thing = find_thing_by_id(coordinator.data, pv_thing_id) or {"id": pv_thing_id, "name": t("pv_fallback_name")}
            selects.append(
                NymeaHemsPvAlignmentSelect(coordinator, pv_thing, pv_config, server_info, hems_pv_param_cache)
            )

    _LOGGER.debug("consolinno_nymea_hems.select: %d Selects werden hinzugefügt", len(selects))
    async_add_entities(selects)


class NymeaActionSelect(CoordinatorEntity, SelectEntity):
    """Generische select-Entity für einen Enum-Parameter einer eigenständigen Aktion."""

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
        self._attr_unique_id = f"nymea_actionsel_{self._thing_id}_{self._action_type_id}_{self._param_id}"

        allowed = param_def.get("allowedValues") or []
        self._attr_options = [str(v) for v in allowed]
        # Mapping zurück auf den ursprünglichen Werttyp (z.B. int/bool), falls
        # allowedValues keine Strings sind - Nymea soll den Originaltyp bekommen,
        # nicht zwangsläufig einen String.
        self._value_map = {str(v): v for v in allowed}

        self._default = get_param_default(param_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def current_option(self):
        val = get_staged_value(
            self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, self._default
        )
        return str(val) if val is not None else None

    async def async_select_option(self, option: str) -> None:
        real_value = self._value_map.get(option, option)
        set_staged_value(self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, real_value)
        self.async_write_ha_state()

        if self._immediate:
            try:
                params = get_staged_params(self._action_param_cache, self._thing_id, self._action_type_id)
                await self._client.execute_action(self._thing_id, self._action_type_id, params)
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error(f"Fehler beim Ausführen der Aktion für {self.name}: {e}")


class NymeaSettingsSelect(CoordinatorEntity, SelectEntity):
    """Generische select-Entity für ein Setting mit fester Werteliste
    (z.B. PV-Ausrichtung). Immer Staging, siehe number.py."""

    def __init__(self, coordinator, client, thing, settings_def, server_info, settings_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._param_id = settings_def.get("id")
        self._settings_param_cache = settings_param_cache

        self._attr_name = settings_entity_name(thing, settings_def)
        self._attr_unique_id = f"nymea_setsel_{self._thing_id}_{self._param_id}"

        allowed = settings_def.get("allowedValues") or []
        self._attr_options = [str(v) for v in allowed]
        self._value_map = {str(v): v for v in allowed}

        current = get_current_setting_value(thing, self._param_id)
        self._default = current if current is not None else get_param_default(settings_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def current_option(self):
        val = get_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, self._default)
        return str(val) if val is not None else None

    async def async_select_option(self, option: str) -> None:
        real_value = self._value_map.get(option, option)
        set_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, real_value)
        self.async_write_ha_state()


class NymeaHemsPvAlignmentSelect(CoordinatorEntity, SelectEntity):
    """PV-Ausrichtung (alignment, Grad) als Himmelsrichtungs-Dropdown -
    immer gestaged, wird über 'PV-Einstellungen speichern' (button.py)
    übertragen."""

    def __init__(self, coordinator, pv_thing, pv_config, server_info, hems_pv_param_cache):
        super().__init__(coordinator)
        self._pv_thing_id = pv_config.get("pvThingId")
        self._hems_pv_param_cache = hems_pv_param_cache
        self._default = pv_config.get("alignment")

        pv_thing_display_name = pv_thing.get("name", t("pv_fallback_name"))
        self._attr_name = f"{pv_thing_display_name} {t('pv_setting_prefix')}: {t('alignment')}"
        self._attr_unique_id = f"nymea_pvsel_{self._pv_thing_id}_alignment"
        self._attr_options = list(pv_alignment_options().values())
        self._attr_device_info = build_device_info(pv_thing, server_info)

    @property
    def current_option(self):
        degrees = get_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, "alignment", self._default)
        return pv_alignment_options().get(degrees)

    async def async_select_option(self, option: str) -> None:
        degrees = pv_alignment_name_to_degrees().get(option)
        set_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, "alignment", degrees)
        self.async_write_ha_state()