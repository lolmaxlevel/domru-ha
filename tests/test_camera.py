# ruff: noqa: D101,D102,D107,PT009
"""Tests for the Home Assistant camera entity wrapper."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

CAMERA_MODULE_PATH = Path("custom_components/domru/camera.py")


class FakeCameraEntityFeature:
    STREAM = 2


class FakeCamera:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._webrtc_provider = None
        self.stream_options: dict[str, str | bool | float] = {}

    async def async_create_stream(self) -> str:
        return "unsafe_hls_stream"

    async def async_refresh_providers(self, *, write_state: bool = True) -> None:
        _ = write_state
        self._webrtc_provider = getattr(self, "_next_webrtc_provider", None)

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: object
    ) -> None:
        if self._webrtc_provider:
            await self._webrtc_provider.async_on_webrtc_candidate(session_id, candidate)

    def set_next_webrtc_provider(self, provider: object) -> None:
        self._next_webrtc_provider = provider


class FakeWebRTCProvider:
    domain = "go2rtc"

    def __init__(
        self,
        *,
        url: str = "http://localhost:11984/",
        stream_error: Exception | None = None,
    ) -> None:
        self._sessions: dict[str, object] = {}
        self.received_candidates: list[tuple[str, object]] = []
        self._url = url
        self._rest_client = FakeGo2RtcRestClient(stream_error)

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: object
    ) -> None:
        if session_id in self._sessions:
            self.received_candidates.append((session_id, candidate))

    def open_session(self, session_id: str) -> None:
        self._sessions[session_id] = object()

    @property
    def added_streams(self) -> list[tuple[str, str]]:
        return self._rest_client.streams.added


class FakeGo2RtcStreams:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.added: list[tuple[str, str]] = []

    async def add(self, name: str, source: str) -> None:
        if self.error is not None:
            raise self.error
        self.added.append((name, source))


class FakeGo2RtcRestClient:
    def __init__(self, stream_error: Exception | None = None) -> None:
        self.streams = FakeGo2RtcStreams(stream_error)


class FakeDomruEntity:
    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator


class FakeConfigEntry:
    def __init__(self, entry_id: str = "entry-1") -> None:
        self.entry_id = entry_id
        self.options: dict[str, Any] = {}


class FakeCoordinator:
    def __init__(self, entry_id: str = "entry-1") -> None:
        self.config_entry = FakeConfigEntry(entry_id)


class FakeClient:
    def __init__(self, stream_url: str) -> None:
        self.stream_url = stream_url

    async def async_get_camera_stream_url(self, _camera_id: int) -> str:
        return self.stream_url


def _load_camera_module() -> types.ModuleType:
    package_name = "domru_camera_for_tests"
    module_names = (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.camera",
        package_name,
        f"{package_name}.camera_source",
        f"{package_name}.entity",
        f"{package_name}.camera",
    )
    previous_modules = {name: sys.modules.get(name) for name in module_names}

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    camera_component = types.ModuleType("homeassistant.components.camera")
    camera_component.Camera = FakeCamera
    camera_component.CameraEntityFeature = FakeCameraEntityFeature

    package = types.ModuleType(package_name)
    package.__path__ = []
    camera_source = types.ModuleType(f"{package_name}.camera_source")
    camera_source.camera_sources_from_data = lambda _data: []
    entity = types.ModuleType(f"{package_name}.entity")
    entity.DomruEntity = FakeDomruEntity

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.camera": camera_component,
            package_name: package,
            f"{package_name}.camera_source": camera_source,
            f"{package_name}.entity": entity,
        }
    )

    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.camera",
            CAMERA_MODULE_PATH,
        )
        if spec is None or spec.loader is None:
            message = f"Cannot load {CAMERA_MODULE_PATH}"
            raise RuntimeError(message)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


camera_module = _load_camera_module()
DomruCamera = camera_module.DomruCamera


class CameraTests(unittest.TestCase):
    def test_keeps_home_assistant_hls_video_fallback(self) -> None:
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=object(),
            camera_id=123,
            camera_name="Yard",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )

        self.assertEqual(
            asyncio.run(camera.async_create_stream()),
            "unsafe_hls_stream",
        )

    def test_initializes_home_assistant_camera_state(self) -> None:
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=object(),
            camera_id=123,
            camera_name="Yard",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )

        self.assertTrue(hasattr(camera, "_cache"))
        self.assertTrue(hasattr(camera, "_webrtc_provider"))

    def test_https_flv_does_not_receive_rtsp_stream_options(self) -> None:
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=object(),
            camera_id=123,
            camera_name="Yard",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )

        self.assertEqual(camera.stream_options, {})

    def test_has_sound_attribute_uses_resolved_audio_capability(self) -> None:
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=object(),
            camera_id=123,
            camera_name="Intercom",
            camera_data={"id": 456, "externalCameraId": 123},
            has_sound=True,
        )

        self.assertTrue(camera.extra_state_attributes["has_sound"])

    def test_preserves_ice_candidate_until_go2rtc_session_is_ready(self) -> None:
        async def exercise_race() -> list[tuple[str, object]]:
            camera = DomruCamera(
                coordinator=FakeCoordinator(),
                client=object(),
                camera_id=123,
                camera_name="Intercom",
                camera_data={"ID": 123, "IsSound": 1},
                has_sound=True,
            )
            provider = FakeWebRTCProvider()
            camera.set_next_webrtc_provider(provider)
            await camera.async_refresh_providers(write_state=False)

            candidate = object()
            candidate_task = asyncio.create_task(
                camera.async_on_webrtc_candidate("session-1", candidate)
            )
            await asyncio.sleep(0)
            provider.open_session("session-1")
            await candidate_task
            return provider.received_candidates

        received = asyncio.run(exercise_race())

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "session-1")

    def test_stream_url_credentials_are_not_logged(self) -> None:
        stream_url = "rtsp://camera:secret-token@example.test/live"
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=FakeClient(stream_url),
            camera_id=123,
            camera_name="Intercom",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )

        with self.assertLogs("domru_camera_for_tests.camera", level="INFO") as logs:
            result = asyncio.run(camera.stream_source())

        self.assertEqual(result, stream_url)
        self.assertNotIn(stream_url, "\n".join(logs.output))

    def test_audio_camera_uses_managed_go2rtc_transcoding_proxy(self) -> None:
        stream_url = "https://operator.test/live?token=secret-token"
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=FakeClient(stream_url),
            camera_id=123,
            camera_name="Intercom",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )
        provider = FakeWebRTCProvider()
        camera.set_next_webrtc_provider(provider)

        async def exercise() -> str | None:
            await camera.async_refresh_providers(write_state=False)
            return await camera.stream_source()

        result = asyncio.run(exercise())

        self.assertEqual(result, "rtsp://127.0.0.1:18554/domru_entry-1_123")
        self.assertEqual(
            provider.added_streams,
            [
                (
                    "domru_entry-1_123",
                    f"ffmpeg:{stream_url}#video=copy#audio=aac#audio=opus",
                )
            ],
        )

    def test_audio_proxy_names_are_isolated_between_config_entries(self) -> None:
        async def prepare_stream(entry_id: str) -> tuple[str | None, str]:
            camera = DomruCamera(
                coordinator=FakeCoordinator(entry_id),
                client=FakeClient("https://operator.test/live"),
                camera_id=123,
                camera_name="Intercom",
                camera_data={"ID": 123, "IsSound": 1},
                has_sound=True,
            )
            provider = FakeWebRTCProvider()
            camera.set_next_webrtc_provider(provider)
            await camera.async_refresh_providers(write_state=False)
            source = await camera.stream_source()
            return source, provider.added_streams[0][0]

        async def exercise() -> tuple[tuple[str | None, str], tuple[str | None, str]]:
            first, second = await asyncio.gather(
                prepare_stream("entry-a"),
                prepare_stream("entry-b"),
            )
            return first, second

        first, second = asyncio.run(exercise())

        self.assertEqual(
            first,
            ("rtsp://127.0.0.1:18554/domru_entry-a_123", "domru_entry-a_123"),
        )
        self.assertEqual(
            second,
            ("rtsp://127.0.0.1:18554/domru_entry-b_123", "domru_entry-b_123"),
        )

    def test_audio_proxy_failure_preserves_direct_stream_without_leaking_url(
        self,
    ) -> None:
        stream_url = "https://operator.test/live?token=secret-token"
        camera = DomruCamera(
            coordinator=FakeCoordinator(),
            client=FakeClient(stream_url),
            camera_id=123,
            camera_name="Intercom",
            camera_data={"ID": 123, "IsSound": 1},
            has_sound=True,
        )
        provider = FakeWebRTCProvider(
            stream_error=RuntimeError(f"failed to add {stream_url}")
        )
        camera.set_next_webrtc_provider(provider)

        async def exercise() -> str | None:
            await camera.async_refresh_providers(write_state=False)
            return await camera.stream_source()

        with self.assertLogs("domru_camera_for_tests.camera", level="WARNING") as logs:
            result = asyncio.run(exercise())

        output = "\n".join(logs.output)
        self.assertEqual(result, stream_url)
        self.assertIn("direct stream fallback", output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn(stream_url, output)
        self.assertNotIn("secret-token", output)


if __name__ == "__main__":
    unittest.main()
