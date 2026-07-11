# ruff: noqa: D102,D103,D107,EM102,PT009,PT027,S106,TRY003
"""Tests for Dom.ru API phone login helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

if "aiohttp" not in sys.modules:
    aiohttp_stub = types.ModuleType("aiohttp")

    class ClientError(Exception):
        """aiohttp.ClientError test stub."""

    aiohttp_stub.ClientError = ClientError
    aiohttp_stub.ClientSession = object
    sys.modules["aiohttp"] = aiohttp_stub

if "aiohttp.client_exceptions" not in sys.modules:
    client_exceptions_stub = types.ModuleType("aiohttp.client_exceptions")

    class ClientConnectorError(ClientError):
        """aiohttp ClientConnectorError test stub."""

    class ContentTypeError(ClientError):
        """aiohttp ContentTypeError test stub."""

    client_exceptions_stub.ClientConnectorError = ClientConnectorError
    client_exceptions_stub.ContentTypeError = ContentTypeError
    sys.modules["aiohttp.client_exceptions"] = client_exceptions_stub

if "async_timeout" not in sys.modules:
    async_timeout_stub = types.ModuleType("async_timeout")

    class _Timeout:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    def timeout(_seconds: int) -> _Timeout:
        return _Timeout()

    async_timeout_stub.timeout = timeout
    sys.modules["async_timeout"] = async_timeout_stub

from aiohttp.client_exceptions import ContentTypeError

API_MODULE_PATH = Path("custom_components/domru/api.py")
spec = importlib.util.spec_from_file_location("domru_api_for_tests", API_MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {API_MODULE_PATH}")
api_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api_module
spec.loader.exec_module(api_module)

DomruApiClient = api_module.DomruApiClient


def _content_type_error() -> ContentTypeError:
    """Return a ContentTypeError compatible with real aiohttp and test stubs."""
    try:
        return ContentTypeError(request_info=None, history=())
    except TypeError:
        return ContentTypeError()


class FakeResponse:
    """HTTP response stub for API wrapper tests."""

    reason = "OK"

    def __init__(
        self,
        payload: Any,
        status: int = 200,
        *,
        json_exception: Exception | None = None,
        text: str = "",
    ) -> None:
        self._payload = payload
        self.status = status
        self._json_exception = json_exception
        self._text = text

    async def json(self) -> Any:
        if self._json_exception is not None:
            raise self._json_exception
        return self._payload

    async def text(self) -> str:
        return self._text


class FakeSession:
    """Capture outgoing API requests and return queued responses."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def request(
        self,
        *,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers or {},
            }
        )
        return self.responses.pop(0)


