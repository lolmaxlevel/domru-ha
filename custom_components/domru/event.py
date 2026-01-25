"""Event platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.event import EventDeviceClass, EventEntity

from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event platform."""
    async_add_entities(
        [
            DomruCallEvent(
                coordinator=entry.runtime_data.coordinator,
            )
        ]
    )


class DomruCallEvent(DomruEntity, EventEntity):
    """Dom.ru call event entity."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types: ClassVar[list[str]] = [
        "call_accepted",
        "call_rejected",
        "call_missed",
        "door_opened",
        "motion_detected",
        "unknown",
    ]

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator)
        self._attr_name = "События домофона"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_intercom_events"

    def trigger_event(self, event_type: str, event_data: dict) -> None:
        """Trigger an event."""
        # Маппинг типов событий API на события Home Assistant
        event_type_map = {
            "accessControlCallAccepted": "call_accepted",
            "accessControlCallRejected": "call_rejected",
            "accessControlCallMissed": "call_missed",
            "accessControlOpen": "door_opened",
            "motionDetected": "motion_detected",
        }

        ha_event_type = event_type_map.get(event_type, "unknown")

        self._trigger_event(
            ha_event_type,
            {
                "message": event_data.get("message", ""),
                "event_id": event_data.get("id", ""),
                "source_type": event_data.get("source", {}).get("type", ""),
                "source_id": event_data.get("source", {}).get("id", ""),
            },
        )
        self.async_write_ha_state()
