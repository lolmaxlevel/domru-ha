"""
Custom integration to integrate Dom.ru Smart Intercom with Home Assistant.

For more details about this integration, please refer to
https://github.com/yourusername/domru-ha
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.loader import async_get_loaded_integration

from . import services
from .api import (
    DomruApiClient,
    DomruApiClientCommunicationError,
    DomruApiClientError,
)
from .const import (
    CONF_OPERATOR_ID,
    CONF_REFRESH_TOKEN,
    CONF_SIP_ENABLED,
    CONF_SIP_HOST_IP,
    CONF_SIP_LOCAL_IP,
    CONF_SIP_LOCAL_PORT,
    CONF_SIP_MODE,
    CONF_SIP_POLL_INTERVAL,
    DEFAULT_SIP_POLL_INTERVAL,
    DOMAIN,
    LOGGER,
    SIGNAL_CALL_STATUS_UPDATE,
    SIGNAL_COURIER_AUTO_OPEN_UPDATE,
    SIP_MODE_ON_DEMAND,
    SIP_MODE_PERSISTENT,
)
from .coordinator import DomruDataUpdateCoordinator
from .data import DomruData
from .door import async_open_door
from .sip import DomruSipClient

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import DomruConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.CAMERA,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    client = DomruApiClient(
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        session=async_get_clientsession(hass),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        operator_id=entry.data.get(CONF_OPERATOR_ID),
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
    event_poller: asyncio.Task[None] | None = None

    # Check if SIP is enabled in options (default: True)
    sip_enabled = entry.options.get(CONF_SIP_ENABLED, True)

    if not sip_enabled:
        LOGGER.info("SIP is disabled in options")
    else:
        try:
            sip_client, event_poller = await _setup_sip(hass, entry, client)
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
        ):  # pylint: disable=broad-except
            LOGGER.warning("Failed to initialize SIP client", exc_info=True)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected failure while initializing SIP client")

    entry.runtime_data = DomruData(
        client=client,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
        sip_client=sip_client,
        event_poller=event_poller,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    _remove_legacy_event_entity(hass, entry)
    _remove_legacy_binary_sensor_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register services
    await services.async_setup_services(hass)

    return True


def _remove_legacy_event_entity(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> None:
    """Remove the old intercom event entity from existing installs."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        Platform.EVENT,
        DOMAIN,
        f"{entry.entry_id}_intercom_events",
    )
    if entity_id:
        entity_registry.async_remove(entity_id)


