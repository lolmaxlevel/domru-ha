"""Sensor platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.util import dt as dt_util

from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

ENTITY_DESCRIPTIONS = (
    SensorEntityDescription(
        key="balance",
        name="Баланс",
        icon="mdi:cash",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="₽",
    ),
    SensorEntityDescription(
        key="amount_sum",
        name="Сумма к оплате",
        icon="mdi:cash-multiple",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="₽",
    ),
    SensorEntityDescription(
        key="block_status",
        name="Статус блокировки",
        icon="mdi:lock-check",
    ),
    SensorEntityDescription(
        key="target_date",
        name="Дата следующего платежа",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="events_count",
        name="Количество событий",
        icon="mdi:history",
    ),
    SensorEntityDescription(
        key="last_event",
        name="Последнее событие",
        icon="mdi:bell-ring",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        DomruSensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class DomruSensor(DomruEntity, SensorEntity):
    """Dom.ru Sensor class."""

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        # Set unique ID for this sensor
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{entity_description.key}"

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return the native value of the sensor."""
        data = self.coordinator.data
        finances = data.get("finances", {})

        if self.entity_description.key == "balance":
            return finances.get("balance")

        if self.entity_description.key == "amount_sum":
            return finances.get("amountSum")

        if self.entity_description.key == "block_status":
            block_type = finances.get("blockType", "UNKNOWN")
            blocked = finances.get("blocked", False)
            if blocked:
                return "Заблокирован"
            if block_type == "NOT_BLOCKED":
                return "Не заблокирован"
            return block_type

        if self.entity_description.key == "target_date":
            target_date = finances.get("targetDate")
            if target_date:
                # Parse ISO 8601 timestamp string to datetime object
                try:
                    return dt_util.parse_datetime(target_date)
                except (ValueError, TypeError):
                    return None
            return None

        # Events
        events = data.get("events", [])

        if self.entity_description.key == "events_count":
            return len(events)

        if self.entity_description.key == "last_event":
            if events:
                # Get timestamp from first event (most recent)
                first_event = events[0]
                timestamp = first_event.get("timestamp")

                if timestamp:
                    try:
                        # Convert Unix timestamp string to datetime
                        from datetime import timezone
                        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                    except (ValueError, TypeError, OSError):
                        pass
            return None

        # Legacy support
        if self.entity_description.key == "place_name":
            places = data.get("places", [])
            if places:
                return places[0].get("name")
            return None

        if self.entity_description.key == "access_control_name":
            access_controls = data.get("access_controls", [])
            if access_controls:
                return access_controls[0].get("name")
            return None

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        data = self.coordinator.data
        finances = data.get("finances", {})

        if self.entity_description.key == "balance":
            # Возвращаем всю информацию о платеже
            return {
                "balance": finances.get("balance"),
                "block_type": finances.get("blockType"),
                "amount_sum": finances.get("amountSum"),
                "target_date": finances.get("targetDate"),
                "payment_link": finances.get("paymentLink"),
                "days_to_block": finances.get("daysToBlock"),
                "days_to_warning": finances.get("daysToWarning"),
                "blocked": finances.get("blocked", False),
            }

        if self.entity_description.key == "block_status":
            return {
                "blocked": finances.get("blocked", False),
                "block_type": finances.get("blockType"),
            }

        # Events attributes
        events = data.get("events", [])

        if self.entity_description.key == "events_count":
            # Return list of event types/messages
            events_list = []

            # Маппинг известных типов событий на понятные названия
            event_type_map = {
                "accessControlCallAccepted": "Звонок принят",
                "accessControlCallRejected": "Звонок отклонен",
                "accessControlCallMissed": "Пропущенный звонок",
                "accessControlOpen": "Дверь открыта",
                "motionDetected": "Обнаружено движение",
                "videoRecorded": "Записано видео",
                "alarmTriggered": "Тревога",
            }

            for event in events[:10]:  # Last 10 events
                event_type = event.get("eventTypeName", "unknown")
                message = event.get("message", "")

                # Используем понятное название если знаем тип, иначе показываем как есть
                event_type_display = event_type_map.get(event_type, event_type)

                events_list.append({
                    "type": event_type,
                    "type_display": event_type_display,
                    "message": message,
                    "timestamp": event.get("timestamp"),
                    "id": event.get("id"),
                })

            return {
                "events": events_list,
                "total_count": len(events),
            }

        if self.entity_description.key == "last_event":
            if events:
                first_event = events[0]
                event_type = first_event.get("eventTypeName", "unknown")
                source = first_event.get("source", {})

                # Маппинг типов событий
                event_type_map = {
                    "accessControlCallAccepted": "Звонок принят",
                    "accessControlCallRejected": "Звонок отклонен",
                    "accessControlCallMissed": "Пропущенный звонок",
                    "accessControlOpen": "Дверь открыта",
                    "motionDetected": "Обнаружено движение",
                    "videoRecorded": "Записано видео",
                    "alarmTriggered": "Тревога",
                }

                event_type_display = event_type_map.get(event_type, event_type)

                return {
                    "type": event_type,
                    "type_display": event_type_display,
                    "message": first_event.get("message", ""),
                    "event_id": first_event.get("id"),
                    "place_id": first_event.get("placeId"),
                    "source_type": source.get("type", ""),
                    "source_id": source.get("id"),
                    "actions": first_event.get("actions", []),
                    "value": first_event.get("value"),
                }
            return None

        return None
