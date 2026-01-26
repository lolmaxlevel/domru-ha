"""
Custom integration to integrate Dom.ru Smart Intercom with Home Assistant.

For more details about this integration, please refer to
https://github.com/yourusername/domru-ha
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from . import services
from .api import (
    DomruApiClient,
    DomruApiClientCommunicationError,
    DomruApiClientError,
)
from .const import (
    CONF_SIP_ENABLED,
    CONF_SIP_LOCAL_IP,
    CONF_SIP_LOCAL_PORT,
    DOMAIN,
    LOGGER,
)
from .coordinator import DomruDataUpdateCoordinator
from .data import DomruData
from .sip import DomruSipClient

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import DomruConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.EVENT,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    client = DomruApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )

    # Authenticate first
    await client.async_authenticate()

    # Load initial data to set place_id and access_control_id
    await client.async_get_data()

    coordinator = DomruDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(hours=1),
    )

    # Initialize SIP client for incoming calls
    sip_client = None

    # Check if SIP is enabled in options (default: True)
    sip_enabled = entry.options.get(CONF_SIP_ENABLED, True)

    if not sip_enabled:
        LOGGER.info("SIP is disabled in options")
    else:
        try:
            # Generate installation ID from Home Assistant instance ID
            instance_id = hass.data.get("core.uuid") or str(uuid.uuid4())
            installation_id = _generate_installation_id(instance_id)

            LOGGER.info(
                "Getting SIP credentials with installation_id: %s", installation_id
            )

            # Get SIP credentials
            sip_credentials = await client.async_get_sip_credentials(installation_id)

            if (
                sip_credentials.get("login")
                and sip_credentials.get("password")
                and sip_credentials.get("realm")
            ):
                LOGGER.info(
                    "SIP credentials received - login: %s, realm: %s",
                    sip_credentials.get("login"),
                    sip_credentials.get("realm"),
                )

                # Create callback for incoming calls
                def on_call_callback(call_data: dict) -> None:
                    """Handle incoming call."""
                    event_type = call_data.get("event")
                    LOGGER.info("SIP event: %s - %s", event_type, call_data)

                    # Trigger event
                    if event_type == "incoming_call":
                        hass.bus.async_fire(
                            f"{DOMAIN}_incoming_call",
                            {
                                "from": call_data.get("from", "Unknown"),
                                "call_id": call_data.get("call_id", ""),
                            },
                        )
                    elif event_type == "call_answered":
                        hass.bus.async_fire(
                            f"{DOMAIN}_call_answered",
                            {
                                "call_id": call_data.get("call_id", ""),
                            },
                        )
                    elif event_type == "call_ended":
                        hass.bus.async_fire(
                            f"{DOMAIN}_call_ended",
                            {},
                        )

                    # Update all sensor entities to reflect new call status
                    for entity_id in hass.states.async_entity_ids("sensor"):
                        if entity_id.startswith(f"sensor.{DOMAIN}"):
                            entity = hass.data.get("entity_registry")
                            if entity:
                                hass.async_create_task(
                                    hass.helpers.entity_component.async_update_entity(
                                        entity_id
                                    )
                                )

                # Get SIP settings from options
                local_ip = entry.options.get(CONF_SIP_LOCAL_IP) or None
                local_port = entry.options.get(CONF_SIP_LOCAL_PORT, 5060)

                # Empty string means auto-detect
                if local_ip == "":
                    local_ip = None

                sip_client = DomruSipClient(
                    realm=sip_credentials["realm"],
                    username=sip_credentials["login"],
                    password=sip_credentials["password"],
                    local_ip=local_ip,
                    local_port=local_port,
                    on_call_callback=on_call_callback,
                )

                # Start SIP client
                await sip_client.start()
                LOGGER.info("SIP client started successfully")
            else:
                LOGGER.warning(
                    "SIP credentials not available "
                    "(login: %s, password: %s, realm: %s), "
                    "incoming calls disabled",
                    bool(sip_credentials.get("login")),
                    bool(sip_credentials.get("password")),
                    bool(sip_credentials.get("realm")),
                )
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
        ):  # pylint: disable=broad-except
            LOGGER.warning("Failed to initialize SIP client", exc_info=True)

    entry.runtime_data = DomruData(
        client=client,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
        sip_client=sip_client,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register services
    await services.async_setup_services(hass)

    return True


def _generate_installation_id(instance_id: str) -> str:
    """Generate installation ID based on Home Assistant instance ID."""
    h = hashlib.sha256(instance_id.encode()).hexdigest()
    return str(
        uuid.UUID(
            f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-"
            f"{format((int(h[16], 16) & 0x3) | 0x8, 'x')}{h[17:20]}-{h[20:32]}"
        )
    )


async def async_unload_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    # Stop SIP client if running
    if entry.runtime_data.sip_client:
        try:
            await entry.runtime_data.sip_client.stop()
            LOGGER.info("SIP client stopped")
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
        ):  # pylint: disable=broad-except
            LOGGER.error("Error stopping SIP client", exc_info=True)

    # Unload services if this is the last entry
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) == 1:  # This is the last one
        await services.async_unload_services(hass)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
