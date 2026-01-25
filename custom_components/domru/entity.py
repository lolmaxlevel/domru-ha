"""DomruEntity class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import DomruDataUpdateCoordinator


class DomruEntity(CoordinatorEntity[DomruDataUpdateCoordinator]):
    """DomruEntity class."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: DomruDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        # Don't set unique_id here - let each entity set its own
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            name="Домофон",
        )
