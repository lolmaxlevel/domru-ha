"""Door control helpers for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import DomruApiClient
    from .coordinator import DomruDataUpdateCoordinator


def _first_id(items: Any, key: str = "id") -> str | int | None:
    """Return the first non-empty identifier from API data."""
    if not isinstance(items, list) or not items:
        return None
    first_item = items[0]
    if not isinstance(first_item, dict):
        return None
    return first_item.get(key)


async def async_open_first_door(
    client: DomruApiClient,
    coordinator: DomruDataUpdateCoordinator,
) -> dict[str, Any]:
    """Open the first available access control device."""
    data = coordinator.data or {}
    place_id = _first_id(data.get("places", []))
    access_control_id = _first_id(data.get("access_controls", []))

    if place_id is not None and access_control_id is not None:
        client.set_ids(
            place_id=place_id,
            access_control_id=access_control_id,
        )

    return await client.async_open_door(
        access_control_id=access_control_id,
        place_id=place_id,
    )
