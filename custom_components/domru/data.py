"""Custom types for Dom.ru Smart Intercom."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator


type DomruConfigEntry = ConfigEntry[DomruData]


@dataclass
class DomruData:
    """Data for the Dom.ru Smart Intercom integration."""

    client: DomruApiClient
    coordinator: DomruDataUpdateCoordinator
    integration: Integration
