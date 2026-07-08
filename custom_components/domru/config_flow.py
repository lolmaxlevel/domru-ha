"""Adds config flow for Dom.ru Smart Intercom."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from slugify import slugify

from .api import (
    DomruApiClient,
    DomruApiClientAuthenticationError,
    DomruApiClientCommunicationError,
    DomruApiClientError,
)
from .const import (
    AUTH_METHOD_PASSWORD,
    AUTH_METHOD_PHONE,
    CONF_ACCOUNT_ID,
    CONF_AUTH_METHOD,
    CONF_CAMERA_STREAM_CACHE,
    CONF_CAMERA_STREAM_CACHE_TIME,
    CONF_OPERATOR_ID,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_SIP_ENABLED,
    CONF_SIP_HOST_IP,
    CONF_SIP_LOCAL_IP,
    CONF_SIP_LOCAL_PORT,
    CONF_SIP_MODE,
    DEFAULT_SIP_MODE,
    DOMAIN,
    LOGGER,
    SIP_MODE_ON_DEMAND,
    SIP_MODE_PERSISTENT,
)

RUSSIAN_PHONE_DIGITS = 11
ERROR_API = "api_error"


class DomruFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Dom.ru Smart Intercom."""

    VERSION = 1
    supports_options_flow = True

    def __init__(self) -> None:
        """Initialize flow state."""
        super().__init__()
        self._phone: str | None = None
        self._phone_accounts: list[dict] = []
        self._selected_account: dict | None = None
        self._last_error_message: str | None = None

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            if user_input[CONF_AUTH_METHOD] == AUTH_METHOD_PHONE:
                return await self.async_step_phone()
            return await self.async_step_password()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTH_METHOD,
                        default=AUTH_METHOD_PHONE,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "label": "Phone + SMS code",
                                    "value": AUTH_METHOD_PHONE,
                                },
                                {
                                    "label": "Username + password",
                                    "value": AUTH_METHOD_PASSWORD,
                                },
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        ),
                    ),
                },
            ),
        )

    async def async_step_password(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle login and password authentication."""
        _errors = {}
        if user_input is not None:
            try:
                await self._test_credentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
            except DomruApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                _errors["base"] = "auth"
            except DomruApiClientCommunicationError as exception:
                LOGGER.error(exception)
                _errors["base"] = "connection"
            except DomruApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    ## Do NOT use this in production code
                    ## The unique_id should never be something that can change
                    ## https://developers.home-assistant.io/docs/config_entries_config_flow_handler#unique-ids
                    unique_id=slugify(user_input[CONF_USERNAME])
                )
                self._abort_if_unique_id_configured()
                data = dict(user_input)
                data[CONF_AUTH_METHOD] = AUTH_METHOD_PASSWORD
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=data,
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def async_step_phone(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle phone number input and account discovery."""
        _errors = {}
        if user_input is not None:
            self._phone = _normalize_phone(user_input[CONF_PHONE])
            try:
                client = self._create_client()
                accounts = await client.async_get_phone_accounts(self._phone)
            except DomruApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                self._last_error_message = _error_message(exception)
                _errors["base"] = ERROR_API
            except DomruApiClientCommunicationError as exception:
                LOGGER.error(exception)
                _errors["base"] = "connection"
            except DomruApiClientError as exception:
                LOGGER.exception(exception)
                self._last_error_message = _error_message(exception)
                _errors["base"] = ERROR_API
            else:
                self._phone_accounts = [
                    account for account in accounts if account.get("accountId")
                ]
                if not self._phone_accounts:
                    _errors["base"] = "auth"
                elif len(self._phone_accounts) == 1:
                    self._selected_account = self._phone_accounts[0]
                    request_result = await self._async_request_phone_confirmation()
                    if request_result is None:
                        return await self.async_step_sms()
                    _errors["base"] = request_result[0]
                    self._last_error_message = request_result[1]
                else:
                    return await self.async_step_account()

        return self.async_show_form(
            step_id="phone",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PHONE,
                        default=(user_input or {}).get(CONF_PHONE, "+7"),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                },
            ),
            errors=_errors,
            description_placeholders=_description_placeholders(
                self._last_error_message
            ),
        )

    async def async_step_account(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle account selection for phone login."""
        if self._phone is None or not self._phone_accounts:
            return await self.async_step_phone()

        _errors = {}
        if user_input is not None:
            account_id = user_input[CONF_ACCOUNT_ID]
            self._selected_account = next(
                (
                    account
                    for account in self._phone_accounts
                    if account.get("accountId") == account_id
                ),
                None,
            )
            if self._selected_account is None:
                _errors["base"] = "auth"
            else:
                request_result = await self._async_request_phone_confirmation()
                if request_result is None:
                    return await self.async_step_sms()
                _errors["base"] = request_result[0]
                self._last_error_message = request_result[1]

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "label": _account_label(account),
                                    "value": account["accountId"],
                                }
                                for account in self._phone_accounts
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        ),
                    ),
                },
            ),
            errors=_errors,
            description_placeholders=_description_placeholders(
                self._last_error_message
            ),
        )

    async def async_step_sms(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle SMS code confirmation."""
        if self._phone is None or self._selected_account is None:
            return await self.async_step_phone()

        _errors = {}
        if user_input is not None:
            try:
                client = self._create_client()
                await client.async_confirm_phone_code(
                    self._phone,
                    user_input["sms_code"],
                    self._selected_account,
                )
                refresh_token, operator_id = _phone_auth_tokens(client)
            except DomruApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                self._last_error_message = _error_message(exception)
                _errors["base"] = ERROR_API
            except DomruApiClientCommunicationError as exception:
                LOGGER.error(exception)
                _errors["base"] = "connection"
            except DomruApiClientError as exception:
                LOGGER.exception(exception)
                self._last_error_message = _error_message(exception)
                _errors["base"] = ERROR_API
            else:
                account_id = self._selected_account.get("accountId", self._phone)
                await self.async_set_unique_id(slugify(str(account_id)))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_account_label(self._selected_account),
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_PHONE,
                        CONF_PHONE: self._phone,
                        CONF_ACCOUNT_ID: self._selected_account.get("accountId"),
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_OPERATOR_ID: operator_id,
                    },
                )

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema(
                {
                    vol.Required("sms_code"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                },
            ),
            errors=_errors,
            description_placeholders=_description_placeholders(
                self._last_error_message
            ),
        )

    async def _test_credentials(self, username: str, password: str) -> None:
        """Validate credentials."""
        client = DomruApiClient(
            username=username,
            password=password,
            session=async_create_clientsession(self.hass),
        )
        await client.async_authenticate()

    def _create_client(self) -> DomruApiClient:
        """Create an unauthenticated API client for flow helper calls."""
        return DomruApiClient(
            username=None,
            password=None,
            session=async_create_clientsession(self.hass),
        )

    async def _async_request_phone_confirmation(self) -> tuple[str, str] | None:
        """Request SMS confirmation and return a config flow error key on failure."""
        if self._phone is None or self._selected_account is None:
            return "auth", ""

        try:
            client = self._create_client()
            await client.async_request_phone_confirmation(
                self._phone,
                self._selected_account,
            )
        except DomruApiClientAuthenticationError as exception:
            LOGGER.warning(exception)
            return ERROR_API, _error_message(exception)
        except DomruApiClientCommunicationError as exception:
            LOGGER.error(exception)
            return "connection", ""
        except DomruApiClientError as exception:
            LOGGER.exception(exception)
            return ERROR_API, _error_message(exception)
        return None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DomruOptionsFlowHandler:
        """Create the options flow."""
        return DomruOptionsFlowHandler(config_entry)


