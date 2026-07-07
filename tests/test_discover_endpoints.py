# ruff: noqa: D102,EM102,PT009,S603,TRY003
"""Tests for endpoint discovery helpers."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
import unittest
from pathlib import Path

if "async_timeout" not in sys.modules:
    async_timeout_module = types.ModuleType("async_timeout")

    class _Timeout:
        def __init__(self, _seconds: int) -> None:
            pass

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    async_timeout_module.timeout = _Timeout
    sys.modules["async_timeout"] = async_timeout_module

if "custom_components" not in sys.modules:
    custom_components_stub = types.ModuleType("custom_components")
    custom_components_stub.__path__ = [str(Path("custom_components"))]
    sys.modules["custom_components"] = custom_components_stub

if "custom_components.domru" not in sys.modules:
    domru_stub = types.ModuleType("custom_components.domru")
    domru_stub.__path__ = [str(Path("custom_components/domru"))]
    sys.modules["custom_components.domru"] = domru_stub

DISCOVER_MODULE_PATH = Path("dev/discover_endpoints.py")
spec = importlib.util.spec_from_file_location(
    "domru_discover_endpoints_for_tests",
    DISCOVER_MODULE_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {DISCOVER_MODULE_PATH}")
discover_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discover_module
spec.loader.exec_module(discover_module)

EndpointProbe = discover_module.EndpointProbe
endpoint_probes = discover_module.endpoint_probes
render_probe = discover_module.render_probe
response_shape = discover_module.response_shape


class DiscoverEndpointsTests(unittest.TestCase):
    """Endpoint discovery helper behavior."""

    def test_render_probe_returns_none_when_variable_missing(self) -> None:
        probe = EndpointProbe("v1", "GET", "rest/v1/places/{place_id}", "place")

        self.assertIsNone(render_probe(probe, {}))

    def test_render_probe_formats_path_and_body(self) -> None:
        probe = EndpointProbe(
            "v1",
            "POST",
            "rest/v1/events/search",
            "events",
            body={"placeIds": ["{place_id}"]},
        )

        rendered = render_probe(probe, {"place_id": 5802693})

        self.assertEqual(
            rendered,
            ("rest/v1/events/search", {"placeIds": ["5802693"]}),
        )

    def test_endpoint_probes_skip_side_effects_by_default(self) -> None:
        probes = endpoint_probes()

        self.assertTrue(probes)
        self.assertFalse(any(probe.side_effect for probe in probes))

    def test_endpoint_probes_can_include_side_effects(self) -> None:
        probes = endpoint_probes(include_actions=True)

        self.assertTrue(any(probe.side_effect for probe in probes))

    def test_response_shape_summarizes_nested_data(self) -> None:
        shape = response_shape({"data": [{"id": 1, "name": "Door"}]})

        self.assertEqual(
            shape,
            {"data": [{"id": "int", "name": "str"}, "... 1 item(s) total"]},
        )

    def test_script_help_does_not_require_homeassistant(self) -> None:
        result = subprocess.run(
            [sys.executable, str(DISCOVER_MODULE_PATH), "--help"],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--include-actions", result.stdout)


if __name__ == "__main__":
    unittest.main()
