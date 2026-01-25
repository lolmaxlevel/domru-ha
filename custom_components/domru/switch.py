"""Switch platform for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

# Future: switches for door lock states, etc.

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import DomruConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: DomruConfigEntry,  # noqa: ARG001 Unused function argument: `entry`
    async_add_entities: AddEntitiesCallback,  # noqa: ARG001 Unused function argument: `async_add_entities`
) -> None:
    """Set up the switch platform."""
    # Currently no switches are implemented
    # This can be extended in the future with door lock states
    pass
