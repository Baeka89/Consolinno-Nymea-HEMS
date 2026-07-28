"""Binary Sensor Plattform für Consolinno Nymea HEMS.

Bildet nur-lesbare Boolean-States ab (z.B. "connected", "reachable").
Schreibbare Boolean-States (echte Schalter) werden stattdessen in
switch.py als SwitchEntity angelegt.
"""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .nymea_action_helpers import t

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    server_info = data.get("server_info", {})
    # In __init__.py einmalig zentral abgerufen (statt hier erneut vom Gateway zu holen)
    thing_class_cache = data.get("thing_class_cache", {})

    binary_sensors = []
    if coordinator.data:
        for thing in coordinator.data:
            try:
                st_types = thing_class_cache.get(thing.get("thingClassId"), [])

                for state in thing.get("states", []):
                    # Nur Booleans verarbeiten
                    if not isinstance(state.get("value"), bool):
                        continue

                    st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)

                    # Schreibbare Booleans werden als switch.py abgebildet, hier nur
                    # die nicht-schreibbaren (reinen Status-)Werte anlegen.
                    if not (st_def and st_def.get("writable")):
                        binary_sensors.append(
                            NymeaHEMBinarySensor(coordinator, thing, state, st_def, server_info)
                        )
            except Exception as e:
                _LOGGER.error(f"Fehler beim Laden der Binary-Sensor-Details für {thing.get('name')}: {e}")

    _LOGGER.debug("consolinno_nymea_hems.binary_sensor: %d Binary Sensors werden hinzugefügt", len(binary_sensors))
    async_add_entities(binary_sensors)


class NymeaHEMBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", t("unknown_thing"))
        self._state_type_id = state.get("stateTypeId")

        # Klarnamen-Logik wie bei sensor.py / switch.py
        display_name = st_def.get("displayName") if st_def else self._state_type_id
        self._attr_name = f"{self._thing_name} {display_name}"
        self._attr_unique_id = f"nymea_bsens_{self._thing_id}_{self._state_type_id}"

        # UUID Bereinigung für via_device (Klammern entfernen)
        server_uuid = server_info.get("uuid", "").replace("{", "").replace("}", "")

        # Geräte-Zuweisung (identisch zu sensor.py / switch.py)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._thing_id)},
            "name": self._thing_name,
            "manufacturer": "Consolinno",
            "model": t("hems_device_model"),
        }

        if server_uuid:
            self._attr_device_info["via_device"] = (DOMAIN, f"nymea_overview_{server_uuid}")

    @property
    def is_on(self) -> bool:
        s = self._get_s()
        if not s:
            return False
        return bool(s.get("value"))

    def _get_s(self):
        if not self.coordinator.data:
            return None
        for t in self.coordinator.data:
            if t.get("id") == self._thing_id:
                for s in t.get("states", []):
                    if s.get("stateTypeId") == self._state_type_id:
                        return s
        return None