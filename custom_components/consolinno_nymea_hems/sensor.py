import logging
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.const import (
    UnitOfPower, 
    UnitOfEnergy, 
    PERCENTAGE, 
    UnitOfElectricCurrent, 
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfFrequency,
    UnitOfTime
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .nymea_action_helpers import t, thing_name

_LOGGER = logging.getLogger(__name__)

UNIT_MAP = {
    "UnitAmpere": UnitOfElectricCurrent.AMPERE,
    "UnitDegreeCelsius": UnitOfTemperature.CELSIUS,
    "UnitHertz": UnitOfFrequency.HERTZ,
    "UnitHours": UnitOfTime.HOURS,
    "UnitKiloWattHour": UnitOfEnergy.KILO_WATT_HOUR,
    "UnitMinutes": UnitOfTime.MINUTES,
    "UnitPercentage": PERCENTAGE,
    "UnitSeconds": UnitOfTime.SECONDS,
    "UnitVolt": UnitOfElectricPotential.VOLT,
    "UnitWatt": UnitOfPower.WATT,
    "UnitEuroCentPerKiloWattHour": "ct/kWh",
    "UnitLux": "lx",
    "UnitOhm": "Ω",
    "UnitPartsPerMillion": "ppm",
}

async def async_setup_entry(hass, config_entry, async_add_entities):
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    server_info = data.get("server_info", {})
    # In __init__.py einmalig zentral abgerufen (statt hier erneut vom Gateway zu holen)
    thing_class_cache = data.get("thing_class_cache", {})

    sensors = []
    
    # 1. Server-Info Sensor (Landet in der "Nymea Übersicht")
    sensors.append(NymeaServerInfoSensor(coordinator, server_info, config_entry.entry_id))
    
    # 2. Dynamische Sensoren aus den Things
    if coordinator.data:
        for thing in coordinator.data:
            try:
                st_types = thing_class_cache.get(thing.get("thingClassId"), [])

                for state in thing.get("states", []):
                    # Nur nicht-Booleans verarbeiten (Booleans -> switch.py / binary_sensor.py)
                    if isinstance(state.get("value"), bool):
                        continue

                    st_def = next((t for t in st_types if t["id"] == state["stateTypeId"]), None)

                    # Schreibbare numerische States werden von number.py als number-Entity
                    # angelegt (dort steuerbar) - hier NICHT zusätzlich als Sensor, sonst
                    # gäbe es zwei Entities für denselben Wert.
                    if st_def and st_def.get("writable") and isinstance(state.get("value"), (int, float)):
                        continue

                    sensors.append(NymeaHEMStatSensor(coordinator, thing, state, st_def, server_info))
            except Exception as e:
                _LOGGER.error(f"Fehler bei {thing.get('name')}: {e}")

    _LOGGER.debug("consolinno_nymea_hems.sensor: %d Sensoren werden hinzugefügt", len(sensors))
    async_add_entities(sensors)

class NymeaHEMStatSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, thing, state, st_def, server_info):
        super().__init__(coordinator)
        self._thing_id = thing.get("id")
        self._thing_name = thing.get("name", t("unknown_thing"))
        self._state_type_id = state.get("stateTypeId")
        self._st_def = st_def
        
        display_name = st_def.get("displayName") if st_def else self._state_type_id
        self._attr_name = f"{self._thing_name} {display_name}"
        self._attr_unique_id = f"nymea_sensor_{self._thing_id}_{self._state_type_id}"

        nymea_unit = st_def.get("unit") if st_def else None
        self._base_unit = UNIT_MAP.get(nymea_unit)
        self._nymea_unit = nymea_unit

        # GERÄTE-ZUORDNUNG: Immer dem Thing zugeordnet
        server_uuid = server_info.get("uuid", "").replace("{", "").replace("}", "")
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._thing_id)},
            "name": self._thing_name,
            "manufacturer": "Consolinno",
            "model": t("hems_device_model"),
        }
        
        # Optionale Verknüpfung zur Übersicht (via_device)
        if server_uuid:
            self._attr_device_info["via_device"] = (DOMAIN, f"nymea_overview_{server_uuid}")

    def _is_complex(self, val):
        return isinstance(val, (dict, list))

    @property
    def native_unit_of_measurement(self):
        s = self._get_s()
        if s and self._is_complex(s.get("value")): return None
        return self._base_unit

    @property
    def state_class(self):
        s = self._get_s()
        if s and self._is_complex(s.get("value")): return None
        if self._nymea_unit == "UnitKiloWattHour": return SensorStateClass.TOTAL_INCREASING
        if self._nymea_unit in ["UnitWatt", "UnitDegreeCelsius", "UnitVolt", "UnitAmpere", "UnitPercentage"]:
            return SensorStateClass.MEASUREMENT
        return None

    @property
    def device_class(self):
        s = self._get_s()
        if s and self._is_complex(s.get("value")): return None
        if self._nymea_unit == "UnitWatt": return SensorDeviceClass.POWER
        if self._nymea_unit == "UnitKiloWattHour": return SensorDeviceClass.ENERGY
        if self._nymea_unit == "UnitUnixTime": return SensorDeviceClass.TIMESTAMP
        if self._nymea_unit == "UnitAmpere": return SensorDeviceClass.CURRENT
        if self._nymea_unit == "UnitVolt": return SensorDeviceClass.VOLTAGE
        if self._nymea_unit == "UnitDegreeCelsius": return SensorDeviceClass.TEMPERATURE
        return None

    @property
    def native_value(self):
        s = self._get_s()
        if not s: return None
        val = s.get("value")
        if self._is_complex(val): return "Daten in Attributen"
        if val is None: return None
        if self.device_class == SensorDeviceClass.TIMESTAMP:
            try: return dt_util.utc_from_timestamp(float(val))
            except: return val
        try: return round(float(val), 2)
        except (ValueError, TypeError): return val

    @property
    def extra_state_attributes(self):
        s = self._get_s()
        val = s.get("value") if s else None
        if isinstance(val, dict): return val
        return {"full_value": val}

    def _get_s(self):
        if not self.coordinator.data: return None
        for t in self.coordinator.data:
            if t.get("id") == self._thing_id:
                for s in t.get("states", []):
                    if s.get("stateTypeId") == self._state_type_id: return s
        return None

class NymeaServerInfoSensor(CoordinatorEntity, SensorEntity):
    """Sammelpunkt für Informationen ohne konkrete Thing-ID."""
    def __init__(self, coordinator, info, entry_id):
        super().__init__(coordinator)
        self._info = info
        server_uuid = info.get("uuid", "").replace("{", "").replace("}", "")
        self._attr_name = t("system_version_name")
        self._attr_unique_id = f"nymea_info_{server_uuid or entry_id}"
        
        # Dieses Gerät bündelt alles, was sonst "in der Luft hängen" würde
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"nymea_overview_{server_uuid}")},
            "name": t("nymea_overview_device"),
            "manufacturer": "Consolinno",
            "model": t("system_overview_model"),
        }

    @property
    def native_value(self):
        return self._info.get("version")