"""Sensor platform for Dom.ru Smart Intercom."""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
    SensorEntityDescription(
        key="sip_status",
        name="Статус SIP",
        icon="mdi:phone-voip",
    ),
    SensorEntityDescription(
        key="call_status",
        name="Статус звонка",
        icon="mdi:phone-ring",
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
            entry=entry,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class DomruSensor(DomruEntity, SensorEntity):
    """Dom.ru Sensor class."""

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
        entry: DomruConfigEntry,
    ) -> None:
        """Initialize the sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._entry = entry
        # Set unique ID for this sensor
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return the native value of the sensor."""
        key = self.entity_description.key
        data = self.coordinator.data

        # Route to appropriate handler based on key
        handlers: dict[str, Any] = {
            "balance": self._get_balance,
            "amount_sum": self._get_amount_sum,
            "block_status": self._get_block_status,
            "target_date": self._get_target_date,
            "events_count": self._get_events_count,
            "last_event": self._get_last_event,
            "place_name": self._get_place_name,
            "access_control_name": self._get_access_control_name,
            "sip_status": self._get_sip_status,
            "call_status": self._get_call_status,
        }

        handler = handlers.get(key)
        if handler:
            return handler(data)
        return None

    def _get_balance(self, data: dict[str, Any]) -> str | float | None:
        """Get balance value."""
        finances = data.get("finances", {})
        return finances.get("balance")

    def _get_amount_sum(self, data: dict[str, Any]) -> str | float | None:
        """Get amount sum value."""
        finances = data.get("finances", {})
        return finances.get("amountSum")

    def _get_block_status(self, data: dict[str, Any]) -> str:
        """Get block status."""
        finances = data.get("finances", {})
        block_type = finances.get("blockType", "UNKNOWN")
        blocked = finances.get("blocked", False)
        if blocked:
            return "Заблокирован"
        if block_type == "NOT_BLOCKED":
            return "Не заблокирован"
        return block_type

    def _get_target_date(self, data: dict[str, Any]) -> datetime | None:
        """Get target date."""
        finances = data.get("finances", {})
        target_date = finances.get("targetDate")
        if target_date:
            # Parse ISO 8601 timestamp string to datetime object
            try:
                return dt_util.parse_datetime(target_date)
            except (ValueError, TypeError):
                return None
        return None

    def _get_events_count(self, data: dict[str, Any]) -> int:
        """Get events count."""
        events = data.get("events", [])
        return len(events)

    def _get_last_event(self, data: dict[str, Any]) -> datetime | None:
        """Get last event timestamp."""
        events = data.get("events", [])
        if events:
            # Get timestamp from first event (most recent)
            first_event = events[0]
            timestamp = first_event.get("timestamp")

            if timestamp:
                try:
                    # Convert Unix timestamp string to datetime
                    return datetime.fromtimestamp(int(timestamp), tz=UTC)
                except (ValueError, TypeError, OSError):
                    pass
        return None

    def _get_place_name(self, data: dict[str, Any]) -> str | None:
        """Get place name."""
        places = data.get("places", [])
        if places:
            return places[0].get("name")
        return None

    def _get_access_control_name(self, data: dict[str, Any]) -> str | None:
        """Get access control name."""
        access_controls = data.get("access_controls", [])
        if access_controls:
            return access_controls[0].get("name")
        return None

    def _get_sip_status(self, data: dict[str, Any]) -> str:  # noqa: ARG002
        """Get SIP status."""
        sip_client = self._entry.runtime_data.sip_client
        if not sip_client:
            return "Отключен"
        if sip_client.is_running:
            return "Подключен"
        return "Ошибка"

    def _get_call_status(self, data: dict[str, Any]) -> str:  # noqa: ARG002
        """Get call status."""
        sip_client = self._entry.runtime_data.sip_client
        if not sip_client:
            return "idle"

        status = sip_client.call_status

        # Translate to Russian
        status_map = {
            "idle": "Нет звонка",
            "ringing": "Звонок",
            "answered": "Отвечен",
        }

        return status_map.get(status, status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # noqa: PLR0911
        """Return extra state attributes."""
        data = self.coordinator.data
        finances = data.get("finances", {})

        # Call status attributes
        if self.entity_description.key == "call_status":
            sip_client = self._entry.runtime_data.sip_client
            if not sip_client:
                return None

            call_info = sip_client.get_active_call_info()
            if not call_info:
                return None

            # Parse From header to extract caller info
            from_header = call_info.get("from", "")
            caller_match = re.search(r'"([^"]+)"', from_header)
            caller_name = caller_match.group(1) if caller_match else "Unknown"

            return {
                "caller": caller_name,
                "call_id": call_info.get("call_id", ""),
                "from_header": from_header,
            }

        # Balance attributes
        if self.entity_description.key == "balance":
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

                events_list.append(
                    {
                        "type": event_type,
                        "type_display": event_type_display,
                        "message": message,
                        "timestamp": event.get("timestamp"),
                        "id": event.get("id"),
                    }
                )

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

        # SIP status attributes
        if self.entity_description.key == "sip_status":
            sip_client = self._entry.runtime_data.sip_client
            if sip_client:
                return {
                    "running": sip_client.is_running,
                    "local_ip": sip_client.local_ip,
                    "local_port": sip_client.local_port,
                    "realm": sip_client.realm,
                    "username": sip_client.username,
                    "expires": sip_client.expires,
                    "cseq": sip_client.cseq,
                }
            return {"running": False}

        return None
