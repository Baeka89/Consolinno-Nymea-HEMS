import logging
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .sensor import UNIT_MAP  # Wir importieren die Map direkt aus der sensor.py

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    server_info = data.get("server_info", {})
    
    numbers = []
    if coordinator.data:
        for thing in coordinator.data:
            try:
                cls_data = await client.get_thing_class_details(thing.get("thingClassId"))
                st_types = cls_data[0].get("stateTypes", []) if cls_data else []
                
                for state in thing.get("states", []):
                    st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)
                    
                    # Validierung: Nur schreibbare Zahlenwerte
                    if st_def and st_def.get("writable") and isinstance(state.get("value"), (int, float)):
                        numbers.append(NymeaHEMNumber(coordinator, client, thing, state, st_def, server_info))
            except Exception as e:
                _LOGGER.error(f"Fehler beim Laden der Number-Details für {thing.get('name')}: {e}")

    async_add_entities(numbers)

class NymeaHEMNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator, client, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", "Unbekannt")
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
            "model": "HEMS Device",
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