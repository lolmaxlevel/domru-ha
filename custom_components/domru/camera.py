"""Camera platform for Dom.ru Smart Intercom."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature

from .camera_source import camera_sources_from_data
from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

_LOGGER = logging.getLogger(__name__)
_GO2RTC_SESSION_WAIT_TIMEOUT = 10
_HA_MANAGED_GO2RTC_URL = "http://localhost:11984"
_HA_MANAGED_GO2RTC_RTSP_URL = "rtsp://127.0.0.1:18554"


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform."""
    # Wait for initial data load
    coordinator = entry.runtime_data.coordinator
    if not coordinator.data:
        await coordinator.async_config_entry_first_refresh()

    entities = [
        DomruCamera(
            coordinator=coordinator,
            client=entry.runtime_data.client,
            camera_id=source.get("camera_id"),
            camera_name=source["name"],
            camera_data=source["data"],
            has_sound=source["has_sound"],
            config_entry=entry,
            unique_id_suffix=source["unique_id"],
            snapshot_type=source["snapshot"],
            place_id=source.get("place_id"),
            access_control_id=source.get("access_control_id"),
        )
        for source in camera_sources_from_data(coordinator.data)
    ]

    async_add_entities(entities)


class DomruCamera(DomruEntity, Camera):
    """Dom.ru camera class."""

    # Указываем, что камера поддерживает стриминг
    _attr_supported_features: CameraEntityFeature = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        client: DomruApiClient,
        camera_id: str | int | None,
        camera_name: str,
        camera_data: dict,
        *,
        has_sound: bool = False,
        config_entry: DomruConfigEntry | None = None,
        unique_id_suffix: str | None = None,
        snapshot_type: str = "forpost",
        place_id: str | int | None = None,
        access_control_id: str | int | None = None,
    ) -> None:
        """Initialize the camera class."""
        super().__init__(coordinator)
        # CoordinatorEntity does not continue cooperative initialization to Camera.
        Camera.__init__(self)
        self._client = client
        self._camera_id = camera_id
        self._camera_data = camera_data
        self._has_sound = has_sound
        self._audio_proxy_logged = False
        self._audio_stream_name = (
            f"domru_{coordinator.config_entry.entry_id}_{camera_id}"
        )
        self._attr_name = camera_name
        self._snapshot_type = snapshot_type
        self._place_id = place_id
        self._access_control_id = access_control_id
        unique_id = unique_id_suffix or f"camera_{camera_id}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{unique_id}"
        self._stream_url: str | None = None
        self._stream_url_time: float | None = None

        # Get caching settings from config entry options
        if config_entry is None:
            config_entry = coordinator.config_entry

        options = config_entry.options
        self._enable_cache = options.get("camera_stream_cache", False)
        self._stream_url_cache_time = float(
            options.get("camera_stream_cache_time", 300)
        )

        # Отключаем автоматическое обновление снимков, используем только стрим
        self._attr_is_streaming = True

        if has_sound:
            _LOGGER.info("Camera %s reports audio support", camera_id)

        # Dom.ru returns HTTPS/FLV, so RTSP-specific PyAV options must stay unset.
        self.stream_options = {}

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: object
    ) -> None:
        """Preserve early ICE candidates while go2rtc prepares the source."""
        provider = self._webrtc_provider
        sessions = getattr(provider, "_sessions", None) if provider else None
        if (
            provider
            and provider.domain == "go2rtc"
            and isinstance(sessions, dict)
            and session_id not in sessions
        ):
            _LOGGER.debug("Waiting for go2rtc WebRTC session %s", session_id)
            try:
                async with asyncio.timeout(_GO2RTC_SESSION_WAIT_TIMEOUT):
                    # The core provider exposes no readiness event; its private
                    # session map is the only observable race boundary.
                    while session_id not in sessions:  # noqa: ASYNC110
                        await asyncio.sleep(0.01)
            except TimeoutError:
                _LOGGER.warning(
                    "Timed out waiting for go2rtc WebRTC session %s", session_id
                )

        await super().async_on_webrtc_candidate(session_id, candidate)

    async def stream_source(self) -> str | None:
        """Return the source of the stream (RTSP URL)."""
        if self._camera_id is None:
            return None

        current_time = time.time()

        # If caching is disabled, always fetch fresh URL
        if not self._enable_cache:
            try:
                _LOGGER.debug(
                    "Fetching fresh stream URL for camera %s", self._camera_id
                )
                url = await self._client.async_get_camera_stream_url(self._camera_id)
                _LOGGER.info(
                    "Got stream URL for camera %s",
                    self._camera_id,
                )
                return await self._async_source_with_audio_proxy(url)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Error getting stream URL for camera %s", self._camera_id
                )
                return None

        # If caching is enabled, check if cache is expired
        if (
            not self._stream_url
            or not self._stream_url_time
            or (current_time - self._stream_url_time) > self._stream_url_cache_time
        ):
            try:
                _LOGGER.debug(
                    "Fetching stream URL for camera %s (cache expired)",
                    self._camera_id,
                )
                self._stream_url = await self._client.async_get_camera_stream_url(
                    self._camera_id
                )
                self._stream_url_time = current_time
                _LOGGER.info(
                    "Got stream URL for camera %s",
                    self._camera_id,
                )
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Error getting stream URL for camera %s", self._camera_id
                )
                return None
        if self._stream_url is None:
            return None
        return await self._async_source_with_audio_proxy(self._stream_url)

    async def _async_source_with_audio_proxy(self, source_url: str) -> str:
        """Prepare a managed go2rtc stream with browser-compatible audio."""
        provider = self._webrtc_provider
        if (
            not self._has_sound
            or provider is None
            or provider.domain != "go2rtc"
            or str(getattr(provider, "_url", "")).rstrip("/") != _HA_MANAGED_GO2RTC_URL
        ):
            return source_url

        rest_client = getattr(provider, "_rest_client", None)
        streams = getattr(rest_client, "streams", None)
        add_stream = getattr(streams, "add", None)
        if not callable(add_stream):
            return source_url

        stream_name = self._audio_stream_name
        go2rtc_source = f"ffmpeg:{source_url}#video=copy#audio=aac#audio=opus"
        try:
            await add_stream(stream_name, go2rtc_source)
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-except
            _LOGGER.warning(
                "Camera %s audio proxy failed; using direct stream fallback (%s)",
                self._camera_id,
                type(err).__name__,
            )
            return source_url

        if not self._audio_proxy_logged:
            self._audio_proxy_logged = True
            _LOGGER.info(
                "Camera %s managed go2rtc audio proxy is ready",
                self._camera_id,
            )
        return f"{_HA_MANAGED_GO2RTC_RTSP_URL}/{quote(stream_name, safe='')}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image."""
        # Этот метод используется как fallback если стрим недоступен
        # или для получения thumbnail в UI
        _ = width, height  # Unused parameters
        try:
            if (
                self._snapshot_type == "access_control"
                and self._place_id is not None
                and self._access_control_id is not None
            ):
                _LOGGER.debug(
                    "Fetching access control snapshot for %s",
                    self._access_control_id,
                )
                return await self._client.async_get_access_control_snapshot(
                    self._place_id,
                    self._access_control_id,
                )

            if self._camera_id is None:
                return None

            _LOGGER.debug("Fetching snapshot for camera %s", self._camera_id)
            return await self._client.async_get_camera_snapshot(self._camera_id)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Error getting snapshot for camera %s", self._camera_id)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | bool]:
        """Return extra state attributes."""
        return {
            "camera_id": self._camera_id,
            "snapshot_type": self._snapshot_type,
            "place_id": self._place_id,
            "access_control_id": self._access_control_id,
            "has_sound": self._has_sound,
            "is_active": self._camera_data.get("IsActive") == 1,
            "state": "online" if self._camera_data.get("State") == 1 else "offline",
            "motion_detector": self._camera_data.get("MotionDetectorMode"),
            "record_type": self._camera_data.get("RecordType"),
            "quota_seconds": self._camera_data.get("Quota"),
            "timezone": self._camera_data.get("TimeZone"),
        }
