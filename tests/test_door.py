# ruff: noqa: D102,D107,EM102,TRY003,PT009
"""Tests for shared Dom.ru door control helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

DOOR_MODULE_PATH = Path("custom_components/domru/door.py")
spec = importlib.util.spec_from_file_location("domru_door_for_tests", DOOR_MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {DOOR_MODULE_PATH}")
door_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = door_module
spec.loader.exec_module(door_module)

async_open_first_door = door_module.async_open_first_door


class FakeClient:
    """Capture door open calls."""

    def __init__(self) -> None:
        self.ids: tuple[str | int | None, str | int | None] = (None, None)
        self.opened_with: tuple[str | int | None, str | int | None] | None = None

    def set_ids(
        self,
        place_id: str | int | None = None,
        access_control_id: str | int | None = None,
    ) -> None:
        self.ids = (place_id, access_control_id)

    async def async_open_door(
        self,
        access_control_id: str | int | None = None,
        place_id: str | int | None = None,
    ) -> dict[str, str]:
        self.opened_with = (access_control_id, place_id)
        return {"result": "ok"}


class FakeCoordinator:
    """Minimal coordinator with API data."""

    def __init__(self, data: dict) -> None:
        self.data = data


class DoorHelperTests(unittest.TestCase):
    """Door helper behavior."""

    def test_open_first_door_uses_first_place_and_access_control(self) -> None:
        client = FakeClient()
        coordinator = FakeCoordinator(
            {
                "places": [{"id": "place-1"}],
                "access_controls": [{"id": "door-1"}],
            }
        )

        result = asyncio.run(async_open_first_door(client, coordinator))

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(client.ids, ("place-1", "door-1"))
        self.assertEqual(client.opened_with, ("door-1", "place-1"))


if __name__ == "__main__":
    unittest.main()
