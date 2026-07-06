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


def _id_at_index(items: Any, index: int, key: str = "id") -> str | int | None:
    """Return an identifier by zero-based index from API data."""
    if not isinstance(items, list) or index < 0 or index >= len(items):
        return None
    item = items[index]
    if not isinstance(item, dict):
        return None
    return item.get(key)


async def async_open_door(
    client: DomruApiClient,
    coordinator: DomruDataUpdateCoordinator,
    *,
    access_control_id: str | int | None = None,
    door_index: int | None = None,
) -> dict[str, Any]:
    """Open an access control device by ID, index, or the first available door."""
    if access_control_id is not None and door_index is not None:
        msg = "Use either access_control_id or door_index, not both"
        raise ValueError(msg)

    data = coordinator.data or {}
    place_id = _first_id(data.get("places", []))

    selected_access_control_id = access_control_id
    if selected_access_control_id is None:
        access_controls = data.get("access_controls", [])
        selected_access_control_id = (
            _first_id(access_controls)
            if door_index is None
            else _id_at_index(access_controls, door_index)
        )

    if door_index is not None and selected_access_control_id is None:
        msg = f"No access control found for door_index={door_index}"
        raise ValueError(msg)

    if place_id is not None and selected_access_control_id is not None:
        client.set_ids(
            place_id=place_id,
            access_control_id=selected_access_control_id,
        )

    return await client.async_open_door(
        access_control_id=selected_access_control_id,
        place_id=place_id,
    )


async def async_open_first_door(
    client: DomruApiClient,
    coordinator: DomruDataUpdateCoordinator,
) -> dict[str, Any]:
    """Open the first available access control device."""
    return await async_open_door(client, coordinator)
