"""Services for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

SERVICE_REFRESH_EVENTS = "refresh_events"
SERVICE_TEST_SIP_CALL = "test_sip_call"
SERVICE_ANSWER_CALL = "answer_call"
SERVICE_REJECT_CALL = "reject_call"

SERVICE_REFRESH_EVENTS_SCHEMA = vol.Schema({})
SERVICE_TEST_SIP_CALL_SCHEMA = vol.Schema({})
SERVICE_ANSWER_CALL_SCHEMA = vol.Schema({})
SERVICE_REJECT_CALL_SCHEMA = vol.Schema({})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Dom.ru integration."""

    async def handle_refresh_events(_: ServiceCall) -> None:
        """Handle the refresh events service call."""
        # Get all config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            if entry.runtime_data and entry.runtime_data.coordinator:
                await entry.runtime_data.coordinator.async_request_refresh()

    async def handle_test_sip_call(_: ServiceCall) -> None:
        """Handle the test SIP call service - simulates incoming call."""
        # Get all config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            if entry.runtime_data and entry.runtime_data.sip_client:
                sip_client = entry.runtime_data.sip_client

                # Simulate incoming call
                sip_client.simulate_incoming_call()
                return

        # If no SIP client found, log warning
        LOGGER.warning(
            "No SIP client found to test - SIP might be disabled or not configured"
        )

    async def handle_answer_call(_: ServiceCall) -> None:
        """Handle the answer call service."""
        # Get all config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            if entry.runtime_data and entry.runtime_data.sip_client:
                sip_client = entry.runtime_data.sip_client

                # Answer the call
                if sip_client.answer_call():
                    LOGGER.info("Call answered via service")
                    return
                LOGGER.warning("No incoming call to answer")
                return

        LOGGER.warning("No SIP client found - SIP might be disabled or not configured")

    async def handle_reject_call(_: ServiceCall) -> None:
        """Handle the reject call service."""
        # Get all config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            if entry.runtime_data and entry.runtime_data.sip_client:
                sip_client = entry.runtime_data.sip_client

                # Reject the call
                if sip_client.reject_call():
                    LOGGER.info("Call rejected via service")
                    return
                LOGGER.warning("No incoming call to reject")
                return

        LOGGER.warning("No SIP client found - SIP might be disabled or not configured")

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_EVENTS,
        handle_refresh_events,
        schema=SERVICE_REFRESH_EVENTS_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_SIP_CALL,
        handle_test_sip_call,
        schema=SERVICE_TEST_SIP_CALL_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ANSWER_CALL,
        handle_answer_call,
        schema=SERVICE_ANSWER_CALL_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REJECT_CALL,
        handle_reject_call,
        schema=SERVICE_REJECT_CALL_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Dom.ru services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_EVENTS)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_SIP_CALL)
    hass.services.async_remove(DOMAIN, SERVICE_ANSWER_CALL)
    hass.services.async_remove(DOMAIN, SERVICE_REJECT_CALL)
