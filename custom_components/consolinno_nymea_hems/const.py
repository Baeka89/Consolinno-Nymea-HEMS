"""Constants for Consolinno Nymea HEMS integration."""

DOMAIN = "consolinno_nymea_hems"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SSL = "ssl"
CONF_POLL_INTERVAL = "poll_interval"

# Standardwerte - DIESE MÜSSEN VORHANDEN SEIN
DEFAULT_PORT = 2222
DEFAULT_SSL = True
DEFAULT_POLL_INTERVAL = 60

JSONRPC_HELLO_METHOD = "JSONRPC.Hello"
JSONRPC_AUTH_METHOD = "JSONRPC.Authenticate"
INTEGRATIONS_GET_THINGS = "Integrations.GetThings"