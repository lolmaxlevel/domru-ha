"""Access control presentation helpers for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import Any


def valid_access_controls(access_controls: Any) -> list[dict[str, Any]]:
    """Return access controls that have an API identifier."""
    if not isinstance(access_controls, list):
        return []

    return [
        access_control
        for access_control in access_controls
        if isinstance(access_control, dict) and access_control.get("id") is not None
    ]


def multiple_access_controls(access_controls: Any) -> bool:
    """Return true when extra access-control UI is useful."""
    return len(valid_access_controls(access_controls)) > 1


def access_control_label(access_control: dict[str, Any], index: int) -> str:
    """Return a stable display label for an access control."""
    name = access_control.get("name") or "Door"
    return f"{index + 1}: {name}"
