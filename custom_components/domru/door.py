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


def _first_item(items: Any) -> dict[str, Any] | None:
    """Return the first dict item from API data."""
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def _id_at_index(items: Any, index: int, key: str = "id") -> str | int | None:
    """Return an identifier by zero-based index from API data."""
    if not isinstance(items, list) or index < 0 or index >= len(items):
        return None
    item = items[index]
    if not isinstance(item, dict):
        return None
    return item.get(key)


def _item_at_index(items: Any, index: int) -> dict[str, Any] | None:
    """Return an item by zero-based index from API data."""
    if not isinstance(items, list) or index < 0 or index >= len(items):
        return None
    item = items[index]
    return item if isinstance(item, dict) else None


def _item_by_id(items: Any, item_id: str | int) -> dict[str, Any] | None:
    """Return the item with the matching ID."""
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == str(item_id):
            return item
    return None


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
    places = data.get("places", [])
    access_controls = data.get("access_controls", [])

    selected_access_control_id = access_control_id
    selected_access_control = None
    if selected_access_control_id is None:
        selected_access_control = (
            _first_item(access_controls)
            if door_index is None
            else _item_at_index(access_controls, door_index)
        )
        if selected_access_control is not None:
            selected_access_control_id = selected_access_control.get("id")
    else:
        selected_access_control = _item_by_id(
            access_controls,
            selected_access_control_id,
        )

    if door_index is not None and selected_access_control_id is None:
        msg = f"No access control found for door_index={door_index}"
        raise ValueError(msg)

    place_id = (
        selected_access_control.get("place_id")
        or selected_access_control.get("placeId")
        if selected_access_control
        else None
    )
    if place_id is None:
        place_id = _first_id(places)

    if place_id is not None and selected_access_control_id is not None:
        client.set_ids(
            place_id=place_id,
            access_control_id=selected_access_control_id,
        )

    return await client.async_open_door(
        access_control_id=selected_access_control_id,
        place_id=place_id,
        access_control=selected_access_control,
    )


async def async_open_first_door(
    client: DomruApiClient,
    coordinator: DomruDataUpdateCoordinator,
) -> dict[str, Any]:
    """Open the first available access control device."""
    return await async_open_door(client, coordinator)
