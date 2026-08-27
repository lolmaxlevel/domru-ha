# ruff: noqa: D102,EM102,PT009,TRY003
"""Tests for Dom.ru camera source helpers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

CAMERA_SOURCE_MODULE_PATH = Path("custom_components/domru/camera_source.py")
spec = importlib.util.spec_from_file_location(
    "domru_camera_source_for_tests",
    CAMERA_SOURCE_MODULE_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {CAMERA_SOURCE_MODULE_PATH}")
camera_source_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = camera_source_module
spec.loader.exec_module(camera_source_module)

camera_sources_from_data = camera_source_module.camera_sources_from_data


class CameraSourceTests(unittest.TestCase):
    """Camera source helper behavior."""

    def test_access_control_with_preview_creates_snapshot_camera_source(self) -> None:
        sources = camera_sources_from_data(
            {
                "cameras": [],
                "access_controls": [
                    {
                        "id": 5676,
                        "name": "Королева Пр-Кт 19  (п. 10)",
                        "place_id": 5802693,
                        "previewAvailable": True,
                        "externalCameraId": "18616643",
                    }
                ],
            }
        )

        self.assertEqual(
            sources,
            [
                {
                    "unique_id": "camera_18616643",
                    "camera_id": "18616643",
                    "name": "Королева Пр-Кт 19  (п. 10)",
                    "data": {
                        "id": 5676,
                        "name": "Королева Пр-Кт 19  (п. 10)",
                        "place_id": 5802693,
                        "previewAvailable": True,
                        "externalCameraId": "18616643",
                    },
                    "has_sound": False,
                    "snapshot": "access_control",
                    "place_id": 5802693,
                    "access_control_id": 5676,
                }
            ],
        )

    def test_regular_camera_source_uses_existing_camera_metadata(self) -> None:
        sources = camera_sources_from_data(
            {
                "cameras": [
                    {
                        "ID": 123,
                        "Name": "Yard",
                        "IsSound": 1,
                    }
                ],
                "access_controls": [],
            }
        )

        self.assertEqual(sources[0]["unique_id"], "camera_123")
        self.assertEqual(sources[0]["camera_id"], 123)
        self.assertEqual(sources[0]["name"], "Yard")
        self.assertTrue(sources[0]["has_sound"])
        self.assertEqual(sources[0]["snapshot"], "forpost")

    def test_access_control_snapshot_replaces_duplicate_forpost_camera(self) -> None:
        sources = camera_sources_from_data(
            {
                "cameras": [
                    {
                        "ID": 18616643,
                        "Name": "Forpost duplicate",
                        "IsSound": 1,
                    }
                ],
                "access_controls": [
                    {
                        "id": 5676,
                        "name": "Intercom",
                        "place_id": 5802693,
                        "previewAvailable": True,
                        "externalCameraId": "18616643",
                    }
                ],
            }
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["unique_id"], "camera_18616643")
        self.assertEqual(sources[0]["snapshot"], "access_control")
        self.assertEqual(sources[0]["access_control_id"], 5676)
        self.assertTrue(sources[0]["has_sound"])
        self.assertEqual(sources[0]["data"]["IsSound"], 1)


if __name__ == "__main__":
    unittest.main()
