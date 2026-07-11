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
    CONF_ACCESS_TOKEN,
    CONF_OPERATOR_ID,
    CONF_REFRESH_TOKEN,
    CONF_SIP_ENABLED,
    CONF_SIP_HOST_IP,
    CONF_SIP_LOCAL_IP,
    CONF_SIP_LOCAL_PORT,
    CONF_SIP_MODE,
    DEFAULT_SIP_MODE,
    DOMAIN,
    LOGGER,
    SIGNAL_CALL_STATUS_UPDATE,
    SIGNAL_COURIER_AUTO_OPEN_UPDATE,
    SIP_MODE_ON_DEMAND,
)
from .coordinator import DomruDataUpdateCoordinator
from .data import DomruData
from .door import async_open_door
from .fcm import DomruFcmListener
from .sip import DomruSipClient
from .sip_entities import async_answer_and_hangup_when_ready

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
        access_token=(
            entry.data.get(CONF_ACCESS_TOKEN) or entry.data.get(CONF_REFRESH_TOKEN)
        ),
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
    fcm_listener = None
    event_poller: asyncio.Task[None] | None = None
    instance_id = hass.data.get("core.uuid") or str(uuid.uuid4())
    installation_id = _generate_installation_id(instance_id)

    # Check if SIP is enabled in options (default: True)
    sip_enabled = entry.options.get(CONF_SIP_ENABLED, True)

    if not sip_enabled:
        LOGGER.info("SIP is disabled in options")
    else:
        try:
            sip_client, event_poller = await _setup_sip(
                hass,
                entry,
                client,
                installation_id,
            )
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
        fcm_listener=fcm_listener,
        event_poller=event_poller,
    )

    if sip_enabled:
        fcm_listener = _setup_fcm_listener(hass, entry, client, installation_id)
        entry.runtime_data.fcm_listener = fcm_listener
        hass.async_create_task(fcm_listener.async_start())

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
    installation_id: str,
) -> tuple[DomruSipClient | None, asyncio.Task[None] | None]:
    """
    Set up SIP client and optional event poller.

    Returns (sip_client, event_poller_task).
    """
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
    sip_mode = entry.options.get(CONF_SIP_MODE, DEFAULT_SIP_MODE)
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

    event_poller = None
    if sip_mode == SIP_MODE_ON_DEMAND:
        LOGGER.info("SIP on-demand mode will register when an FCM call push arrives")

    return sip_client, event_poller


def _setup_fcm_listener(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    client: DomruApiClient,
    installation_id: str,
) -> DomruFcmListener:
    """Set up the FCM listener and its one-shot SIP push binding."""
    fcm_listener: DomruFcmListener | None = None

    def on_fcm_event(event: dict[str, Any]) -> None:
        """Handle normalized FCM doorbell events."""
        event_type = event.get("event_type")
        attributes = event.get("attributes") or {}
        data = getattr(entry, "runtime_data", None)
        sip_client = getattr(data, "sip_client", None) if data else None

        LOGGER.info("FCM doorbell event: %s - %s", event_type, event)
        if event_type == "ring":
            if sip_client:
                call_id = str(attributes.get("call_id") or "")
                fcm_token = fcm_listener.fcm_token if fcm_listener else None
                sip_client.register_for_incoming_call(
                    call_id=call_id or None,
                    fcm_token=fcm_token,
                )
            hass.bus.async_fire(
                f"{DOMAIN}_incoming_call",
                {
                    "from": attributes.get("gate_name") or "FCM",
                    "call_id": attributes.get("call_id") or "",
                    "source": "fcm",
                    "place_id": event.get("place_id", ""),
                    "access_control_id": event.get("access_control_id", ""),
                },
            )
            _schedule_courier_auto_open(hass, entry)
        elif event_type == "ended":
            if sip_client:
                sip_client.hangup_call()
                sip_client.end_on_demand_session()
            hass.bus.async_fire(f"{DOMAIN}_call_ended", {"source": "fcm"})

        async_dispatcher_send(hass, SIGNAL_CALL_STATUS_UPDATE)

    def on_fcm_token_ready(fcm_token: str) -> None:
        """Prebind the push Contact once without enabling periodic SIP refresh."""
        data = getattr(entry, "runtime_data", None)
        sip_client = getattr(data, "sip_client", None) if data else None
        if sip_client:
            sip_client.install_fcm_push_binding(fcm_token)

    fcm_listener = DomruFcmListener(
        hass,
        entry,
        client,
        installation_id,
        on_event=on_fcm_event,
        on_token_ready=on_fcm_token_ready,
    )
    return fcm_listener


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
            await async_answer_and_hangup_when_ready(data.sip_client)

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
    if entry.runtime_data.fcm_listener:
        await entry.runtime_data.fcm_listener.async_stop()
        LOGGER.info("FCM listener stopped")

        instance_id = hass.data.get("core.uuid") or entry.entry_id
        installation_id = _generate_installation_id(instance_id)
        await entry.runtime_data.client.unregister_push_device(installation_id)

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
