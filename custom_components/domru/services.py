"""Services for Dom.ru Smart Intercom."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

SERVICE_REFRESH_EVENTS = "refresh_events"

SERVICE_REFRESH_EVENTS_SCHEMA = vol.Schema({})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Dom.ru integration."""

    async def handle_refresh_events(call: ServiceCall) -> None:
        """Handle the refresh events service call."""
        # Get all config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            if entry.runtime_data and entry.runtime_data.coordinator:
                await entry.runtime_data.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_EVENTS,
        handle_refresh_events,
        schema=SERVICE_REFRESH_EVENTS_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Dom.ru services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_EVENTS)

