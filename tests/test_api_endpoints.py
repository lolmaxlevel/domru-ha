# ruff: noqa: D102,D107,EM102,TRY003,PT009,S106
"""Tests for Dom.ru API endpoint selection."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

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

API_MODULE_PATH = Path("custom_components/domru/api.py")
spec = importlib.util.spec_from_file_location("domru_api_for_tests", API_MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {API_MODULE_PATH}")
api_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api_module
spec.loader.exec_module(api_module)

DomruApiClient = api_module.DomruApiClient


class CapturingClient(DomruApiClient):
    """API client that records requests instead of sending them."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        super().__init__(
            username="user",
            password="pass",
            session=object(),
            refresh_token="refresh",
            operator_id=2,
        )
        self.responses = responses or []
        self.requests: list[dict[str, Any]] = []

    async def _api_wrapper(  # type: ignore[override]
        self,
        method: str,
        url: str,
        json: dict | None = None,
        headers: dict | None = None,
        *,
        authenticated: bool = True,
        success_statuses: tuple[int, ...] | None = None,
        bad_request_message: str | None = None,
    ) -> Any:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
                "authenticated": authenticated,
                "success_statuses": success_statuses,
                "bad_request_message": bad_request_message,
            }
        )
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {"data": {"ok": True}}


class FakeBinaryResponse:
    """Binary HTTP response for direct session requests."""

    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    async def read(self) -> bytes:
        return self._body


class FakeBinarySession:
    """Capture direct HTTP requests and return binary responses."""

    def __init__(self, response: FakeBinaryResponse) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> FakeBinaryResponse:
        self.requests.append(
            {"method": method, "url": url, "headers": headers or {}, "json": json}
        )
        return self.response


