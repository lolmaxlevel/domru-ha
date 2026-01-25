"""Constants for Dom.ru Smart Intercom."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "domru"
ATTRIBUTION = "Data provided by Dom.ru API"

# Configuration option keys
CONF_CAMERA_STREAM_CACHE = "camera_stream_cache"
CONF_CAMERA_STREAM_CACHE_TIME = "camera_stream_cache_time"
