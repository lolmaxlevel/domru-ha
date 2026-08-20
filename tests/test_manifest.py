# ruff: noqa: D101,D102,PT009
"""Tests for the integration manifest contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


class ManifestTests(unittest.TestCase):
    def test_go2rtc_is_an_optional_after_dependency(self) -> None:
        manifest = json.loads(
            Path("custom_components/domru/manifest.json").read_text(encoding="utf-8")
        )

        self.assertIn("stream", manifest["dependencies"])
        self.assertIn("go2rtc", manifest.get("after_dependencies", []))


if __name__ == "__main__":
    unittest.main()
