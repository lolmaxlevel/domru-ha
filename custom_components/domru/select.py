"""Select platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .access_control import access_control_label, multiple_access_controls
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
    """Set up the select platform."""
    async_add_entities(
        [
            DomruCourierAccessControlSelect(
                coordinator=entry.runtime_data.coordinator,
                entry=entry,
            )
        ]
    )


class DomruCourierAccessControlSelect(DomruEntity, SelectEntity):
    """Select the access control used by courier auto-open."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:door-open"
    _attr_name = "Courier Auto Open Door"

    def __init__(
        self,
        coordinator: DomruDataUpdateCoordinator,
        entry: DomruConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_entity_registry_enabled_default = multiple_access_controls(
            coordinator.data.get("access_controls", [])
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_courier_auto_open_access_control"
        )

    @property
    def available(self) -> bool:
        """Return true when there is more than one access control to choose."""
        return super().available and multiple_access_controls(
            self.coordinator.data.get("access_controls", [])
        )

    @property
    def options(self) -> list[str]:
        """Return available access controls."""
        return [option for option, _ in self._option_pairs()]

    @property
    def current_option(self) -> str | None:
        """Return the selected access control."""
        pairs = self._option_pairs()
        if not pairs:
            return None

        selected_id = self._entry.runtime_data.courier_auto_open_access_control_id
        if selected_id is None:
            return pairs[0][0]

        for option, access_control_id in pairs:
            if str(access_control_id) == str(selected_id):
                return option

        return pairs[0][0]

    async def async_select_option(self, option: str) -> None:
        """Select an access control for courier auto-open."""
        for label, access_control_id in self._option_pairs():
            if label == option:
                self._entry.runtime_data.courier_auto_open_access_control_id = (
                    access_control_id
                )
                self.async_write_ha_state()
                return

        msg = f"Unknown access control option: {option}"
        raise ValueError(msg)

    def _option_pairs(self) -> list[tuple[str, str | int]]:
        """Return display labels and access control IDs."""
        access_controls = self.coordinator.data.get("access_controls", [])
        if not isinstance(access_controls, list):
            return []

        pairs: list[tuple[str, str | int]] = []
        for index, access_control in enumerate(access_controls):
            if not isinstance(access_control, dict):
                continue

            access_control_id = access_control.get("id")
            if access_control_id is None:
                continue

            name = access_control_label(access_control, index)
            pairs.append((name, access_control_id))

        return pairs