def _remove_legacy_binary_sensor_entities(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> None:
    """Remove binary sensors that are no longer exposed."""
    entity_registry = er.async_get(hass)
    for key in ("has_cameras", "has_access_controls", "recent_call"):
        entity_id = entity_registry.async_get_entity_id(
            Platform.BINARY_SENSOR,
            DOMAIN,
            f"{entry.entry_id}_{key}",
        )
        if entity_id:
            entity_registry.async_remove(entity_id)


async def _setup_sip(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    client: DomruApiClient,
) -> tuple[DomruSipClient | None, asyncio.Task[None] | None]:
    """
    Set up SIP client and optional event poller.

    Returns (sip_client, event_poller_task).
    """
    # Generate installation ID from Home Assistant instance ID
    instance_id = hass.data.get("core.uuid") or str(uuid.uuid4())
    installation_id = _generate_installation_id(instance_id)

    LOGGER.info("Getting SIP credentials with installation_id: %s", installation_id)

    # Get SIP credentials
    sip_credentials = await client.async_get_sip_credentials(installation_id)

    if not (
        sip_credentials.get("login")
        and sip_credentials.get("password")
        and sip_credentials.get("realm")
    ):
        LOGGER.warning(
            "SIP credentials not available "
            "(login: %s, password: %s, realm: %s), "
            "incoming calls disabled",
            bool(sip_credentials.get("login")),
            bool(sip_credentials.get("password")),
            bool(sip_credentials.get("realm")),
        )
        return None, None

    LOGGER.info(
        "SIP credentials received - login: %s, realm: %s",
        sip_credentials.get("login"),
        sip_credentials.get("realm"),
    )

    # Get SIP settings from options
    local_ip = entry.options.get(CONF_SIP_LOCAL_IP) or None
    sip_host_ip = entry.options.get(CONF_SIP_HOST_IP) or None
    local_port = entry.options.get(CONF_SIP_LOCAL_PORT, 5060)
    sip_mode = entry.options.get(CONF_SIP_MODE, SIP_MODE_PERSISTENT)
    poll_interval = entry.options.get(CONF_SIP_POLL_INTERVAL, DEFAULT_SIP_POLL_INTERVAL)

    if local_ip == "":
        local_ip = None
    if sip_host_ip == "":
        sip_host_ip = None

    realm = sip_credentials["realm"]

    LOGGER.info(
        "Using SIP mode=%s realm=%s local=%s:%s registrar_ip_override=%s",
        sip_mode,
        realm,
        local_ip or "auto",
        local_port,
        sip_host_ip or "-",
    )

    # Create call event callback
    def on_call_callback(call_data: dict[str, Any]) -> None:
        """Handle SIP call events."""
        event_type = call_data.get("event")
        LOGGER.info("SIP event: %s - %s", event_type, call_data)

        if event_type == "incoming_call":
            hass.bus.async_fire(
                f"{DOMAIN}_incoming_call",
                {
                    "from": call_data.get("from", "Unknown"),
                    "call_id": call_data.get("call_id", ""),
                },
            )
            _schedule_courier_auto_open(hass, entry)
        elif event_type == "call_answered":
            hass.bus.async_fire(
                f"{DOMAIN}_call_answered",
                {"call_id": call_data.get("call_id", "")},
            )
        elif event_type == "call_ended":
            hass.bus.async_fire(f"{DOMAIN}_call_ended", {})

        # Signal sensor updates
        async_dispatcher_send(hass, SIGNAL_CALL_STATUS_UPDATE)

    sip_client = DomruSipClient(
        realm=realm,
        username=sip_credentials["login"],
        password=sip_credentials["password"],
        local_ip=local_ip,
        local_port=local_port,
        on_call_callback=on_call_callback,
        registration_mode=sip_mode,
        server_ip=sip_host_ip,
    )

    # Start SIP client
    await sip_client.start()
    LOGGER.info("SIP client started successfully (mode: %s)", sip_mode)

    # In on-demand mode, start event poller to detect incoming calls
    event_poller = None
    if sip_mode == SIP_MODE_ON_DEMAND:
        event_poller = asyncio.create_task(
            _poll_events_loop(hass, client, sip_client, poll_interval)
        )
        LOGGER.info("Event poller started (interval: %d seconds)", poll_interval)

    return sip_client, event_poller


def _schedule_courier_auto_open(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> None:
    """Open the door once when courier auto-open mode is armed."""
    data = getattr(entry, "runtime_data", None)
    if data is None:
        return

    if not data.courier_auto_open_enabled or data.courier_auto_open_in_progress:
        return

    data.courier_auto_open_in_progress = True
    hass.async_create_task(_async_courier_auto_open(hass, entry))


async def _async_courier_auto_open(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> None:
    """Consume courier auto-open mode by opening the door once."""
    data = entry.runtime_data
    try:
        if data.sip_client:
            data.sip_client.answer_and_hangup()

        selected_access_control_id = _selected_courier_access_control_id(
            data.coordinator.data,
            data.courier_auto_open_access_control_id,
        )
        await async_open_door(
            data.client,
            data.coordinator,
            access_control_id=selected_access_control_id,
        )
        await data.coordinator.async_request_refresh()
        LOGGER.info("Courier auto-open consumed successfully")
    except (DomruApiClientError, DomruApiClientCommunicationError):
        LOGGER.warning("Courier auto-open failed", exc_info=True)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected courier auto-open failure")
    finally:
        data.courier_auto_open_enabled = False
        data.courier_auto_open_in_progress = False
        async_dispatcher_send(hass, SIGNAL_CALL_STATUS_UPDATE)
        async_dispatcher_send(hass, SIGNAL_COURIER_AUTO_OPEN_UPDATE)


async def _poll_events_loop(
    hass: HomeAssistant,
    client: DomruApiClient,
    sip_client: DomruSipClient,
    interval: int,
) -> None:
    """
    Poll API events to detect incoming calls for on-demand SIP.

    When a call event is detected, triggers immediate SIP registration
    so the server can route the INVITE to us.
    """
    last_event_id: str | None = None
    call_event_types = {
        "accessControlCallAccepted",
        "accessControlCallRejected",
        "accessControlCallMissed",
        "accessControlCallIncoming",
    }

    LOGGER.info("Event polling loop started (interval=%ds)", interval)

    while True:
        try:
            await asyncio.sleep(interval)

            # Skip if HA is shutting down
            if hass.is_stopping:
                break

            # Don't poll if already in a call
            if sip_client.call_status != "idle":
                continue

            # Fetch latest events
            events = await client.async_get_events(
                client._place_id,  # noqa: SLF001
                limit=5,
            )

            if not events:
                continue

            latest = events[0]
            event_id = str(latest.get("id", ""))
            event_type = latest.get("eventTypeName", "")

            # Check if this is a new call-related event
            if event_id and event_id != last_event_id:
                last_event_id = event_id

                if event_type in call_event_types:
                    LOGGER.info(
                        "Detected call event via API: %s (id=%s), "
                        "triggering SIP registration",
                        event_type,
                        event_id,
                    )
                    sip_client.register_now()

        except asyncio.CancelledError:
            LOGGER.info("Event polling loop cancelled")
            break
        except Exception:  # noqa: BLE001
            LOGGER.debug("Error in event polling loop", exc_info=True)
            # Continue polling even on errors
            await asyncio.sleep(interval)


def _generate_installation_id(instance_id: str) -> str:
    """Generate installation ID based on Home Assistant instance ID."""
    h = hashlib.sha256(instance_id.encode()).hexdigest()
    return str(
        uuid.UUID(
            f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-"
            f"{format((int(h[16], 16) & 0x3) | 0x8, 'x')}{h[17:20]}-{h[20:32]}"
        )
    )


def _selected_courier_access_control_id(
    coordinator_data: dict[str, Any],
    selected_access_control_id: str | int | None,
) -> str | int | None:
    """Return the selected courier door if it still exists."""
    if selected_access_control_id is None:
        return None

    access_controls = coordinator_data.get("access_controls", [])
    if not isinstance(access_controls, list):
        return None

    for access_control in access_controls:
        if not isinstance(access_control, dict):
            continue
        access_control_id = access_control.get("id")
        if str(access_control_id) == str(selected_access_control_id):
            return access_control_id

    return None


async def async_unload_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    # Cancel event poller if running
    if entry.runtime_data.event_poller:
        entry.runtime_data.event_poller.cancel()
        with suppress(asyncio.CancelledError):
            await entry.runtime_data.event_poller
        LOGGER.info("Event poller stopped")

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
