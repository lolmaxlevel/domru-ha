"""Binary sensor platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

ENTITY_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="has_cameras",
        name="Доступны камеры",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="has_access_controls",
        name="Доступны домофоны",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="recent_call",
        name="Недавний звонок",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        icon="mdi:phone-ring",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""
    async_add_entities(
        DomruBinarySensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class DomruBinarySensor(DomruEntity, BinarySensorEntity):
    """Dom.ru binary_sensor class."""

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary_sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        # Set unique ID for this binary sensor
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return true if the binary_sensor is on."""
        data = self.coordinator.data

        if self.entity_description.key == "has_cameras":
            cameras = data.get("cameras", [])
            return len(cameras) > 0

        if self.entity_description.key == "has_access_controls":
            access_controls = data.get("access_controls", [])
            return len(access_controls) > 0

        if self.entity_description.key == "recent_call":
            # Проверяем, был ли звонок в последние 60 секунд
            events = data.get("events", [])
            if not events:
                return False

            # Ищем последний звонок
            for event in events:
                event_type = event.get("eventTypeName", "")
                if event_type in [
                    "accessControlCallAccepted",
                    "accessControlCallRejected",
                    "accessControlCallMissed",
                ]:
                    timestamp = event.get("timestamp")
                    if timestamp:
                        try:
                            event_time = datetime.fromtimestamp(int(timestamp), tz=UTC)
                            now = datetime.now(UTC)
                            # Звонок был в последние 60 секунд
                            if (now - event_time) < timedelta(seconds=60):
                                return True
                        except (ValueError, TypeError, OSError):
                            pass
                    break  # Проверили самое свежее событие звонка

            return False

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.key == "recent_call":
            data = self.coordinator.data
            events = data.get("events", [])

            # Найти последний звонок
            for event in events:
                event_type = event.get("eventTypeName", "")
                if event_type in [
                    "accessControlCallAccepted",
                    "accessControlCallRejected",
                    "accessControlCallMissed",
                ]:
                    event_type_map = {
                        "accessControlCallAccepted": "Звонок принят",
                        "accessControlCallRejected": "Звонок отклонен",
                        "accessControlCallMissed": "Пропущенный звонок",
                    }

                    return {
                        "message": event.get("message", ""),
                        "type": event_type,
                        "type_display": event_type_map.get(event_type, event_type),
                        "timestamp": event.get("timestamp"),
                        "event_id": event.get("id"),
                    }

        return None
