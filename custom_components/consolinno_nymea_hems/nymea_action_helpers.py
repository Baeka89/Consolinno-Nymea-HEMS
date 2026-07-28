"""Gemeinsame Hilfsfunktionen für die generische Nymea-Action-Unterstützung.

Alle Plattformen (number, switch, select, text, button), die Entities aus
Nymea-ActionTypes erzeugen, nutzen diese Funktionen, damit die Logik nur
EINMAL existiert und nicht in jeder Datei separat gepflegt werden muss.
"""
from typing import Any, Dict, Iterable, Iterator, List, Tuple

from .const import DOMAIN


# ----------------------------------------------------------------------
# i18n für UNSERE EIGENEN Textbausteine (nicht die von Nymea gelieferten
# States/Actions/Settings-Namen - die übersetzt Nymea selbst über die
# "locale" beim JSONRPC.Hello-Handshake, siehe nymea_client.py).
# Alles, was WIR selbst an Text hinzufügen (z.B. "Einstellung:",
# "ausführen", "Einstellungen speichern", Himmelsrichtungen), hängt an
# derselben HA-Systemsprache, damit am Ende ein durchgängiges Ergebnis
# entsteht statt eines Sprachmix' aus Nymea-Deutsch + unserem Englisch
# (oder umgekehrt).
# ----------------------------------------------------------------------

_OWN_STRINGS: Dict[str, Dict[str, str]] = {
    "de": {
        "unknown_thing": "Unbekannt",
        "setting_prefix": "Einstellung",
        "save_settings": "Einstellungen speichern",
        "execute_suffix": "ausführen",
        "pv_setting_prefix": "PV-Einstellung",
        "save_pv_settings": "PV-Einstellungen speichern",
        "pv_fallback_name": "PV-Anlage",
        "pv_locally_controllable": "PV-Anlage lokal steuerbar",
        "overload_protection": "Überlastschutz (Haushalts-Phasenlimit)",
        "hems_system_device": "Consolinno HEMS System",
        "hems_optimizer_model": "HEMS Optimizer",
        "nymea_overview_device": "Nymea Übersicht",
        "system_version_name": "Nymea System Version",
        "latitude": "Breitengrad",
        "longitude": "Längengrad",
        "roof_pitch": "Dachneigung",
        "peak_power": "Spitzenleistung",
        "alignment": "Ausrichtung",
        "north": "Norden", "northeast": "Nordosten", "east": "Osten", "southeast": "Südosten",
        "south": "Süden", "southwest": "Südwesten", "west": "Westen", "northwest": "Nordwesten",
        "hems_device_model": "HEMS-Gerät",
        "system_overview_model": "System-Übersicht",
        "remote_connection": "Fernverbindung",
        "restart_nymea_service": "Nymea-Dienst neu starten",
        "restart_system": "System neu starten",
        "shutdown_system": "System herunterfahren",
    },
    "en": {
        "unknown_thing": "Unknown",
        "setting_prefix": "Setting",
        "save_settings": "Save settings",
        "execute_suffix": "execute",
        "pv_setting_prefix": "PV setting",
        "save_pv_settings": "Save PV settings",
        "pv_fallback_name": "PV system",
        "pv_locally_controllable": "PV system locally controllable",
        "overload_protection": "Overload protection (household phase limit)",
        "hems_system_device": "Consolinno HEMS System",
        "hems_optimizer_model": "HEMS Optimizer",
        "nymea_overview_device": "Nymea Overview",
        "system_version_name": "Nymea System Version",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "roof_pitch": "Roof pitch",
        "peak_power": "Peak power",
        "alignment": "Orientation",
        "north": "North", "northeast": "Northeast", "east": "East", "southeast": "Southeast",
        "south": "South", "southwest": "Southwest", "west": "West", "northwest": "Northwest",
        "hems_device_model": "HEMS Device",
        "system_overview_model": "System Overview",
        "remote_connection": "Remote connection",
        "restart_nymea_service": "Restart nymea service",
        "restart_system": "Restart system",
        "shutdown_system": "Shutdown system",
    },
}

