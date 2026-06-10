"""Switch platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import SIGNAL_COURIER_AUTO_OPEN_UPDATE
from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

ENTITY_DESCRIPTIONS = (
    SwitchEntityDescription(
        key="courier_auto_open",
        name="Courier Auto Open",
        icon="mdi:truck-delivery",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    async_add_entities(
        DomruCourierAutoOpenSwitch(
            coordinator=entry.runtime_data.coordinator,
            entry=entry,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class DomruCourierAutoOpenSwitch(DomruEntity, SwitchEntity):
    """One-shot switch that opens the door on the next incoming call."""

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entry: DomruConfigEntry,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialize the courier auto-open switch."""
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    async def async_added_to_hass(self) -> None:
        """Register switch state update callbacks."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_COURIER_AUTO_OPEN_UPDATE,
                self._handle_courier_update,
            )
        )

    @callback
    def _handle_courier_update(self) -> None:
        """Write current switch state after one-shot mode changes."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return true when courier auto-open is armed."""
        return self._entry.runtime_data.courier_auto_open_enabled

    @property
    def available(self) -> bool:
        """Return true when incoming calls can trigger auto-open."""
        return self._entry.runtime_data.sip_client is not None

    async def async_turn_on(self, **kwargs: object) -> None:  # noqa: ARG002
        """Arm courier auto-open mode for the next incoming call."""
        self._entry.runtime_data.courier_auto_open_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:  # noqa: ARG002
        """Disarm courier auto-open mode."""
        data = self._entry.runtime_data
        data.courier_auto_open_enabled = False
        data.courier_auto_open_in_progress = False
        self.async_write_ha_state()
