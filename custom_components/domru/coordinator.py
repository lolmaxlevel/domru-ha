"""DataUpdateCoordinator for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DomruApiClientAuthenticationError,
    DomruApiClientError,
)

if TYPE_CHECKING:
    from .data import DomruConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class DomruDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: DomruConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            return await self.config_entry.runtime_data.client.async_get_data()
        except DomruApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except DomruApiClientError as exception:
            raise UpdateFailed(exception) from exception
