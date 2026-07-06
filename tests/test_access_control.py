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
multiple_access_controls = access_control_module.multiple_access_controls
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


if __name__ == "__main__":
    unittest.main()
