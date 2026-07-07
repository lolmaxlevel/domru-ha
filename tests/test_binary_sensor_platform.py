# ruff: noqa: D102,PT009
"""Tests for removed binary sensor platform."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

BINARY_SENSOR_MODULE_PATH = Path("custom_components/domru/binary_sensor.py")
INIT_MODULE_PATH = Path("custom_components/domru/__init__.py")


class BinarySensorPlatformTests(unittest.TestCase):
    """Binary sensor platform registration behavior."""

    def test_binary_sensor_platform_is_not_forwarded(self) -> None:
        init_source = INIT_MODULE_PATH.read_text(encoding="utf-8")
        platforms_match = re.search(
            r"PLATFORMS: list\[Platform\] = \[(.*?)\]",
            init_source,
            re.DOTALL,
        )

        self.assertIsNotNone(platforms_match)
        self.assertNotIn("Platform.BINARY_SENSOR", platforms_match.group(1))

    def test_removed_binary_sensor_file_has_no_entity_descriptions(self) -> None:
        binary_sensor_source = BINARY_SENSOR_MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn("ENTITY_DESCRIPTIONS = ()", binary_sensor_source)


if __name__ == "__main__":
    unittest.main()
