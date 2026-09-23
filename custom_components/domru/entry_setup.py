"""Config-entry setup boundary for Dom.ru authentication and API failures."""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import (
    DomruApiClient,
    DomruApiClientAuthenticationError,
    DomruApiClientCommunicationError,
    DomruApiClientError,
)
from .const import CONF_ACCESS_TOKEN, CONF_OPERATOR_ID, CONF_REFRESH_TOKEN


def persist_auth_update(
    hass: Any,
    entry: Any,
    access_token: str,
    refresh_token: str,
    operator_id: str | int,
) -> None:
    """Persist rotated credentials without discarding other entry data."""
    data = {
        **entry.data,
        CONF_ACCESS_TOKEN: access_token,
        CONF_REFRESH_TOKEN: refresh_token,
        CONF_OPERATOR_ID: operator_id,
    }
    if data != entry.data:
        hass.config_entries.async_update_entry(entry, data=data)


async def async_load_initial_data(client: Any) -> dict[str, Any]:
    """Authenticate and load required data with Home Assistant failure semantics."""
    try:
        await client.async_authenticate()
        return await client.async_get_data()
    except DomruApiClientAuthenticationError as exception:
        raise ConfigEntryAuthFailed(exception) from exception
    except (
        DomruApiClientCommunicationError,
        DomruApiClientError,
    ) as exception:
        raise ConfigEntryNotReady(str(exception)) from exception


async def async_create_client_and_load_data(
    hass: Any,
    entry: Any,
    session: Any,
) -> tuple[DomruApiClient, dict[str, Any]]:
    """Create a persistence-aware API client and load required initial data."""
    client = DomruApiClient(
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        session=session,
        access_token=(
            entry.data.get(CONF_ACCESS_TOKEN) or entry.data.get(CONF_REFRESH_TOKEN)
        ),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        operator_id=entry.data.get(CONF_OPERATOR_ID),
        on_auth_update=partial(persist_auth_update, hass, entry),
    )
    initial_data = await async_load_initial_data(client)
    return client, initial_data
