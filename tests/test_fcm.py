# ruff: noqa: ANN001,ANN002,ANN003,ANN201,ANN205,ANN206,D102,D106,D107,N802,PT009,RUF012,SLF001
"""Tests for FCM doorbell notification helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_homeassistant_stubs() -> None:
    """Install minimal Home Assistant modules needed to import fcm.py."""
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    event = types.ModuleType("homeassistant.helpers.event")
    helpers = types.ModuleType("homeassistant.helpers")

    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    core.callback = lambda func: func
    dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None
    event.async_track_time_interval = lambda *_args, **_kwargs: (lambda: None)

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.dispatcher", dispatcher)
    sys.modules.setdefault("homeassistant.helpers.event", event)


_install_homeassistant_stubs()

FCM_MODULE_PATH = Path("custom_components/domru/fcm.py")
spec = importlib.util.spec_from_file_location("domru_fcm_for_tests", FCM_MODULE_PATH)
if spec is None or spec.loader is None:
    msg = f"Cannot load {FCM_MODULE_PATH}"
    raise RuntimeError(msg)
fcm_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fcm_module
spec.loader.exec_module(fcm_module)

fcm_event_from_notification = fcm_module.fcm_event_from_notification
DomruFcmListener = fcm_module.DomruFcmListener


class FakeHass:
    """Minimal Home Assistant object for FCM listener tests."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeEntry:
    """Minimal config entry for FCM listener tests."""

    data: dict = {}


class FakeApi:
    """Minimal API for FCM listener tests."""

    async def register_push_device(self, _token: str, _installation_id: str) -> bool:
        return True


class FakeFirebaseMessaging:
    """Firebase module fake that returns no client."""

    class FcmRegisterConfig:
        def __init__(self, **_kwargs) -> None:
            pass

    class FcmPushClientConfig:
        def __init__(self, **_kwargs) -> None:
            pass

    @staticmethod
    def FcmPushClient(*_args, **_kwargs):
        return None


class FakeRaceClient:
    """FCM client fake that clears listener state during check-in."""

    def __init__(self, listener) -> None:
        self.listener = listener
        self.started = False

    async def checkin_or_register(self) -> str:
        self.listener._client = None
        return "fcm-token"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        return None

    def is_started(self) -> bool:
        return self.started


class FakeRaceFirebaseMessaging:
    """Firebase module fake that reproduces mutable _client startup race."""

    client: FakeRaceClient | None = None
    listener = None

    class FcmRegisterConfig:
        def __init__(self, **_kwargs) -> None:
            pass

    class FcmPushClientConfig:
        def __init__(self, **_kwargs) -> None:
            pass

    @classmethod
    def FcmPushClient(cls, *_args, **_kwargs):
        cls.client = FakeRaceClient(cls.listener)
        return cls.client


class FcmPayloadTests(unittest.TestCase):
    """FCM payload parsing behavior."""

    def test_incoming_call_push_maps_to_ring_event(self) -> None:
        event = fcm_event_from_notification(
            {
                "data": {
                    "PushType": "CALL_INCOMING",
                    "PlaceId": 12,
                    "AccessControlId": 34,
                    "Call-ID": "call-1",
                    "GateName": "Front door",
                    "AllowOpen": "true",
                },
            }
        )

        self.assertEqual(event["event_type"], "ring")
        self.assertEqual(event["place_id"], "12")
        self.assertEqual(event["access_control_id"], "34")
        self.assertEqual(event["attributes"]["call_id"], "call-1")
        self.assertEqual(event["attributes"]["gate_name"], "Front door")

    def test_google_label_push_maps_to_ended_event(self) -> None:
        event = fcm_event_from_notification(
            {"data": {"google.c.a.m_l": "CALL_END_ANSWERED_MOBILE"}}
        )

        self.assertEqual(event["event_type"], "ended")
        self.assertEqual(event["attributes"]["reason"], "answered_elsewhere")

    def test_unknown_push_type_is_ignored(self) -> None:
        self.assertIsNone(fcm_event_from_notification({"data": {"PushType": "OTHER"}}))

    def test_fcm_import_runs_in_executor(self) -> None:
        source = FCM_MODULE_PATH.read_text()
        compact_source = "".join(source.split())

        self.assertIn(
            "self._hass.async_add_executor_job(importlib.import_module",
            compact_source,
        )
        self.assertNotIn(
            'firebase_messaging = importlib.import_module("firebase_messaging")',
            source,
        )

    def test_fcm_start_handles_none_client_without_crashing(self) -> None:
        sys.modules["firebase_messaging"] = FakeFirebaseMessaging
        listener = DomruFcmListener(FakeHass(), FakeEntry(), FakeApi(), "install-1")

        try:
            with self.assertLogs(fcm_module.LOGGER, level="WARNING") as logs:
                asyncio.run(listener.async_start())
        finally:
            sys.modules.pop("firebase_messaging", None)

        self.assertIsNone(listener.fcm_token)
        output = "\n".join(logs.output)
        self.assertIn("returned no FCM client", output)
        self.assertNotIn("AttributeError", output)

    def test_fcm_start_uses_local_client_after_checkin(self) -> None:
        listener = DomruFcmListener(FakeHass(), FakeEntry(), FakeApi(), "install-1")
        FakeRaceFirebaseMessaging.listener = listener
        sys.modules["firebase_messaging"] = FakeRaceFirebaseMessaging

        try:
            asyncio.run(listener.async_start())
        finally:
            sys.modules.pop("firebase_messaging", None)
            FakeRaceFirebaseMessaging.listener = None

        self.assertEqual(listener.fcm_token, "fcm-token")
        self.assertIs(FakeRaceFirebaseMessaging.client, listener._client)
        self.assertTrue(FakeRaceFirebaseMessaging.client.started)


if __name__ == "__main__":
    unittest.main()
