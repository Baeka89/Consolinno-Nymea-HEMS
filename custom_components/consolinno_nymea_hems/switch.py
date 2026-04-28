import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    server_info = data.get("server_info", {})
    
    switches = []
    if coordinator.data:
        for thing in coordinator.data:
            try:
                # Wir holen die Klassendetails, um die Klarnamen der Schalter zu erfahren
                cls_data = await client.get_thing_class_details(thing.get("thingClassId"))
                st_types = cls_data[0].get("stateTypes", []) if cls_data else []
                
                for state in thing.get("states", []):
                    # Wir prüfen: Ist es ein Boolean (Schalter)
                    if isinstance(state.get("value"), bool):
                        st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)
                        
                        # Schalter hinzufügen
                        switches.append(NymeaHEMSwitch(coordinator, client, thing, state, st_def, server_info))
            except Exception as e:
                _LOGGER.error(f"Fehler beim Laden der Schalter-Details für {thing.get('name')}: {e}")

    async_add_entities(switches)

class NymeaHEMSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, client, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._client = client
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", "Unbekannt")
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
            "model": "HEMS Device",
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