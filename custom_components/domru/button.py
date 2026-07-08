"""Button platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .access_control import access_control_label, valid_access_controls
from .const import SIGNAL_CALL_STATUS_UPDATE
from .door import async_open_door
from .entity import DomruEntity
from .sip_entities import dismiss_call

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry
    from .sip import DomruSipClient

ENTITY_DESCRIPTIONS = (
    ButtonEntityDescription(
        key="open_door",
        name="Open Door",
        icon="mdi:door",
    ),
    ButtonEntityDescription(
        key="dismiss_call",
        name="Dismiss Call",
        icon="mdi:phone-off",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    access_controls = valid_access_controls(
        entry.runtime_data.coordinator.data.get("access_controls", [])
    )
    async_add_entities(
        [
            DomruButtonEntity(
                hass=hass,
                coordinator=entry.runtime_data.coordinator,
                entity_description=entity_description,
                client=entry.runtime_data.client,
                sip_client=entry.runtime_data.sip_client,
            )
            for entity_description in ENTITY_DESCRIPTIONS
        ]
        + [
            DomruButtonEntity(
                hass=hass,
                coordinator=entry.runtime_data.coordinator,
                entity_description=_access_control_button_description(
                    access_control,
                    index,
                ),
                client=entry.runtime_data.client,
                sip_client=entry.runtime_data.sip_client,
                access_control_id=access_control["id"],
            )
            for index, access_control in enumerate(access_controls)
            if len(access_controls) > 1
        ]
    )


def _access_control_button_description(
    access_control: dict,
    index: int,
) -> ButtonEntityDescription:
    """Return a button description for an access control device."""
    access_control_id = access_control["id"]
    name = access_control_label(access_control, index)
    return ButtonEntityDescription(
        key=f"open_door_{access_control_id}",
        name=f"Open {name}",
        icon="mdi:door-open",
    )


class DomruButtonEntity(DomruEntity, ButtonEntity):
    """Dom.ru button class."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DomruDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
        client: DomruApiClient,
        sip_client: DomruSipClient | None,
        access_control_id: str | int | None = None,
    ) -> None:
        """Initialize the button class."""
        super().__init__(coordinator)
        self._hass = hass
        self.entity_description = entity_description
        self._client = client
        self._sip_client = sip_client
        self._access_control_id = access_control_id
        # Set unique ID for this button
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        if self.entity_description.key.startswith("open_door"):
            if self._sip_client:
                self._sip_client.answer_and_hangup()
                async_dispatcher_send(self._hass, SIGNAL_CALL_STATUS_UPDATE)

            await async_open_door(
                self._client,
                self.coordinator,
                access_control_id=self._access_control_id,
            )
            await self.coordinator.async_request_refresh()

        elif self.entity_description.key == "dismiss_call":
            dismiss_call(self._sip_client)
            async_dispatcher_send(self._hass, SIGNAL_CALL_STATUS_UPDATE)