# Wird einmal beim Laden der Integration gesetzt (siehe __init__.py:
# set_integration_language(hass.config.language)). Modul-globaler Zustand ist
# hier bewusst und unproblematisch, da HA nur eine einzige Systemsprache kennt.
_current_language = "de"


def set_integration_language(ha_language: str) -> None:
    """Legt fest, in welcher Sprache unsere EIGENEN Textbausteine erzeugt
    werden. Wird einmal beim Setup aufgerufen, siehe __init__.py."""
    global _current_language
    lang = (ha_language or "de").replace("-", "_").split("_")[0].lower()
    _current_language = lang if lang in _OWN_STRINGS else "en"


def t(key: str) -> str:
    """Übersetzt einen unserer eigenen Textbausteine in die aktuell
    eingestellte Sprache. Fallback: Englisch, dann der Schlüssel selbst
    (damit nie eine leere/kaputte Entity-Bezeichnung entsteht)."""
    strings = _OWN_STRINGS.get(_current_language, _OWN_STRINGS["en"])
    return strings.get(key, _OWN_STRINGS["en"].get(key, key))


def thing_name(thing: dict) -> str:
    """Liefert den Namen eines Things mit sprachabhängigem Fallback statt
    fest 'Unbekannt'."""
    return thing.get("name", t("unknown_thing"))


def iter_standalone_actions(
    coordinator_data: List[dict], thing_class_action_cache: Dict[str, list]
) -> Iterator[Tuple[dict, dict]]:
    """Liefert (thing, action_def) für jede eigenständige Aktion jedes Things.

    "Eigenständig" heißt: kein Zustands-Zwilling (siehe __init__.py), also
    bereits vorgefiltert im thing_class_action_cache.
    """
    for thing in coordinator_data or []:
        class_id = thing.get("thingClassId")
        for action_def in thing_class_action_cache.get(class_id, []):
            yield thing, action_def


def iter_thing_settings(
    coordinator_data: List[dict], thing_class_settings_cache: Dict[str, list]
) -> Iterator[Tuple[dict, dict]]:
    """Liefert (thing, settings_def) für jedes Setting (settingsType) jedes Things.

    Settings sind ein eigenes Nymea-Konzept (settingsTypes auf der ThingClass),
    strukturell identisch zu ParamTypes, aber getrennt von States/Actions -
    persistente Konfigurationswerte, änderbar zur Laufzeit ohne Neueinrichtung.
    """
    for thing in coordinator_data or []:
        class_id = thing.get("thingClassId")
        for settings_def in thing_class_settings_cache.get(class_id, []):
            yield thing, settings_def


def get_current_setting_value(thing: dict, param_type_id: str) -> Any:
    """Liest den aktuell auf dem Gateway gespeicherten Wert eines Settings
    direkt vom Thing-Objekt (Feld "settings", analog zu "states")."""
    for s in thing.get("settings", []):
        if s.get("paramTypeId") == param_type_id:
            return s.get("value")
    return None


def classify_param(param_type: dict) -> str:
    """Ordnet einen Nymea-ParamType generisch einer HA-Entity-Art zu."""
    if param_type.get("allowedValues"):
        return "select"
    ptype = str(param_type.get("type", "")).lower()
    if "bool" in ptype:
        return "bool"
    if ptype in ("int", "uint", "double", "float", "real", "percentage"):
        return "number"
    return "text"


def get_param_default(param_type: dict) -> Any:
    """Bestimmt einen sinnvollen Startwert für einen Parameter."""
    default = param_type.get("defaultValue")
    if default is not None:
        return default

    kind = classify_param(param_type)
    if kind == "bool":
        return False
    if kind == "number":
        return param_type.get("minValue", 0)
    if kind == "select":
        allowed = param_type.get("allowedValues") or [""]
        return allowed[0]
    return ""


