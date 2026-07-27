"""Access control presentation helpers for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import Any

type AccessControlTarget = tuple[str, str]


def valid_access_controls(access_controls: Any) -> list[dict[str, Any]]:
    """Return access controls that have an API identifier."""
    if not isinstance(access_controls, list):
        return []

    return [
        access_control
        for access_control in access_controls
        if isinstance(access_control, dict) and access_control.get("id") is not None
    ]


def access_control_target(
    access_control: dict[str, Any],
) -> AccessControlTarget | None:
    """Return the place/access-control identity used by FCM events."""
    place_id = access_control.get("place_id") or access_control.get("placeId")
    access_control_id = access_control.get("id")
    if place_id is None or access_control_id is None:
        return None
    return str(place_id), str(access_control_id)


def access_control_targets(access_controls: Any) -> set[AccessControlTarget]:
    """Return every valid FCM target discovered for this config entry."""
    return {
        target
        for access_control in valid_access_controls(access_controls)
        if (target := access_control_target(access_control)) is not None
    }


def selected_access_control(
    access_controls: Any,
    selected_access_control_id: str | int | None,
) -> dict[str, Any] | None:
    """Return the selected access control, defaulting to the first valid one."""
    controls = valid_access_controls(access_controls)
    if not controls:
        return None
    if selected_access_control_id is None:
        return controls[0]
    return next(
        (
            access_control
            for access_control in controls
            if str(access_control.get("id")) == str(selected_access_control_id)
        ),
        None,
    )


def selected_access_control_matches(
    access_controls: Any,
    selected_access_control_id: str | int | None,
    place_id: str | int | None,
    access_control_id: str | int | None,
) -> bool:
    """Return whether an FCM event belongs to the selected courier door."""
    selected = selected_access_control(access_controls, selected_access_control_id)
    target = access_control_target(selected) if selected else None
    return target == (str(place_id), str(access_control_id))


def multiple_access_controls(access_controls: Any) -> bool:
    """Return true when extra access-control UI is useful."""
    return len(valid_access_controls(access_controls)) > 1


def access_control_label(access_control: dict[str, Any], index: int) -> str:
    """Return a stable display label for an access control."""
    name = access_control.get("name") or "Door"
    return f"{index + 1}: {name}"
