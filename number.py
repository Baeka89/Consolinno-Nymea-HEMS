import logging
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

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
                # Klassendetails für Klarnamen abrufen
                cls_data = await client.get_thing_class_details(thing.get("thingClassId"))
                st_types = cls_data[0].get("stateTypes", []) if cls_data else []
                
                for state in thing.get("states", []):
                    st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)
                    
                    # Wir erstellen ein Number-Feld wenn:
                    # 1. Der Wert eine Zahl ist (int/float)
                    # 2. Der Wert als 'writable' markiert ist
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
        
        # Klarnamen-Logik
        display_name = st_def.get("displayName") if st_def else self._state_type_id
        self._attr_name = f"{self._thing_name} {display_name}"
        self._attr_unique_id = f"nymea_num_{self._thing_id}_{self._state_type_id}"

        # Werteeinstellungen (Min/Max/Schrittweite)
        # Nymea liefert oft keine festen Grenzen, daher setzen wir großzügige Defaults
        # falls die API keine mitliefert.
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100000 
        self._attr_native_step = 1.0

        # Geräte-Zuweisung (wie bei Sensoren und Switches)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._thing_id)},
            "name": self._thing_name,
            "manufacturer": "Consolinno",
            "model": "Nymea HEMS Device",
            "via_device": (DOMAIN, server_info.get("uuid")),
        }

    @property
    def native_value(self) -> float:
        if not self.coordinator.data:
            return None
        for thing in self.coordinator.data:
            if thing.get("id") == self._thing_id:
                for s in thing.get("states", []):
                    if s.get("stateTypeId") == self._state_type_id:
                        val = s.get("value")
                        return float(val) if val is not None else None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Ändert den Wert auf dem Nymea-Server."""
        # Wir senden den Wert als float oder int zurück an die API
        await self._client.set_thing_state(self._thing_id, self._state_type_id, value)
        # Sofortiges Update erzwingen
        await self.coordinator.async_request_refresh()