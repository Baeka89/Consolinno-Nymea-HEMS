import logging
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .sensor import UNIT_MAP  # Wir importieren die Map direkt aus der sensor.py
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
    get_staged_settings,
    build_device_info,
    action_entity_name,
    settings_entity_name,
    get_staged_pv_value,
    set_staged_pv_value,
    find_thing_by_id,
    build_system_device_info,
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
    household_phase_limit = data.get("household_phase_limit")
    hems_pv_param_cache = data.get("hems_pv_param_cache", {})

    numbers = []
    if coordinator.data:
        for thing in coordinator.data:
            try:
                st_types = thing_class_cache.get(thing.get("thingClassId"), [])

                for state in thing.get("states", []):
                    st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)
                    
                    # Validierung: Nur schreibbare Zahlenwerte
                    if st_def and st_def.get("writable") and isinstance(state.get("value"), (int, float)):
                        numbers.append(NymeaHEMNumber(coordinator, client, thing, state, st_def, server_info))
            except Exception as e:
                _LOGGER.error(f"Fehler beim Laden der Number-Details für {thing.get('name')}: {e}")

    # Generische Aktions-Parameter: numerische Parameter eigenständiger Aktionen
    # (kein Zustands-Zwilling, siehe __init__.py) werden automatisch als number
    # angelegt - unabhängig davon, wie die Aktion heißt oder wie viele Parameter
    # sie hat. Bei genau einem Parameter wird die Aktion sofort bei Änderung
    # ausgelöst, bei mehreren Parametern wird der Wert nur gemerkt (Staging) und
    # über eine zugehörige Button-Entity (button.py) gemeinsam ausgelöst.
    for thing, action_def in iter_standalone_actions(coordinator.data, thing_class_action_cache):
        try:
            param_defs = action_def.get("paramTypes", [])
            numeric_params = [p for p in param_defs if classify_param(p) == "number"]
            immediate = len(param_defs) == 1
            for param_def in numeric_params:
                numbers.append(
                    NymeaActionNumber(
                        coordinator, client, thing, action_def, param_def,
                        server_info, action_param_cache, immediate=immediate,
                    )
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Action-Number-Details für {thing.get('name')}: {e}")

    # Generische Settings-Parameter: numerische Settings (siehe __init__.py,
    # thing_class_settings_cache) werden automatisch als number angelegt.
    # Settings sind IMMER Staging (nie sofort ausgelöst), analog zur Nymea-App,
    # die pro Thing einen gemeinsamen "Speichern"-Button für alle Settings zeigt.
    for thing, settings_def in iter_thing_settings(coordinator.data, thing_class_settings_cache):
        try:
            if classify_param(settings_def) == "number":
                numbers.append(
                    NymeaSettingsNumber(coordinator, client, thing, settings_def, server_info, settings_param_cache)
                )
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Settings-Number-Details für {thing.get('name')}: {e}")

    # Hems-API: PV-Konfiguration (Breitengrad, Längengrad, Dachneigung,
    # Spitzenleistung) - immer gestaged, siehe NymeaHemsPvNumber unten.
    # Ausrichtung (alignment) läuft als select.py, controllableLocalSystem
    # als switch.py.
    pv_numeric_fields = [
        ("latitude", t("latitude"), "°", 0.01),
        ("longitude", t("longitude"), "°", 0.01),
        ("roofPitch", t("roof_pitch"), "°", 1),
        ("kwPeak", t("peak_power"), "kW", 0.01),
    ]
    for pv_config in pv_configurations:
        pv_thing_id = pv_config.get("pvThingId")
        pv_thing = find_thing_by_id(coordinator.data, pv_thing_id) or {"id": pv_thing_id, "name": t("pv_fallback_name")}
        for field, label, unit, step in pv_numeric_fields:
            if field in pv_config:
                numbers.append(
                    NymeaHemsPvNumber(
                        coordinator, pv_thing, pv_config, field, label, unit, step,
                        server_info, hems_pv_param_cache,
                    )
                )

    # Hems-API: Überlastschutz (Haushalts-Phasenlimit) - system-weiter Wert,
    # nicht an ein einzelnes Thing gebunden, daher sofortiges Setzen (nur 1
    # Wert, kein Sinn in einem Staging+Button-Umweg).
    if household_phase_limit is not None:
        numbers.append(
            NymeaHemsPhaseLimitNumber(coordinator, client, household_phase_limit, server_info)
        )

    _LOGGER.debug("consolinno_nymea_hems.number: %d Numbers werden hinzugefügt", len(numbers))
    async_add_entities(numbers)

class NymeaHEMNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator, client, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", t("unknown_thing"))
        self._state_type_id = state.get("stateTypeId")
        self._st_def = st_def
        
        display_name = st_def.get("displayName") if st_def else self._state_type_id
        self._attr_name = f"{self._thing_name} {display_name}"
        self._attr_unique_id = f"nymea_num_{self._thing_id}_{self._state_type_id}"

        # Einheit aus der Sensor-Map holen
        nymea_unit = st_def.get("unit") if st_def else None
        self._attr_native_unit_of_measurement = UNIT_MAP.get(nymea_unit)

        # Werteeinstellungen (Min/Max/Schrittweite)
        # Falls Nymea Min/Max Werte liefert, hier extrahieren:
        self._attr_native_min_value = st_def.get("minValue", 0)
        self._attr_native_max_value = st_def.get("maxValue", 100000)
        self._attr_native_step = 1.0

        # Geräte-Zuordnung (Synchron zur sensor.py)
        server_uuid = server_info.get("uuid", "").replace("{", "").replace("}", "")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._thing_id)},
            "name": self._thing_name,
            "manufacturer": "Consolinno",
            "model": t("hems_device_model"),
        }
        
        if server_uuid:
            self._attr_device_info["via_device"] = (DOMAIN, f"nymea_overview_{server_uuid}")

    def _get_s(self):
        """Sucht den aktuellen State aus dem Coordinator-Daten-Snapshot."""
        if not self.coordinator.data: return None
        for t in self.coordinator.data:
            if t.get("id") == self._thing_id:
                for s in t.get("states", []):
                    if s.get("stateTypeId") == self._state_type_id: return s
        return None

    @property
    def native_value(self) -> float:
        s = self._get_s()
        if not s: return None
        val = s.get("value")
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Ändert den Wert auf dem Nymea-Server."""
        # Nymea erwartet oft Ganzzahlen, wenn es sich um IDs oder Indizes handelt
        # Hier wird geprüft, ob es ein glatter Float ist, dann senden wir int
        send_val = int(value) if value.is_integer() else value
        
        try:
            await self._client.set_thing_state(self._thing_id, self._state_type_id, send_val)
            # Lokalen State im Coordinator sofort "optimistisch" updaten (optional)
            # Das sorgt für ein flüssigeres UI-Gefühl
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Setzen des Werts für {self.name}: {e}")


class NymeaActionNumber(CoordinatorEntity, NumberEntity):
    """Generische number-Entity für einen numerischen Parameter einer eigenständigen Aktion.

    - Bei genau einem Parameter (immediate=True): Wert ändern löst die Aktion sofort aus.
    - Bei mehreren Parametern (immediate=False): Wert wird nur gemerkt (Staging),
      bis die zugehörige Button-Entity (button.py) alle Parameter gemeinsam sendet.
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
        self._attr_unique_id = f"nymea_actionnum_{self._thing_id}_{self._action_type_id}_{self._param_id}"

        nymea_unit = param_def.get("unit")
        self._attr_native_unit_of_measurement = UNIT_MAP.get(nymea_unit)
        self._attr_native_min_value = param_def.get("minValue", 0)
        self._attr_native_max_value = param_def.get("maxValue", 100000)
        self._attr_native_step = 1.0

        self._default = get_param_default(param_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def native_value(self):
        val = get_staged_value(
            self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, self._default
        )
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        send_val = int(value) if float(value).is_integer() else value
        set_staged_value(self._action_param_cache, self._thing_id, self._action_type_id, self._param_id, send_val)
        self.async_write_ha_state()

        if self._immediate:
            try:
                params = get_staged_params(self._action_param_cache, self._thing_id, self._action_type_id)
                await self._client.execute_action(self._thing_id, self._action_type_id, params)
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.error(f"Fehler beim Ausführen der Aktion für {self.name}: {e}")


class NymeaSettingsNumber(CoordinatorEntity, NumberEntity):
    """Generische number-Entity für ein numerisches Setting eines Things.

    Settings werden IMMER gestaged (nie sofort gesendet) - Änderungen wirken
    erst, wenn die zugehörige "Einstellungen speichern"-Button-Entity gedrückt
    wird. Das entspricht dem "ANWENDEN"/"SPEICHERN"-Button der Nymea-App.
    """

    def __init__(self, coordinator, client, thing, settings_def, server_info, settings_param_cache):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._param_id = settings_def.get("id")
        self._settings_param_cache = settings_param_cache

        self._attr_name = settings_entity_name(thing, settings_def)
        self._attr_unique_id = f"nymea_setnum_{self._thing_id}_{self._param_id}"

        nymea_unit = settings_def.get("unit")
        self._attr_native_unit_of_measurement = UNIT_MAP.get(nymea_unit)
        self._attr_native_min_value = settings_def.get("minValue", 0)
        self._attr_native_max_value = settings_def.get("maxValue", 100000)
        self._attr_native_step = 1.0

        # Startwert: aktuell auf dem Gateway gespeicherter Wert, sonst Default
        # aus der ParamType-Definition.
        current = get_current_setting_value(thing, self._param_id)
        self._default = current if current is not None else get_param_default(settings_def)
        self._attr_device_info = build_device_info(thing, server_info)

    @property
    def native_value(self):
        val = get_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, self._default)
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        send_val = int(value) if float(value).is_integer() else value
        set_staged_setting(self._settings_param_cache, self._thing_id, self._param_id, send_val)
        self.async_write_ha_state()