class ApiPhoneLoginTests(unittest.TestCase):
    """Phone login request behavior."""

    def test_stored_access_token_authentication_makes_no_refresh_request(
        self,
    ) -> None:
        session = FakeSession()
        client = DomruApiClient(
            username=None,
            password=None,
            session=session,
            access_token="sms-token",
            refresh_token="sms-token",
            operator_id=123,
        )

        asyncio.run(client.async_authenticate())

        self.assertEqual(session.requests, [])

    def test_get_phone_accounts_escapes_phone_number(self) -> None:
        session = FakeSession(FakeResponse([{"accountId": "account-1"}]))
        client = DomruApiClient(username=None, password=None, session=session)

        accounts = asyncio.run(client.async_get_phone_accounts("+79991112233"))

        self.assertEqual(accounts, [{"accountId": "account-1"}])
        request = session.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertTrue(request["url"].endswith("/auth/v2/login/%2B79991112233"))
        self.assertEqual(request["headers"]["Connection"], "Keep-Alive")

    def test_get_phone_accounts_accepts_multiple_choices_status(self) -> None:
        session = FakeSession(FakeResponse([{"accountId": "account-1"}], status=300))
        client = DomruApiClient(username=None, password=None, session=session)

        accounts = asyncio.run(client.async_get_phone_accounts("+79991112233"))

        self.assertEqual(accounts, [{"accountId": "account-1"}])

    def test_get_phone_accounts_reports_unregistered_phone(self) -> None:
        session = FakeSession(FakeResponse(None, status=204))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "Phone number is not registered",
        ):
            asyncio.run(client.async_get_phone_accounts("+79991112233"))

    def test_get_phone_accounts_reports_invalid_login(self) -> None:
        session = FakeSession(FakeResponse({"error": "invalid_login"}, status=400))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "Invalid phone number or login",
        ):
            asyncio.run(client.async_get_phone_accounts("+79991112233"))

    def test_get_phone_accounts_reports_password_flow(self) -> None:
        session = FakeSession(FakeResponse([], status=200))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "Password authentication is required",
        ):
            asyncio.run(client.async_get_phone_accounts("+79991112233"))

    def test_request_phone_confirmation_posts_selected_account(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
            "address": "Test street",
        }
        session = FakeSession(FakeResponse({}))
        client = DomruApiClient(username=None, password=None, session=session)

        asyncio.run(client.async_request_phone_confirmation("+79991112233", account))

        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertTrue(request["url"].endswith("/auth/v2/confirmation/%2B79991112233"))
        self.assertEqual(request["json"], account)

    def test_request_phone_confirmation_accepts_null_response(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(FakeResponse(None))
        client = DomruApiClient(username=None, password=None, session=session)

        asyncio.run(client.async_request_phone_confirmation("+79991112233", account))

        self.assertEqual(len(session.requests), 1)

    def test_request_phone_confirmation_accepts_empty_non_json_response(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(
            FakeResponse(None, json_exception=_content_type_error(), text="")
        )
        client = DomruApiClient(username=None, password=None, session=session)

        asyncio.run(client.async_request_phone_confirmation("+79991112233", account))

        self.assertEqual(len(session.requests), 1)

    def test_request_phone_confirmation_reports_rate_limit(self) -> None:
        account = {
            "accountId": "account-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(FakeResponse({"error": "limit_exceeded"}, status=429))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "Too many SMS requests. Try again later",
        ):
            asyncio.run(
                client.async_request_phone_confirmation("+79991112233", account)
            )

    def test_confirm_phone_code_posts_confirmation_and_stores_tokens(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(
            FakeResponse(
                {
                    "accessToken": "access",
                    "refreshToken": "refresh",
                    "operatorId": 123,
                }
            )
        )
        client = DomruApiClient(username=None, password=None, session=session)

        result = asyncio.run(
            client.async_confirm_phone_code("+79991112233", "1122", account)
        )

        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertTrue(
            request["url"].endswith("/auth/v3/auth/%2B79991112233/confirmation")
        )
        self.assertEqual(
            request["json"],
            {
                "operatorId": 123,
                "login": "+79991112233",
                "accountId": "account-1",
                "profileId": "profile-1",
                "confirm1": "1122",
                "confirm2": "1122",
                "subscriberId": "456",
            },
        )
        self.assertEqual(result["refreshToken"], "refresh")
        self.assertEqual(client.refresh_token, "refresh")
        self.assertEqual(client.operator_id, 123)

    def test_confirm_phone_code_accepts_nested_token_response(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(
            FakeResponse(
                {
                    "data": {
                        "accessToken": "access",
                        "refreshToken": "refresh",
                        "operatorId": 123,
                    }
                }
            )
        )
        client = DomruApiClient(username=None, password=None, session=session)

        result = asyncio.run(
            client.async_confirm_phone_code("+79991112233", "1122", account)
        )

        self.assertEqual(result["refreshToken"], "refresh")
        self.assertEqual(client.refresh_token, "refresh")
        self.assertEqual(client.operator_id, 123)

    def test_confirm_phone_code_requires_refresh_token_for_phone_login(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(
            FakeResponse(
                {
                    "accessToken": "access",
                    "operatorId": 123,
                }
            )
        )
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "No refresh token",
        ):
            asyncio.run(
                client.async_confirm_phone_code("+79991112233", "1122", account)
            )

        self.assertIsNone(client.refresh_token)
        self.assertIsNone(client.operator_id)

    def test_confirm_phone_code_failure_does_not_store_tokens(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(FakeResponse({"errorCode": 6005}, status=500))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientError,
            "Invalid SMS confirmation code",
        ):
            asyncio.run(
                client.async_confirm_phone_code("+79991112233", "0000", account)
            )

        self.assertIsNone(client.refresh_token)
        self.assertIsNone(client.operator_id)

    def test_confirm_phone_code_http_400_reports_wrong_sms_code(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(FakeResponse({}, status=400))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientError,
            "SMS code is wrong. Try again.",
        ):
            asyncio.run(
                client.async_confirm_phone_code("+79991112233", "0000", account)
            )

        self.assertIsNone(client.refresh_token)
        self.assertIsNone(client.operator_id)

    def test_confirm_phone_code_http_406_reports_invalid_format(self) -> None:
        account = {
            "accountId": "account-1",
            "operatorId": 123,
            "subscriberId": 456,
        }
        session = FakeSession(FakeResponse({"error": "invalid_format"}, status=406))
        client = DomruApiClient(username=None, password=None, session=session)

        with self.assertRaisesRegex(
            api_module.DomruApiClientAuthenticationError,
            "Invalid SMS code format",
        ):
            asyncio.run(client.async_confirm_phone_code("+79991112233", "x", account))

    def test_refresh_token_authentication_does_not_require_password(self) -> None:
        session = FakeSession(
            FakeResponse(
                {
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                    "operatorId": 321,
                }
            )
        )
        client = DomruApiClient(
            username=None,
            password=None,
            session=session,
            refresh_token="old-refresh",
            operator_id=123,
        )

        asyncio.run(client.async_authenticate())

        request = session.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertTrue(request["url"].endswith("/auth/v2/session/refresh"))
        self.assertEqual(request["headers"]["Bearer"], "old-refresh")
        self.assertEqual(request["headers"]["Operator"], "123")
        self.assertEqual(client.refresh_token, "new-refresh")
        self.assertEqual(client.operator_id, 321)

    def test_refresh_token_authentication_accepts_nested_token_response(self) -> None:
        session = FakeSession(
            FakeResponse(
                {
                    "data": {
                        "accessToken": "new-access",
                        "refreshToken": "new-refresh",
                        "operatorId": 321,
                    }
                }
            )
        )
        client = DomruApiClient(
            username=None,
            password=None,
            session=session,
            refresh_token="old-refresh",
            operator_id=123,
        )

        asyncio.run(client.async_authenticate())

        self.assertEqual(client.refresh_token, "new-refresh")
        self.assertEqual(client.operator_id, 321)


if __name__ == "__main__":
    unittest.main()
