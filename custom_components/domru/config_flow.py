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
    CONF_CAMERA_STREAM_CACHE,
    CONF_CAMERA_STREAM_CACHE_TIME,
    DOMAIN,
    LOGGER,
)


class DomruFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Dom.ru Smart Intercom."""

    VERSION = 1
    supports_options_flow = True

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
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
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
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

    async def _test_credentials(self, username: str, password: str) -> None:
        """Validate credentials."""
        session = async_create_clientsession(self.hass)
        client = DomruApiClient(
            username=username,
            password=password,
            session=session,
        )
        await client.async_authenticate()

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DomruOptionsFlowHandler:
        """Create the options flow."""
        return DomruOptionsFlowHandler(config_entry)


class DomruOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Dom.ru Smart Intercom."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

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
                        default=self.config_entry.options.get(
                            CONF_CAMERA_STREAM_CACHE, False
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_CAMERA_STREAM_CACHE_TIME,
                        default=self.config_entry.options.get(
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
                },
            ),
        )