class NymeaHemsPvNumber(CoordinatorEntity, NumberEntity):
    """Ein Feld der PV-Konfiguration (Hems-API) - immer gestaged, wird erst
    beim Drücken von 'PV-Einstellungen speichern' (button.py) übertragen."""

    def __init__(self, coordinator, pv_thing, pv_config, field, label, unit, step,
                 server_info, hems_pv_param_cache):
        super().__init__(coordinator)
        self._pv_thing_id = pv_config.get("pvThingId")
        self._field = field
        self._hems_pv_param_cache = hems_pv_param_cache
        self._default = pv_config.get(field)

        pv_thing_display_name = pv_thing.get("name", t("pv_fallback_name"))
        self._attr_name = f"{pv_thing_display_name} {t('pv_setting_prefix')}: {label}"
        self._attr_unique_id = f"nymea_pvnum_{self._pv_thing_id}_{field}"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_step = step
        if field == "roofPitch":
            self._attr_native_min_value = 0
            self._attr_native_max_value = 90
        elif field == "latitude":
            self._attr_native_min_value = -90
            self._attr_native_max_value = 90
        elif field == "longitude":
            self._attr_native_min_value = -180
            self._attr_native_max_value = 180
        else:
            self._attr_native_min_value = 0
            self._attr_native_max_value = 100000
        self._attr_device_info = build_device_info(pv_thing, server_info)

    @property
    def native_value(self):
        val = get_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, self._field, self._default)
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        set_staged_pv_value(self._hems_pv_param_cache, self._pv_thing_id, self._field, value)
        self.async_write_ha_state()


class NymeaHemsPhaseLimitNumber(CoordinatorEntity, NumberEntity):
    """Haushalts-Phasenlimit (Überlastschutz) - system-weiter Hems-Wert, wird
    sofort beim Ändern übertragen (nur 1 Wert, kein Staging nötig)."""

    def __init__(self, coordinator, client, current_value, server_info):
        super().__init__(coordinator)
        self._client = client
        self._attr_name = t("overload_protection")
        self._attr_unique_id = "nymea_hems_phaselimit"
        self._attr_native_unit_of_measurement = "A"
        self._attr_native_min_value = 16
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_value = current_value
        self._attr_device_info = build_system_device_info(server_info)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._client.set_household_phase_limit(int(value))
            self._attr_native_value = value
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"Fehler beim Setzen des Überlastschutz-Limits: {e}")