def _normalize_phone(phone: str) -> str:
    """Normalize common Russian phone formats to +7XXXXXXXXXX."""
    value = (
        phone.strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if value.startswith("8") and len(value) == RUSSIAN_PHONE_DIGITS:
        return f"+7{value[1:]}"
    if value.startswith("7") and len(value) == RUSSIAN_PHONE_DIGITS:
        return f"+{value}"
    return value


def _account_label(account: dict) -> str:
    """Build a human-readable account label."""
    return str(
        account.get("address")
        or account.get("accountId")
        or account.get("subscriberId")
        or "Dom.ru account"
    )


def _error_message(exception: Exception) -> str:
    """Return a display-safe API error message."""
    return str(exception) or "Dom.ru returned an error"


def _description_placeholders(message: str | None) -> dict[str, str]:
    """Return flow description placeholders for dynamic API errors."""
    return {"error_message": message or ""}


def _phone_auth_tokens(client: DomruApiClient) -> tuple[str, str | int]:
    """Return stored phone-login tokens or raise a config-flow auth error."""
    refresh_token = client.refresh_token
    operator_id = client.operator_id
    if not refresh_token or operator_id is None:
        msg = "No refresh token or operator ID in phone confirmation"
        raise DomruApiClientAuthenticationError(msg)
    return refresh_token, operator_id


class DomruOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Dom.ru Smart Intercom."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CAMERA_STREAM_CACHE,
                        default=self._config_entry.options.get(
                            CONF_CAMERA_STREAM_CACHE, False
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_CAMERA_STREAM_CACHE_TIME,
                        default=self._config_entry.options.get(
                            CONF_CAMERA_STREAM_CACHE_TIME, 300
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60,
                            max=3600,
                            step=60,
                            unit_of_measurement="seconds",
                        ),
                    ),
                    vol.Optional(
                        CONF_SIP_ENABLED,
                        default=self._config_entry.options.get(CONF_SIP_ENABLED, True),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_SIP_MODE,
                        default=self._config_entry.options.get(
                            CONF_SIP_MODE, DEFAULT_SIP_MODE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "label": "Постоянная регистрация (стандартно)",
                                    "value": SIP_MODE_PERSISTENT,
                                },
                                {
                                    "label": "По запросу (через FCM push)",
                                    "value": SIP_MODE_ON_DEMAND,
                                },
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        ),
                    ),
                    vol.Optional(
                        CONF_SIP_LOCAL_IP,
                        default=self._config_entry.options.get(CONF_SIP_LOCAL_IP, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Optional(
                        CONF_SIP_HOST_IP,
                        default=self._config_entry.options.get(CONF_SIP_HOST_IP, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Optional(
                        CONF_SIP_LOCAL_PORT,
                        default=self._config_entry.options.get(
                            CONF_SIP_LOCAL_PORT, 5060
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1024,
                            max=65535,
                            step=1,
                        ),
                    ),
                },
            ),
        )
