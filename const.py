"""Constants for Consolinno Nymea HEMS integration."""

DOMAIN = "nymea_hem"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SSL = "ssl"
CONF_POLL_INTERVAL = "poll_interval"

# WICHTIG: Diese Werte fehlen aktuell laut Log
DEFAULT_PORT = 2222
DEFAULT_SSL = True
DEFAULT_POLL_INTERVAL = 60

JSONRPC_HELLO_METHOD = "JSONRPC.Hello"
JSONRPC_AUTH_METHOD = "JSONRPC.Authenticate"
INTEGRATIONS_GET_THINGS = "Integrations.GetThings"