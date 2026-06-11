"""Constants for Dom.ru Smart Intercom."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "domru"
ATTRIBUTION = "Data provided by Dom.ru API"

# Configuration option keys
CONF_CAMERA_STREAM_CACHE = "camera_stream_cache"
CONF_CAMERA_STREAM_CACHE_TIME = "camera_stream_cache_time"
CONF_AUTH_METHOD = "auth_method"
CONF_PHONE = "phone"
CONF_ACCOUNT_ID = "account_id"
CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105
CONF_OPERATOR_ID = "operator_id"
CONF_SIP_ENABLED = "sip_enabled"
CONF_SIP_LOCAL_IP = "sip_local_ip"
CONF_SIP_HOST_IP = "sip_host_ip"
CONF_SIP_LOCAL_PORT = "sip_local_port"
CONF_SIP_MODE = "sip_mode"
CONF_SIP_POLL_INTERVAL = "sip_poll_interval"

# SIP registration modes
SIP_MODE_PERSISTENT = "persistent"
SIP_MODE_ON_DEMAND = "on_demand"

# Default polling interval for on-demand mode (seconds)
DEFAULT_SIP_POLL_INTERVAL = 3

# Authentication methods
AUTH_METHOD_PASSWORD = "password"  # noqa: S105
AUTH_METHOD_PHONE = "phone"

# Dispatcher signals
SIGNAL_CALL_STATUS_UPDATE = f"{DOMAIN}_call_status_update"
SIGNAL_COURIER_AUTO_OPEN_UPDATE = f"{DOMAIN}_courier_auto_open_update"