class ApiEndpointTests(unittest.TestCase):
    """Endpoint selection behavior."""

    def test_get_subscriber_places_uses_v3_endpoint(self) -> None:
        client = CapturingClient(responses=[{"data": [{"id": 1}]}])

        places = asyncio.run(client.get_subscriber_places())

        self.assertEqual(places, [{"id": 1}])
        self.assertIn("rest/v3/subscriber-places", client.requests[0]["url"])

    def test_discovered_ids_are_exposed_without_private_attribute_access(self) -> None:
        client = CapturingClient()
        client.set_ids(place_id="place-1", access_control_id="door-1")

        self.assertEqual(client.place_id, "place-1")
        self.assertEqual(client.access_control_id, "door-1")

    def test_async_get_data_fetches_access_controls_per_place(self) -> None:
        client = CapturingClient(
            responses=[
                {"data": [{"place": {"id": "place-1"}}]},
                {"data": [{"id": "door-1"}]},
                {"data": []},
                {},
                {"data": []},
            ]
        )

        data = asyncio.run(client.async_get_data())

        self.assertEqual(data["places"], [{"id": "place-1"}])
        self.assertEqual(
            data["access_controls"],
            [{"id": "door-1", "placeId": "place-1", "place_id": "place-1"}],
        )
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols",
            client.requests[1]["url"],
        )

    def test_get_cameras_prefers_place_scoped_endpoint(self) -> None:
        client = CapturingClient(responses=[{"data": [{"id": "camera-1"}]}])
        client.set_ids(place_id="place-1")

        cameras = asyncio.run(client.get_cameras())

        self.assertEqual(cameras, [{"id": "camera-1"}])
        self.assertIn("rest/v1/places/place-1/cameras", client.requests[0]["url"])

    def test_get_cameras_falls_back_when_place_scoped_response_is_empty(self) -> None:
        client = CapturingClient(
            responses=[
                {"data": []},
                {"data": [{"ID": "camera-1"}]},
            ]
        )
        client.set_ids(place_id="place-1")

        cameras = asyncio.run(client.get_cameras())

        self.assertEqual(cameras, [{"ID": "camera-1"}])
        self.assertIn("rest/v1/places/place-1/cameras", client.requests[0]["url"])
        self.assertIn("rest/v1/forpost/cameras", client.requests[1]["url"])

    def test_get_camera_stream_refreshes_session_before_requesting_url(self) -> None:
        client = CapturingClient(
            responses=[
                {"data": {"status": True, "errorCode": None}},
                {"data": {"URL": "https://stream.example.test/live"}},
            ]
        )

        stream_url = asyncio.run(client.async_get_camera_stream_url("camera-1"))

        self.assertEqual(stream_url, "https://stream.example.test/live")
        self.assertEqual(
            [request["method"] for request in client.requests],
            ["PUT", "GET"],
        )
        self.assertIn("refresh-user-session", client.requests[0]["url"])
        self.assertIn("externalCameraId=camera-1", client.requests[0]["url"])
        self.assertIn("LightStream=0", client.requests[1]["url"])

    def test_get_camera_stream_falls_back_when_session_refresh_fails(self) -> None:
        client = CapturingClient(
            responses=[
                api_module.DomruApiClientCommunicationError("refresh failed"),
                {"data": {"URL": "https://stream.example.test/live"}},
            ]
        )

        with self.assertLogs("domru_api_for_tests", level="WARNING"):
            stream_url = asyncio.run(client.async_get_camera_stream_url("camera-1"))

        self.assertEqual(stream_url, "https://stream.example.test/live")
        self.assertEqual(len(client.requests), 2)
        self.assertIn("refresh-user-session", client.requests[0]["url"])
        self.assertIn("LightStream=0", client.requests[1]["url"])

    def test_async_open_door_uses_forpost_endpoint_for_forpost_device(self) -> None:
        client = CapturingClient()

        result = asyncio.run(
            client.async_open_door(
                access_control_id="door-1",
                place_id="place-1",
                access_control={
                    "id": "door-1",
                    "openMethod": "FORPOST",
                    "externalCameraId": "camera-1",
                    "externalDeviceId": "device-1",
                },
            )
        )

        self.assertEqual(result, {"ok": True})
        request = client.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertIn(
            "rest/v1/forpost/cameras/camera-1/devices/device-1/open",
            request["url"],
        )
        self.assertIsNone(request["json"])
        self.assertEqual(request["headers"], {"X-Payment-PlaceId": "place-1"})

    def test_async_open_entrance_uses_entrance_action_endpoint(self) -> None:
        client = CapturingClient()

        result = asyncio.run(
            client.async_open_entrance(
                place_id="place-1",
                access_control_id="door-1",
                entrance_id="entrance-1",
            )
        )

        self.assertEqual(result, {"ok": True})
        request = client.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols/door-1/entrances/entrance-1/actions",
            request["url"],
        )
        self.assertEqual(request["json"], {"name": "accessControlOpen"})

    def test_async_get_access_control_snapshot_uses_videosnapshots(self) -> None:
        session = FakeBinarySession(FakeBinaryResponse(b"\xff\xd8jpeg"))
        client = DomruApiClient(
            username="user",
            password="pass",
            session=session,
            refresh_token="refresh",
            operator_id=2,
        )

        result = asyncio.run(
            client.async_get_access_control_snapshot(
                place_id="place-1",
                access_control_id="door-1",
            )
        )

        self.assertEqual(result, b"\xff\xd8jpeg")
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols/door-1/videosnapshots",
            session.requests[0]["url"],
        )

    def test_get_sip_credentials_fetches_access_controls_for_v3_places(self) -> None:
        client = CapturingClient(
            responses=[
                {"data": [{"place": {"id": "place-1"}}]},
                {"data": [{"id": "door-1"}]},
                {"data": {"login": "sip", "password": "secret", "realm": "realm"}},
            ]
        )

        credentials = asyncio.run(client.async_get_sip_credentials("install-1"))

        self.assertEqual(
            credentials,
            {"login": "sip", "password": "secret", "realm": "realm"},
        )
        self.assertIn("rest/v3/subscriber-places", client.requests[0]["url"])
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols",
            client.requests[1]["url"],
        )
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols/door-1/sipdevices",
            client.requests[2]["url"],
        )
        self.assertEqual(client.requests[2]["json"], {"installationId": "install-1"})

    def test_get_sip_credentials_can_target_a_specific_access_control(self) -> None:
        client = CapturingClient(
            responses=[
                {"data": {"login": "sip-2", "password": "secret", "realm": "realm"}}
            ]
        )

        credentials = asyncio.run(
            client.async_get_sip_credentials(
                "install-1",
                place_id="place-1",
                access_control_id="door-2",
            )
        )

        self.assertEqual(credentials["login"], "sip-2")
        self.assertEqual(len(client.requests), 1)
        self.assertIn(
            "rest/v1/places/place-1/accesscontrols/door-2/sipdevices",
            client.requests[0]["url"],
        )

    def test_register_push_device_mirrors_android_device_installation(self) -> None:
        client = CapturingClient()

        result = asyncio.run(client.register_push_device("fcm-token", "install-1"))

        self.assertTrue(result)
        self.assertEqual(
            [request["method"] for request in client.requests],
            ["POST", "POST"],
        )
        self.assertIn(
            "api/mh-customer-device/mobile/public/v1/customers/device-installations",
            client.requests[0]["url"],
        )
        self.assertIn("rest/v1/subscriberNotifications", client.requests[1]["url"])
        public_request, subscriber_request = client.requests
        public_body = public_request["json"]
        subscriber_body = subscriber_request["json"]
        self.assertFalse(public_request["authenticated"])
        self.assertNotIn("deviceType", public_body)
        self.assertTrue(subscriber_request["authenticated"])
        self.assertEqual(public_body["installationId"], "install-1")
        self.assertEqual(public_body["pushToken"], "fcm-token")
        self.assertEqual(public_body["platform"], "google")
        self.assertEqual(public_body["appVersion"], "9.9.0")
        self.assertEqual(public_body["appVersionCode"], 90900020)
        self.assertEqual(subscriber_body["deviceType"], "MOBILE_APPLICATION")

    def test_push_registration_attempts_subscriber_binding_after_public_failure(
        self,
    ) -> None:
        client = CapturingClient(responses=[RuntimeError("public failed")])

        with self.assertLogs("domru_api_for_tests", level="WARNING"):
            result = asyncio.run(client.register_push_device("fcm-token", "install-1"))

        self.assertFalse(result)
        self.assertEqual(len(client.requests), 2)
        self.assertIn("subscriberNotifications", client.requests[1]["url"])

    def test_unregister_push_device_omits_push_token(self) -> None:
        client = CapturingClient()

        result = asyncio.run(client.unregister_push_device("install-1"))

        self.assertTrue(result)
        request = client.requests[0]
        self.assertEqual(request["method"], "DELETE")
        self.assertIn("rest/v1/subscriberNotifications", request["url"])
        self.assertEqual(request["json"]["installationId"], "install-1")
        self.assertNotIn("pushToken", request["json"])


if __name__ == "__main__":
    unittest.main()
