"""Sensor platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

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

    @property
    def native_value(self) -> str | float | None:
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
                # Return as-is, Home Assistant will parse it
                return target_date
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
            return {
                "payment_link": finances.get("paymentLink"),
                "days_to_block": finances.get("daysToBlock"),
                "days_to_warning": finances.get("daysToWarning"),
            }

        if self.entity_description.key == "block_status":
            return {
                "blocked": finances.get("blocked", False),
                "block_type": finances.get("blockType"),
            }

        return None
