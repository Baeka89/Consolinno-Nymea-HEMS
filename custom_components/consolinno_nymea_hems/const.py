"""Constants for Consolinno Nymea HEMS integration."""

DOMAIN = "consolinno_nymea_hems"
# Hinweis: CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD werden bewusst NICHT
# hier definiert, da im gesamten Code stattdessen die Standardkonstanten aus
# homeassistant.const verwendet werden. Eigene, gleichnamige Konstanten hier
# wären toter Code und nur eine Verwechslungsgefahr.
CONF_SSL = "ssl"
CONF_POLL_INTERVAL = "poll_interval"

# Standardwerte - DIESE MÜSSEN VORHANDEN SEIN
DEFAULT_PORT = 2222
DEFAULT_SSL = True
DEFAULT_POLL_INTERVAL = 60

# Fallback-Template für die Fernverbindung (TunnelProxyServerConfiguration),
# falls noch NIE eine echte Konfiguration gesehen wurde (frische Installation,
# noch kein Store-Wert vorhanden). Über 5 unabhängige Aktivierungen aus der
# Nymea-App hinweg empirisch bestätigt als konstant - nur "id" ändert sich pro
# Aktivierung und wird clientseitig frisch erzeugt (siehe switch.py). Wird
# IMMER von einem echten, beobachteten Wert überschrieben, sobald einer
# vorliegt - dient nur als Startpunkt für den absolut ersten Einschaltvorgang.
DEFAULT_TUNNEL_PROXY_TEMPLATE = {
    "address": "hems-remoteproxy.services.consolinno.de",
    "port": 2213,
    "sslEnabled": True,
    "authenticationEnabled": True,
    "ignoreSslErrors": False,
}

JSONRPC_HELLO_METHOD = "JSONRPC.Hello"
JSONRPC_AUTH_METHOD = "JSONRPC.Authenticate"
INTEGRATIONS_GET_THINGS = "Integrations.GetThings"