def get_staged_value(
    action_param_cache: Dict[str, Dict[str, Dict[str, Any]]],
    thing_id: str,
    action_type_id: str,
    param_id: str,
    default: Any,
) -> Any:
    """Liest den gemerkten Wert eines Aktions-Parameters (mit Lazy-Init)."""
    action_cache = action_param_cache.setdefault(thing_id, {}).setdefault(action_type_id, {})
    if param_id not in action_cache:
        action_cache[param_id] = default
    return action_cache[param_id]


def set_staged_value(
    action_param_cache: Dict[str, Dict[str, Dict[str, Any]]],
    thing_id: str,
    action_type_id: str,
    param_id: str,
    value: Any,
) -> None:
    """Merkt sich einen neuen Parameter-Wert, ohne die Aktion auszulösen."""
    action_param_cache.setdefault(thing_id, {}).setdefault(action_type_id, {})[param_id] = value


def get_staged_params(
    action_param_cache: Dict[str, Dict[str, Dict[str, Any]]],
    thing_id: str,
    action_type_id: str,
) -> Dict[str, Any]:
    """Liefert alle gemerkten Parameterwerte einer Aktion (Kopie)."""
    return dict(action_param_cache.get(thing_id, {}).get(action_type_id, {}))


# Settings sind thing-weit (nicht pro Action), daher gibt es keine echte
# "action_type_id" Ebene. Wir nutzen denselben 3-stufigen Cache/dieselben
# Funktionen wie für Actions und stecken die Settings unter einem festen
# Sentinel-Schlüssel, statt die Logik ein zweites Mal zu schreiben.
_SETTINGS_SENTINEL = "__thing_settings__"


def get_staged_setting(cache, thing_id: str, param_id: str, default: Any) -> Any:
    return get_staged_value(cache, thing_id, _SETTINGS_SENTINEL, param_id, default)


def set_staged_setting(cache, thing_id: str, param_id: str, value: Any) -> None:
    set_staged_value(cache, thing_id, _SETTINGS_SENTINEL, param_id, value)


def get_staged_settings(cache, thing_id: str) -> Dict[str, Any]:
    return get_staged_params(cache, thing_id, _SETTINGS_SENTINEL)


def settings_entity_name(thing: dict, param_def: dict) -> str:
    """Baut den Namen für eine einzelne Settings-Entity: '<Thing> Einstellung: <Name>'."""
    t_name = thing_name(thing)
    param_name = _translate_display_name(param_def)
    return f"{t_name} {t('setting_prefix')}: {param_name}"


def build_device_info(thing: dict, server_info: dict) -> dict:
    """Baut die Device-Info identisch zum Muster in sensor.py/switch.py/number.py."""
    thing_id = thing.get("id")
    t_name = thing_name(thing)
    server_uuid = (server_info or {}).get("uuid", "").replace("{", "").replace("}", "")

    device_info = {
        "identifiers": {(DOMAIN, thing_id)},
        "name": t_name,
        "manufacturer": "Consolinno",
        "model": t("hems_device_model"),
    }
    if server_uuid:
        device_info["via_device"] = (DOMAIN, f"nymea_overview_{server_uuid}")
    return device_info


# Nymea liefert Anzeige-Namen für States/Actions/Settings meist auf Deutsch,
# vereinzelt aber (v.a. bei manchen Action-Parametern) auf Englisch - z.B. bei
# "Netz Exportgrenze festlegen" sind die beiden Parameter selbst englisch
# benannt. Damit am Ende ein durchgängig verständlicher deutscher Name
# entsteht, übersetzen wir die uns bekannten Fälle gezielt. Alles Unbekannte
# fällt automatisch auf den (dann ggf. englischen) Original-Namen von Nymea
# zurück - die Automatik/Flexibilität bleibt also für neue Felder erhalten.
KNOWN_DISPLAY_NAME_TRANSLATIONS = {
    "Grid Export Limit (percent of inverter nominal power)": "Netzeinspeisegrenze (in % der Wechselrichter-Nennleistung)",
    "Inverter Nominal power": "Wechselrichter-Nennleistung",
}


