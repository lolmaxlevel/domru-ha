"""Button platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory

from .entity import DomruEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator
    from .data import DomruConfigEntry

ENTITY_DESCRIPTIONS = (
    ButtonEntityDescription(
        key="open_door",
        name="Open Door",
        icon="mdi:door",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    entry: DomruConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    async_add_entities(
        DomruButtonEntity(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
            client=entry.runtime_data.client,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class DomruButtonEntity(DomruEntity, ButtonEntity):
    """Dom.ru button class."""

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
        client: DomruApiClient,
    ) -> None:
        """Initialize the button class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._client = client
        # Set unique ID for this button
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        if self.entity_description.key == "open_door":
            # Get place_id and access_control_id from coordinator data
            data = self.coordinator.data
            access_controls = data.get("access_controls", [])
            places = data.get("places", [])

            if not places or not access_controls:
                err_msg = "No places or access controls available"
                raise ValueError(err_msg)

            place_id = places[0].get("id")
            device_id = access_controls[0].get("id")

            await self._client.async_open_door(
                access_control_id=device_id, place_id=place_id
            )
            # Store the IDs for future use
            self._client.set_ids(place_id=place_id, access_control_id=device_id)

            await self.coordinator.async_request_refresh()
