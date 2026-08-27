# ruff: noqa: ANN001,ANN003,ANN201,ANN202,ANN204,D101,D102,D105,D107,EM101,EM102,PT009,S105,SLF001,TRY003
"""Behavior tests for the Home Assistant reauthentication flow."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Schema:
    def __init__(self, value):
        self.value = value


def _field(key, **_kwargs):
    return key


vol = types.ModuleType("voluptuous")
vol.Schema = _Schema
vol.Required = _field
vol.Optional = _field
vol.UNDEFINED = object()
sys.modules["voluptuous"] = vol


class FakeEntry:
    def __init__(self) -> None:
        self.data = {
            "auth_method": "phone",
            "phone": "+79991112233",
            "account_id": "account-1",
            "access_token": "expired-access",
            "refresh_token": "expired-refresh",
            "operator_id": 123,
            "preserved": "value",
        }
        self.unique_id = "account-1"


class ConfigFlow:
    def __init_subclass__(cls, **_kwargs):
        return super().__init_subclass__()

    def __init__(self) -> None:
        self.context = {}
        self.hass = object()
        self._reauth_entry = FakeEntry()
        self._unique_id = None
        self.reload_update_calls = 0
        self.listener_update_calls = 0

    @property
    def source(self):
        return self.context.get("source")

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if self._unique_id == self._reauth_entry.unique_id:
            raise RuntimeError("already_configured")

    def _abort_if_unique_id_mismatch(self):
        if self._unique_id != self._reauth_entry.unique_id:
            raise RuntimeError("wrong_account")

    def _get_reauth_entry(self):
        return self._reauth_entry

    def async_update_reload_and_abort(self, entry, *, data_updates):
        self.reload_update_calls += 1
        entry.data = {**entry.data, **data_updates}
        return {"type": "abort", "reason": "reauth_successful"}

    def async_update_and_abort(self, entry, *, data_updates):
        self.listener_update_calls += 1
        entry.data = {**entry.data, **data_updates}
        return {"type": "abort", "reason": "reauth_successful"}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id, **kwargs):
        return {"type": "form", "step_id": step_id, **kwargs}


class OptionsFlow:
    pass


config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigFlow = ConfigFlow
config_entries.OptionsFlow = OptionsFlow
config_entries.ConfigEntry = object
config_entries.ConfigFlowResult = dict
config_entries.FlowResult = dict
config_entries.SOURCE_REAUTH = "reauth"

homeassistant = types.ModuleType("homeassistant")
homeassistant.config_entries = config_entries
sys.modules["homeassistant"] = homeassistant
sys.modules["homeassistant.config_entries"] = config_entries

ha_const = types.ModuleType("homeassistant.const")
ha_const.CONF_PASSWORD = "password"
ha_const.CONF_USERNAME = "username"
sys.modules["homeassistant.const"] = ha_const


class _Selector:
    def __init__(self, _config):
        pass


class _SelectorConfig:
    def __init__(self, **_kwargs):
        pass


class _SelectorMode:
    DROPDOWN = "dropdown"
    TEXT = "text"
    PASSWORD = "password"


selector = types.ModuleType("homeassistant.helpers.selector")
selector.SelectSelector = _Selector
selector.SelectSelectorConfig = _SelectorConfig
selector.SelectSelectorMode = _SelectorMode
selector.TextSelector = _Selector
selector.TextSelectorConfig = _SelectorConfig
selector.TextSelectorType = _SelectorMode
selector.BooleanSelector = _Selector
selector.NumberSelector = _Selector
selector.NumberSelectorConfig = _SelectorConfig

helpers = types.ModuleType("homeassistant.helpers")
helpers.selector = selector
sys.modules["homeassistant.helpers"] = helpers
sys.modules["homeassistant.helpers.selector"] = selector

aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
aiohttp_client.async_create_clientsession = lambda _hass: object()
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

slugify_module = types.ModuleType("slugify")
slugify_module.slugify = lambda value: str(value)
sys.modules["slugify"] = slugify_module


class DomruApiClientError(Exception):
    pass


class DomruApiClientAuthenticationError(DomruApiClientError):
    pass


class DomruApiClientCommunicationError(DomruApiClientError):
    pass


class FakeApiClient:
    def __init__(self, **_kwargs) -> None:
        self.access_token = None
        self.refresh_token = None
        self.operator_id = None

    async def async_confirm_phone_code(self, _phone, _code, account) -> None:
        self.access_token = "new-access"
        self.refresh_token = "new-refresh"
        self.operator_id = account["operatorId"]


def _load_config_flow():
    package_name = "domru_config_flow_for_tests"
    package = types.ModuleType(package_name)
    package.__path__ = []  # type: ignore[attr-defined]
    sys.modules[package_name] = package

    api = types.ModuleType(f"{package_name}.api")
    api.DomruApiClient = FakeApiClient
    api.DomruApiClientError = DomruApiClientError
    api.DomruApiClientAuthenticationError = DomruApiClientAuthenticationError
    api.DomruApiClientCommunicationError = DomruApiClientCommunicationError
    sys.modules[api.__name__] = api

    const_path = Path("custom_components/domru/const.py")
    const_spec = importlib.util.spec_from_file_location(
        f"{package_name}.const", const_path
    )
    if const_spec is None or const_spec.loader is None:
        raise RuntimeError(f"Cannot load {const_path}")
    const = importlib.util.module_from_spec(const_spec)
    sys.modules[const_spec.name] = const
    const_spec.loader.exec_module(const)

    flow_path = Path("custom_components/domru/config_flow.py")
    flow_spec = importlib.util.spec_from_file_location(
        f"{package_name}.config_flow", flow_path
    )
    if flow_spec is None or flow_spec.loader is None:
        raise RuntimeError(f"Cannot load {flow_path}")
    flow = importlib.util.module_from_spec(flow_spec)
    sys.modules[flow_spec.name] = flow
    flow_spec.loader.exec_module(flow)
    return flow


config_flow = _load_config_flow()


class ReauthFlowTests(unittest.TestCase):
    def test_reauth_starts_with_confirmation(self) -> None:
        flow = config_flow.DomruFlowHandler()
        flow.context["source"] = "reauth"

        self.assertTrue(
            hasattr(flow, "async_step_reauth"),
            "config flow does not implement reauthentication",
        )
        result = asyncio.run(flow.async_step_reauth(flow._reauth_entry.data))

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "reauth_confirm")

    def test_phone_sms_reauth_updates_existing_entry(self) -> None:
        flow = config_flow.DomruFlowHandler()
        flow.context["source"] = "reauth"
        flow._phone = "+79991112233"
        flow._selected_account = {
            "accountId": "account-1",
            "operatorId": 321,
            "subscriberId": 456,
            "address": "Test street",
        }

        try:
            result = asyncio.run(flow.async_step_sms({"sms_code": "1122"}))
        except RuntimeError as exception:
            self.fail(
                f"Reauthentication tried to create a duplicate entry: {exception}"
            )

        self.assertEqual(result, {"type": "abort", "reason": "reauth_successful"})
        self.assertEqual(flow._reauth_entry.data["access_token"], "new-access")
        self.assertEqual(flow._reauth_entry.data["refresh_token"], "new-refresh")
        self.assertEqual(flow._reauth_entry.data["preserved"], "value")
        self.assertEqual(flow.listener_update_calls, 1)
        self.assertEqual(flow.reload_update_calls, 0)


if __name__ == "__main__":
    unittest.main()
