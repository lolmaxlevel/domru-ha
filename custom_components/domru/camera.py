"""Camera platform for Dom.ru Smart Intercom."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform."""
    # Wait for initial data load
    coordinator = entry.runtime_data.coordinator
    if not coordinator.data:
        await coordinator.async_config_entry_first_refresh()

    # Get cameras from coordinator data
    cameras_data = coordinator.data.get("cameras", [])

    entities = []
    for camera_data in cameras_data:
        # Support both formats: Go model (ID, Name) and old format (id, name)
        camera_id = camera_data.get("ID") or camera_data.get("id")
        camera_name = camera_data.get("Name") or camera_data.get("name") or f"Camera {camera_id}"

        if camera_id:  # Only add if we have an ID
            entities.append(
                DomruCamera(
                    coordinator=coordinator,
                    client=entry.runtime_data.client,
                    camera_id=camera_id,
                    camera_name=camera_name,
                )
            )

    async_add_entities(entities)


class DomruCamera(DomruEntity, Camera):
    """Dom.ru camera class."""

    # Указываем, что камера поддерживает стриминг
    _attr_supported_features: CameraEntityFeature = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        client,
        camera_id: str | int,
        camera_name: str,
    ) -> None:
        """Initialize the camera class."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._client = client
        self._camera_id = camera_id
        self._attr_name = camera_name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{camera_id}"
        self._stream_url: str | None = None
        # Отключаем автоматическое обновление снимков, используем только стрим
        self._attr_is_streaming = True

    async def stream_source(self) -> str | None:
        """Return the source of the stream (RTSP URL)."""
        try:
            # Cache stream URL to avoid multiple API calls
            if not self._stream_url:
                _LOGGER.debug("Fetching RTSP stream URL for camera %s", self._camera_id)
                self._stream_url = await self._client.async_get_camera_stream_url(self._camera_id)
                _LOGGER.info("Got RTSP stream URL for camera %s: %s", self._camera_id, self._stream_url)
            return self._stream_url
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error getting stream URL for camera %s: %s", self._camera_id, err)
            return None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image."""
        # Этот метод используется как fallback если стрим недоступен
        # или для получения thumbnail в UI
        try:
            _LOGGER.debug("Fetching snapshot for camera %s", self._camera_id)
            return await self._client.async_get_camera_snapshot(self._camera_id)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error getting snapshot for camera %s: %s", self._camera_id, err)
            return None

