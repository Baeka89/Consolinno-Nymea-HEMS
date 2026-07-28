# Consolinno Nymea HEMS Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Maintainer](https://img.shields.io/badge/Maintainer-Baeka89-blue.svg)](https://github.com/Baeka89)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)
[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://paypal.me/misomazo)

[Deutsch](#deutsch) | [English](#english)

---

<a name="deutsch"></a>
## Deutsch 🇩🇪

### Über dieses Projekt
Diese Custom Integration ermöglicht die nahtlose Einbindung des **Consolinno Leaflet HEMS** (basierend auf nymea) in Home Assistant. Die Integration kommuniziert direkt mit der lokalen API deines HEMS, um alle konfigurierten Geräte ("Things") und deren Statuswerte automatisch als Entitäten bereitzustellen – inklusive Steuerung von Schaltern, Zahlenwerten und Auswahlfeldern.

### Features
* **Automatische Erkennung:** Erfasst alle im HEMS vorhandenen Geräte und Zustände automatisch via `Integrations.GetThings`.
* **Breite Entitäts-Abdeckung:** Erstellt Sensoren, Schalter, Zahlen, Binärsensoren, Auswahlfelder und Buttons dynamisch aus den verfügbaren Nymea-Datenpunkten.
* **Fernverbindung steuerbar:** Die Consolinno-Fernverbindung (Remote-Zugriff über den Proxy-Server) lässt sich direkt als Schalter in Home Assistant ein- und ausschalten – ein einmaliges Aktivieren über die Nymea-App reicht als Startpunkt, danach übernimmt Home Assistant dauerhaft die Steuerung (der zuletzt bekannte Verbindungsstatus wird auch über Neustarts hinweg gespeichert).
* **Intelligentes Mapping:** Automatische Zuordnung von Einheiten (Watt, kWh, Celsius etc.) zu den entsprechenden Home Assistant Device Classes.
* **Mehrsprachig:** Nymea-seitige Anzeigenamen folgen automatisch der in Home Assistant eingestellten Sprache.
* **Nachträglich änderbare Verbindungsdaten:** IP-Adresse und Poll-Intervall lassen sich jederzeit über **Einstellungen > Geräte & Dienste > Konfigurieren** anpassen, ohne die Integration neu einrichten zu müssen.
* **Effizientes Polling:** Optimierte, Push-basierte Datenabfrage, um die API-Last des HEMS gering zu halten.
* **Optimiertes Datenhandling:** Komplexe Payloads werden sicher in Attributen gespeichert, um die 255-Zeichen-Beschränkung von Statuswerten zu umgehen.

### Installation
1. Kopiere den Ordner `consolinno_nymea_hems` in das Verzeichnis `custom_components` deiner Home Assistant Instanz.
2. Starte Home Assistant neu.
3. Gehe zu **Einstellungen > Geräte & Dienste > Integration hinzufügen**.
4. Suche nach **Consolinno Nymea HEMS**.

### Konfiguration
Bei der Einrichtung werden folgende Informationen benötigt:
* **Host:** Die IP-Adresse deines HEMS-Moduls.
* **Port:** Standardmäßig `2222`.
* **Benutzername & Passwort:** Deine Nymea-Zugangsdaten.

Änderungen an IP-Adresse oder Poll-Intervall müssen nicht neu eingerichtet werden – dafür einfach bei der Integration auf **Konfigurieren** gehen.

### Unterstützung
Wenn dir diese Integration hilft, freue ich mich über eine kleine Unterstützung für die Weiterentwicklung:
👉 **[Spende via PayPal](https://paypal.me/misomazo)**

---

<a name="english"></a>
## English 🇺🇸

### About this Project
This custom integration allows Home Assistant to interface with the **Consolinno Leaflet HEMS** (powered by nymea). It automatically discovers all connected "Things" and their states, exposing them as native Home Assistant entities – including control of switches, numbers, and select inputs.

### Features
* **Automatic Discovery:** Automatically fetches all devices and states via `Integrations.GetThings`.
* **Broad Entity Coverage:** Dynamically creates sensors, switches, numbers, binary sensors, selects, and buttons based on the available Nymea data points.
* **Controllable Remote Connection:** The Consolinno remote connection (proxy-based remote access) can be turned on/off directly from a Home Assistant switch. A one-time activation via the Nymea app is only needed as a starting point – after that, Home Assistant fully manages it, and the last known state survives Home Assistant restarts.
* **Smart Unit Mapping:** Maps Nymea units (e.g., UnitWatt) to Home Assistant's standard device classes.
* **Multi-language:** Nymea-side display names automatically follow Home Assistant's configured language.
* **Editable Connection Details:** IP address and poll interval can be changed anytime via **Settings > Devices & Services > Configure**, without having to remove and re-add the integration.
* **Efficient Updates:** Push-driven, optimized polling logic to reduce API overhead on your HEMS.
* **Payload Management:** Large or complex data values are stored in sensor attributes to stay within state character limits.

### Installation
1. Copy the `consolinno_nymea_hems` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Navigate to **Settings > Devices & Services > Add Integration**.
4. Search for **Consolinno Nymea HEMS**.

### Configuration
You will need the following details during setup:
* **Host:** The IP address of your HEMS module.
* **Port:** Default is `2222`.
* **Username & Password:** Your Nymea credentials.

Changing the IP address or poll interval later doesn't require removing the integration – just use **Configure** on the integration entry.

### Support
If you find this integration useful, please consider supporting its development:
👉 **[Donate via PayPal](https://paypal.me/misomazo)**

---

### Technische Komponenten / Technical Components
* `manifest.json`: Metadaten, Versionierung und Abhängigkeiten / Integration metadata and requirements.
* `__init__.py`: Verbindungsaufbau, Update-Koordinator und Setup / Connection setup, update coordinator and entry setup.
* `config_flow.py`: Benutzerführung für Ersteinrichtung und Optionen (Host/Poll-Intervall) / User flow for initial setup and options (host/poll interval).
* `const.py`: Zentrale Definitionen und Konstanten / Global constants and domain definitions.
* `nymea_client.py`: JSON-RPC-Client für die Kommunikation mit der Nymea-API / JSON-RPC client for talking to the Nymea API.
* `nymea_action_helpers.py`: Hilfsfunktionen für Aktionen und eigene Textbausteine / Helpers for actions and custom text snippets.
* `sensor.py` / `binary_sensor.py`: Sensor- und Binärsensor-Entitäten / Sensor and binary sensor entities.
* `switch.py`: Schalter-Entitäten, inkl. Steuerung der Fernverbindung / Switch entities, including remote-connection control.
* `number.py` / `select.py` / `button.py` / `text.py`: Steuerbare Entitäten (Zahlen, Auswahlfelder, Buttons, Text) / Controllable entities (numbers, selects, buttons, text).
* `translations/`: Übersetzungen für Config-Flow und Optionen (DE/EN) / Translations for config flow and options (DE/EN).

### Lizenz / License
MIT – siehe [LICENSE](LICENSE) / see [LICENSE](LICENSE).