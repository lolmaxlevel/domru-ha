"""Custom types for Dom.ru Smart Intercom."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator
    from .fcm import DomruFcmListener
    from .sip import DomruSipClient


type DomruConfigEntry = ConfigEntry[DomruData]


@dataclass
class DomruData:
    """Data for the Dom.ru Smart Intercom integration."""

    client: DomruApiClient
    coordinator: DomruDataUpdateCoordinator
    integration: Integration
    sip_client: DomruSipClient | None = None
    fcm_listener: DomruFcmListener | None = None
    event_poller: asyncio.Task[None] | None = None
    courier_auto_open_enabled: bool = False
    courier_auto_open_in_progress: bool = False
    courier_auto_open_access_control_id: str | int | None = None
