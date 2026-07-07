"""Camera source helpers for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import Any


def _value(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present value from API data."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def camera_sources_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return camera entity source definitions from coordinator data."""
    access_control_sources = _access_control_camera_sources(
        data.get("access_controls", [])
    )
    access_control_camera_ids = {
        str(source["camera_id"])
        for source in access_control_sources
        if source.get("camera_id") is not None
    }
    sources = _camera_sources(
        data.get("cameras", []),
        exclude_camera_ids=access_control_camera_ids,
    )
    return sources + access_control_sources


def _camera_sources(
    cameras: Any,
    *,
    exclude_camera_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return regular camera source definitions."""
    if not isinstance(cameras, list):
        return []

    excluded = exclude_camera_ids or set()
    sources: list[dict[str, Any]] = []
    for camera in cameras:
        if not isinstance(camera, dict):
            continue

        camera_id = _value(camera, "ID", "id")
        if camera_id is None:
            continue
        if str(camera_id) in excluded:
            continue

        sources.append(
            {
                "unique_id": f"camera_{camera_id}",
                "camera_id": camera_id,
                "name": _value(camera, "Name", "name") or f"Camera {camera_id}",
                "data": camera,
                "has_sound": camera.get("IsSound") == 1,
                "snapshot": "forpost",
            }
        )

    return sources


def _access_control_camera_sources(access_controls: Any) -> list[dict[str, Any]]:
    """Return access-control snapshot camera source definitions."""
    if not isinstance(access_controls, list):
        return []

    sources: list[dict[str, Any]] = []
    for access_control in access_controls:
        if not isinstance(access_control, dict):
            continue

        access_control_id = access_control.get("id")
        place_id = _value(access_control, "place_id", "placeId")
        if access_control_id is None or place_id is None:
            continue
        if not access_control.get("previewAvailable", access_control.get("allowVideo")):
            continue

        camera_id = _value(access_control, "externalCameraId", "external_camera_id")
        name = access_control.get("name") or f"Access control {access_control_id}"
        unique_id = (
            f"camera_{camera_id}"
            if camera_id is not None
            else f"access_control_{access_control_id}"
        )
        sources.append(
            {
                "unique_id": unique_id,
                "camera_id": camera_id,
                "name": name,
                "data": access_control,
                "has_sound": False,
                "snapshot": "access_control",
                "place_id": place_id,
                "access_control_id": access_control_id,
            }
        )

    return sources
