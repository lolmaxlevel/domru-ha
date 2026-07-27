# ruff: noqa: D102,EM102,TRY003,PT009
"""Tests for access control presentation helpers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ACCESS_CONTROL_MODULE_PATH = Path("custom_components/domru/access_control.py")
spec = importlib.util.spec_from_file_location(
    "domru_access_control_for_tests",
    ACCESS_CONTROL_MODULE_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {ACCESS_CONTROL_MODULE_PATH}")
access_control_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = access_control_module
spec.loader.exec_module(access_control_module)

access_control_label = access_control_module.access_control_label
access_control_targets = access_control_module.access_control_targets
multiple_access_controls = access_control_module.multiple_access_controls
selected_access_control_matches = access_control_module.selected_access_control_matches
valid_access_controls = access_control_module.valid_access_controls


class AccessControlHelperTests(unittest.TestCase):
    """Access control helper behavior."""

    def test_valid_access_controls_ignores_malformed_entries(self) -> None:
        controls = valid_access_controls(
            [
                {"id": "door-1", "name": "Gate"},
                {"name": "No ID"},
                "bad",
                {"id": "door-2"},
            ]
        )

        self.assertEqual(
            controls,
            [{"id": "door-1", "name": "Gate"}, {"id": "door-2"}],
        )

    def test_multiple_access_controls_requires_two_valid_ids(self) -> None:
        self.assertFalse(multiple_access_controls([{"id": "door-1"}]))
        self.assertTrue(multiple_access_controls([{"id": "door-1"}, {"id": "door-2"}]))

    def test_access_control_label_uses_index_and_name(self) -> None:
        self.assertEqual(
            access_control_label({"id": "door-1", "name": "Gate"}, 0),
            "1: Gate",
        )
        self.assertEqual(access_control_label({"id": "door-2"}, 1), "2: Door")

    def test_access_control_targets_include_every_discovered_door(self) -> None:
        self.assertEqual(
            access_control_targets(
                [
                    {"id": "door-1", "place_id": "place-1"},
                    {"id": "door-2", "placeId": "place-1"},
                    {"id": "door-3", "place_id": "place-2"},
                ]
            ),
            {
                ("place-1", "door-1"),
                ("place-1", "door-2"),
                ("place-2", "door-3"),
            },
        )

    def test_selected_courier_door_matches_only_its_fcm_target(self) -> None:
        controls = [
            {"id": "door-1", "place_id": "place-1"},
            {"id": "door-2", "place_id": "place-1"},
        ]

        self.assertTrue(
            selected_access_control_matches(
                controls,
                "door-2",
                "place-1",
                "door-2",
            )
        )
        self.assertFalse(
            selected_access_control_matches(
                controls,
                "door-2",
                "place-1",
                "door-1",
            )
        )

    def test_default_courier_door_is_the_first_valid_control(self) -> None:
        controls = [
            {"id": "door-1", "place_id": "place-1"},
            {"id": "door-2", "place_id": "place-1"},
        ]

        self.assertTrue(
            selected_access_control_matches(
                controls,
                None,
                "place-1",
                "door-1",
            )
        )


if __name__ == "__main__":
    unittest.main()
