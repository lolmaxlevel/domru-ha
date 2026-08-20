# ruff: noqa: D101,D102,PT009
"""Tests for optional camera audio transport setup."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

MEDIA_MODULE_PATH = Path("custom_components/domru/media.py")


def _load_media_module(
    *,
    setup_result: bool = True,
    setup_exception: Exception | None = None,
    setup_calls: list[tuple[str, dict]] | None = None,
) -> types.ModuleType:
    homeassistant = types.ModuleType("homeassistant")
    setup = types.ModuleType("homeassistant.setup")

    async def async_setup_component(
        _hass: object,
        domain: str,
        config: dict,
    ) -> bool:
        if setup_calls is not None:
            setup_calls.append((domain, config))
        if setup_exception is not None:
            raise setup_exception
        return setup_result

    setup.async_setup_component = async_setup_component
    module_names = ("homeassistant", "homeassistant.setup")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.setup": setup,
        }
    )

    try:
        spec = importlib.util.spec_from_file_location(
            "domru_media_for_tests", MEDIA_MODULE_PATH
        )
        if spec is None or spec.loader is None:
            message = f"Cannot load {MEDIA_MODULE_PATH}"
            raise RuntimeError(message)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("domru_media_for_tests", None)
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class MediaTests(unittest.TestCase):
    def test_go2rtc_setup_requests_managed_configuration(self) -> None:
        setup_calls: list[tuple[str, dict]] = []
        media = _load_media_module(setup_calls=setup_calls)

        asyncio.run(media.async_setup_camera_audio(object()))

        self.assertEqual(setup_calls, [("go2rtc", {"go2rtc": {}})])

    def test_go2rtc_setup_accepts_available_component(self) -> None:
        self.assertTrue(MEDIA_MODULE_PATH.exists())
        if not MEDIA_MODULE_PATH.exists():
            return
        media = _load_media_module()

        asyncio.run(media.async_setup_camera_audio(object()))

    def test_go2rtc_setup_preserves_video_fallback_when_unavailable(self) -> None:
        self.assertTrue(MEDIA_MODULE_PATH.exists())
        if not MEDIA_MODULE_PATH.exists():
            return
        media = _load_media_module(setup_result=False)

        with self.assertLogs("domru_media_for_tests", level="WARNING"):
            asyncio.run(media.async_setup_camera_audio(object()))

    def test_go2rtc_setup_preserves_video_fallback_on_setup_error(self) -> None:
        self.assertTrue(MEDIA_MODULE_PATH.exists())
        if not MEDIA_MODULE_PATH.exists():
            return
        media = _load_media_module(setup_exception=RuntimeError("setup failed"))

        with self.assertLogs("domru_media_for_tests", level="WARNING"):
            asyncio.run(media.async_setup_camera_audio(object()))


if __name__ == "__main__":
    unittest.main()
