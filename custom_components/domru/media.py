"""Helpers for optional camera audio transport."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.setup import async_setup_component

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_camera_audio(hass: HomeAssistant) -> None:
    """Set up go2rtc for WebRTC audio without making it a hard dependency."""
    try:
        available = await async_setup_component(hass, "go2rtc", {"go2rtc": {}})
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "go2rtc setup failed; camera streams will remain video-only",
            exc_info=True,
        )
        return

    if not available:
        _LOGGER.warning("go2rtc is unavailable; camera streams will remain video-only")
        return

    _LOGGER.info("go2rtc is available for camera audio transcoding")
