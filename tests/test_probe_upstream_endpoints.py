# ruff: noqa: D102,EM102,PT009,S603,TRY003
"""Tests for upstream endpoint probe helpers."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
import unittest
from pathlib import Path

if "custom_components" not in sys.modules:
    custom_components_stub = types.ModuleType("custom_components")
    custom_components_stub.__path__ = [str(Path("custom_components"))]
    sys.modules["custom_components"] = custom_components_stub

if "custom_components.domru" not in sys.modules:
    domru_stub = types.ModuleType("custom_components.domru")
    domru_stub.__path__ = [str(Path("custom_components/domru"))]
    sys.modules["custom_components.domru"] = domru_stub

PROBE_MODULE_PATH = Path("dev/probe_upstream_endpoints.py")
spec = importlib.util.spec_from_file_location(
    "domru_probe_upstream_endpoints_for_tests",
    PROBE_MODULE_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {PROBE_MODULE_PATH}")
probe_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe_module
spec.loader.exec_module(probe_module)

camera_id_from_sources = probe_module.camera_id_from_sources


class ProbeUpstreamEndpointsTests(unittest.TestCase):
    """Probe helper behavior."""

    def test_camera_id_falls_back_to_access_control_external_camera_id(self) -> None:
        camera_id = camera_id_from_sources(
            cameras=[],
            access_controls=[{"externalCameraId": "18616643"}],
        )

        self.assertEqual(camera_id, "18616643")

    def test_script_help_does_not_require_homeassistant(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROBE_MODULE_PATH), "--help"],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--archive-ts", result.stdout)


if __name__ == "__main__":
    unittest.main()
