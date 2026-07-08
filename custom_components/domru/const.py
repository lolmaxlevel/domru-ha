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
CONF_FCM_CREDENTIALS = "fcm_credentials"

# SIP registration modes
SIP_MODE_PERSISTENT = "persistent"
SIP_MODE_ON_DEMAND = "on_demand"
DEFAULT_SIP_MODE = SIP_MODE_ON_DEMAND

# Default polling interval for on-demand mode (seconds)
DEFAULT_SIP_POLL_INTERVAL = 3

# Authentication methods
AUTH_METHOD_PASSWORD = "password"  # noqa: S105
AUTH_METHOD_PHONE = "phone"

# Dispatcher signals
SIGNAL_CALL_STATUS_UPDATE = f"{DOMAIN}_call_status_update"
SIGNAL_COURIER_AUTO_OPEN_UPDATE = f"{DOMAIN}_courier_auto_open_update"
SIGNAL_DOORBELL = f"{DOMAIN}_doorbell"

# Firebase/FCM config mirrored from the Android app used by the reference
# integration. These identifiers are public app metadata, not account secrets.
FCM_PROJECT_ID = "ntk-myhome"
FCM_APP_ID = "1:369367231553:android:323a999f9f228a40"
FCM_SENDER_ID = "369367231553"
FCM_API_KEY = "AIzaSyB_26K8ZB7iu7qZBpBf5c4NLgvTC3Yrgpk"
FCM_BUNDLE_ID = "ru.inetra.intercom"

ANDROID_APP_VERSION_NAME = "8.9.2"
ANDROID_APP_VERSION_CODE = "8090200"
ANDROID_DEVICE_MANUFACTURER = "Google"
ANDROID_DEVICE_MODEL = "sdk_gphone64_x86_64"
ANDROID_OS_VERSION = "14"