def _translate_display_name(param_def: dict) -> str:
    """Liefert den Anzeigenamen eines Parameters/States, mit deutscher
    Übersetzung für bekannte, englisch benannte Nymea-Felder (siehe
    KNOWN_DISPLAY_NAME_TRANSLATIONS). Unbekannte Felder bleiben unverändert."""
    original = param_def.get("displayName", param_def.get("name", param_def.get("id")))
    return KNOWN_DISPLAY_NAME_TRANSLATIONS.get(original, original)


def action_entity_name(thing: dict, action_def: dict, param_def: dict = None) -> str:
    """Baut einen sprechenden Namen: '<Thing> <Aktion>' bzw. '<Thing> <Aktion> - <Parameter>'."""
    t_name = thing_name(thing)
    action_name = _translate_display_name(action_def)
    if param_def is not None:
        param_name = _translate_display_name(param_def)
        return f"{t_name} {action_name} - {param_name}"
    return f"{t_name} {action_name}"


def action_button_name(thing: dict, action_def: dict) -> str:
    """Name für den Button, der eine Aktion auslöst - mit sprachabhängigem
    'ausführen'/'execute'-Suffix, damit klar ist, dass ein Knopfdruck etwas
    passieren lässt (statt es mit einem Sensor zu verwechseln)."""
    return f"{action_entity_name(thing, action_def)} {t('execute_suffix')}"


# ------------------------------------------------------------------
# Hems-API Helper (PV-Konfiguration, Überlastschutz/HousholdPhaseLimit).
# Anders als bei States/Actions/Settings gibt es hier KEINE abfragbare
# Typ-Liste - jeder Hems-Konfigurationstyp ist eine im Consolinno-Plugin fest
# einprogrammierte Struktur. Diese Helper decken gezielt PvConfiguration und
# HousholdPhaseLimit ab (siehe __init__.py Diagnose-Log für die Rohdaten).
# ------------------------------------------------------------------

# PV-Settings sind pro pvThingId gestaged (nie sofort ausgelöst), analog zu
# Settings - ein gemeinsamer "Speichern"-Button sendet dann die komplette
# PvConfiguration auf einmal (das erwartet Hems.SetPvConfiguration so).
_PV_SENTINEL = "__pv_config__"


def get_staged_pv_value(cache, pv_thing_id: str, field: str, default: Any) -> Any:
    return get_staged_value(cache, pv_thing_id, _PV_SENTINEL, field, default)


def set_staged_pv_value(cache, pv_thing_id: str, field: str, value: Any) -> None:
    set_staged_value(cache, pv_thing_id, _PV_SENTINEL, field, value)


def get_staged_pv_config(cache, pv_thing_id: str) -> Dict[str, Any]:
    return get_staged_params(cache, pv_thing_id, _PV_SENTINEL)


def find_thing_by_id(coordinator_data: List[dict], thing_id: str) -> dict:
    """Sucht ein Thing anhand seiner ID in den Coordinator-Daten (z.B. um das
    zur PV-Konfiguration gehörende Inverter-Thing für die Geräte-Zuordnung zu
    finden - pvThingId verweist auf ein ganz normales, existierendes Thing)."""
    for thing in coordinator_data or []:
        if thing.get("id") == thing_id:
            return thing
    return None


def build_system_device_info(server_info: dict) -> dict:
    """Device-Info für Hems-weite Werte ohne zugehöriges einzelnes Thing
    (z.B. Überlastschutz/HousholdPhaseLimit) - eigenes virtuelles Gerät,
    getrennt von den einzelnen Nymea-Things."""
    return {
        "identifiers": {(DOMAIN, "hems_system")},
        "name": t("hems_system_device"),
        "manufacturer": "Consolinno",
        "model": t("hems_optimizer_model"),
    }