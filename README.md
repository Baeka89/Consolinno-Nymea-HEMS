# Consolinno Nymea HEMS Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Maintainer](https://img.shields.io/badge/Maintainer-Baeka89-blue.svg)](https://github.com/Baeka89)
[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://paypal.me/misomazo)

[Deutsch](#deutsch) | [English](#english)

---

<a name="deutsch"></a>
## Deutsch 🇩🇪

### Über dieses Projekt
Diese Custom Integration ermöglicht die nahtlose Einbindung des **Consolinno Leaflet HEMS** (basierend auf nymea) in Home Assistant. Die Integration kommuniziert direkt mit der lokalen API deines HEMS, um alle konfigurierten Geräte ("Things") und deren Statuswerte automatisch als Sensoren bereitzustellen.

### Features
* **Automatische Erkennung:** Erfasst alle im HEMS vorhandenen Geräte und Zustände automatisch via `Integrations.GetThings`.
* **Dynamische Sensoren:** Erstellt Entitäten basierend auf den verfügbaren Nymea-Datenpunkten direkt aus der `sensor.py`.
* **Intelligentes Mapping:** Automatische Zuordnung von Einheiten (Watt, kWh, Celsius etc.) zu den entsprechenden Home Assistant Device Classes.
* **Effizientes Polling:** Optimierte Datenabfrage, um die API-Last des HEMS gering zu halten.
* **Optimiertes Datenhandling:** Komplexe Payloads werden sicher in Attributen gespeichert, um die 255-Zeichen-Beschränkung von Statuswerten zu umgehen.

### Installation
1. Kopiere den Ordner `consolinno_nymea` in das Verzeichnis `custom_components` deiner Home Assistant Instanz.
2. Starte Home Assistant neu.
3. Gehe zu **Einstellungen > Geräte & Dienste > Integration hinzufügen**.
4. Suche nach **Consolinno Nymea HEMS**.

### Konfiguration
Bei der Einrichtung werden folgende Informationen benötigt:
* **Host:** Die IP-Adresse deines HEMS-Moduls.
* **Port:** Standardmäßig `2222`.
* **Benutzername & Passwort:** Deine Nymea-Zugangsdaten.

### Unterstützung
Wenn dir diese Integration hilft, freue ich mich über eine kleine Unterstützung für die Weiterentwicklung:
👉 **[Spende via PayPal](https://paypal.me/misomazo)**

---

<a name="english"></a>
## English 🇺🇸

### About this Project
This custom integration allows Home Assistant to interface with the **Consolinno Leaflet HEMS** (powered by nymea). It automatically discovers all connected "Things" and their states, exposing them as native Home Assistant sensors.

### Features
* **Automatic Discovery:** Automatically fetches all devices and states via `Integrations.GetThings`.
* **Dynamic Sensor Creation:** Entities are created on-the-fly based on available Nymea data points.
* **Smart Unit Mapping:** Maps Nymea units (e.g., UnitWatt) to Home Assistant's standard device classes.
* **Efficient Updates:** Optimized polling logic to reduce API overhead on your HEMS.
* **Payload Management:** Large or complex data values are stored in sensor attributes to stay within state character limits.

### Installation
1. Copy the `consolinno_nymea` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Navigate to **Settings > Devices & Services > Add Integration**.
4. Search for **Consolinno Nymea HEMS**.

### Configuration
You will need the following details during setup:
* **Host:** The IP address of your HEMS module.
* **Port:** Default is `2222`.
* **Username & Password:** Your Nymea credentials.

### Support
If you find this integration useful, please consider supporting its development:
👉 **[Donate via PayPal](https://paypal.me/misomazo)**

---

### Technische Komponenten / Technical Components
* `manifest.json`: Metadaten, Versionierung und Abhängigkeiten / Integration metadata and requirements.
* `sensor.py`: Logik für die Sensorgenerierung und Statusverarbeitung / Core logic for sensor generation.
* `const.py`: Zentrale Definitionen und Konstanten / Global constants and domain definitions.
* `__init__.py`: Handhabt den Verbindungsaufbau und das Setup / Handles connection and integration setup.
* `config_flow.py`: Benutzerführung für die Einrichtung in der UI / User interface for the integration setup.