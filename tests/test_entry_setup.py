# ruff: noqa: D101,D102,D107,EM102,N818,PT009,PT027,S105,TRY003
"""Tests for config-entry authentication persistence and setup routing."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any


class ConfigEntryAuthFailed(Exception):
    """Home Assistant authentication failure test stub."""


class ConfigEntryNotReady(Exception):
    """Home Assistant temporary setup failure test stub."""


class DomruApiClientError(Exception):
    """Dom.ru API failure test stub."""


class DomruApiClientCommunicationError(DomruApiClientError):
    """Dom.ru communication failure test stub."""


class DomruApiClientAuthenticationError(DomruApiClientError):
    """Dom.ru authentication failure test stub."""


class FakeDomruApiClient:
    """Capture client construction and expose the auth callback."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.on_auth_update = kwargs["on_auth_update"]

    async def async_authenticate(self) -> None:
        return None

    async def async_get_data(self) -> dict[str, Any]:
        return {"places": [{"id": "place-1"}]}


def _load_entry_setup_module() -> types.ModuleType | None:
    module_path = Path("custom_components/domru/entry_setup.py")
    if not module_path.exists():
        return None

    package_name = "domru_entry_setup_for_tests"
    package = types.ModuleType(package_name)
    package.__path__ = []  # type: ignore[attr-defined]
    sys.modules[package_name] = package

    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    sys.modules["homeassistant.exceptions"] = exceptions

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.CONF_PASSWORD = "password"
    ha_const.CONF_USERNAME = "username"
    sys.modules["homeassistant.const"] = ha_const

    api = types.ModuleType(f"{package_name}.api")
    api.DomruApiClient = FakeDomruApiClient
    api.DomruApiClientAuthenticationError = DomruApiClientAuthenticationError
    api.DomruApiClientCommunicationError = DomruApiClientCommunicationError
    api.DomruApiClientError = DomruApiClientError
    sys.modules[api.__name__] = api

    const = types.ModuleType(f"{package_name}.const")
    const.CONF_ACCESS_TOKEN = "access_token"
    const.CONF_OPERATOR_ID = "operator_id"
    const.CONF_REFRESH_TOKEN = "refresh_token"
    sys.modules[const.__name__] = const

    module_name = f"{package_name}.entry_setup"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


entry_setup = _load_entry_setup_module()


class FakeConfigEntries:
    def __init__(self) -> None:
        self.updates: list[tuple[object, dict[str, Any]]] = []

    def async_update_entry(self, entry: object, *, data: dict[str, Any]) -> None:
        self.updates.append((entry, data))


class FakeHass:
    def __init__(self) -> None:
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(self) -> None:
        self.data = {"phone": "+79991112233", "refresh_token": "old-refresh"}


class FakeClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.authenticated = False

    async def async_authenticate(self) -> None:
        self.authenticated = True
        if isinstance(self.result, Exception):
            raise self.result

    async def async_get_data(self) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


class EntrySetupTests(unittest.TestCase):
    def setUp(self) -> None:
        if entry_setup is None:
            self.fail("custom_components/domru/entry_setup.py is missing")

    def test_persist_auth_update_preserves_non_auth_entry_data(self) -> None:
        hass = FakeHass()
        entry = FakeEntry()

        entry_setup.persist_auth_update(
            hass,
            entry,
            "new-access",
            "new-refresh",
            321,
        )

        self.assertEqual(
            hass.config_entries.updates,
            [
                (
                    entry,
                    {
                        "phone": "+79991112233",
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "operator_id": 321,
                    },
                )
            ],
        )

    def test_initial_auth_failure_requests_reauthentication(self) -> None:
        client = FakeClient(DomruApiClientAuthenticationError("expired"))

        with self.assertRaises(ConfigEntryAuthFailed):
            asyncio.run(entry_setup.async_load_initial_data(client))

    def test_initial_api_failure_remains_retryable(self) -> None:
        client = FakeClient(DomruApiClientCommunicationError("offline"))

        with self.assertRaises(ConfigEntryNotReady):
            asyncio.run(entry_setup.async_load_initial_data(client))

    def test_initial_data_is_returned_after_authentication(self) -> None:
        client = FakeClient({"places": [{"id": "place-1"}]})

        result = asyncio.run(entry_setup.async_load_initial_data(client))

        self.assertTrue(client.authenticated)
        self.assertEqual(result, {"places": [{"id": "place-1"}]})

    def test_create_client_wires_rotated_credentials_to_entry_storage(self) -> None:
        hass = FakeHass()
        entry = FakeEntry()
        entry.data.update(
            {
                "access_token": "stored-access",
                "operator_id": 123,
            }
        )
        session = object()

        self.assertTrue(
            hasattr(entry_setup, "async_create_client_and_load_data"),
            "entry setup does not construct a persistence-aware API client",
        )
        client, initial_data = asyncio.run(
            entry_setup.async_create_client_and_load_data(hass, entry, session)
        )
        client.on_auth_update("new-access", "new-refresh", 321)

        self.assertEqual(initial_data, {"places": [{"id": "place-1"}]})
        self.assertIs(client.kwargs["session"], session)
        self.assertEqual(client.kwargs["access_token"], "stored-access")
        self.assertEqual(client.kwargs["refresh_token"], "old-refresh")
        self.assertEqual(
            hass.config_entries.updates[0][1]["refresh_token"],
            "new-refresh",
        )


if __name__ == "__main__":
    unittest.main()
