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
from .access_control import (
    access_control_target,
    access_control_targets,
    selected_access_control,
    selected_access_control_matches,
    valid_access_controls,
)
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
from .sip import DomruSipClient, SipAccount
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

    # Load initial data to set IDs and all FCM access-control targets.
    initial_data = await client.async_get_data()

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
                initial_data.get("access_controls", []),
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
        installation_id=installation_id,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()
    if sip_client:
        _sync_sip_access_control_targets(entry)
        entry.async_on_unload(
            coordinator.async_add_listener(
                lambda: _sync_sip_access_control_targets(entry)
            )
        )

    _remove_legacy_event_entity(hass, entry)
    _remove_legacy_binary_sensor_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register services
    await services.async_setup_services(hass)

    if sip_enabled:
        fcm_listener = _setup_fcm_listener(hass, entry, client, installation_id)
        entry.runtime_data.fcm_listener = fcm_listener
        entry.runtime_data.fcm_start_task = hass.async_create_task(
            fcm_listener.async_start()
        )

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
    discovered_access_controls: Any,
) -> tuple[DomruSipClient | None, asyncio.Task[None] | None]:
    """
    Set up SIP client and optional event poller.

    Returns (sip_client, event_poller_task).
    """
    LOGGER.info("Getting SIP credentials with installation_id: %s", installation_id)

    sip_accounts = await _async_get_sip_accounts(
        client,
        installation_id,
        discovered_access_controls,
    )
    primary_target = next(iter(sip_accounts), None)
    if primary_target is not None:
        primary_account = sip_accounts[primary_target]
        sip_credentials = {
            "login": primary_account.username,
            "password": primary_account.password,
            "realm": primary_account.realm,
        }
    else:
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
            _schedule_courier_auto_open_for_sip_call(hass, entry, sip_client)
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
        place_id=primary_target[0] if primary_target else client.place_id,
        access_control_id=(
            primary_target[1] if primary_target else client.access_control_id
        ),
        access_control_targets=(
            set(sip_accounts)
            if sip_accounts
            else access_control_targets(discovered_access_controls)
        ),
        access_control_accounts=sip_accounts,
    )

    # Start SIP client
    await sip_client.start()
    LOGGER.info("SIP client started successfully (mode: %s)", sip_mode)

    event_poller = None
    if sip_mode == SIP_MODE_ON_DEMAND:
        LOGGER.info("SIP on-demand mode will register when an FCM call push arrives")

    return sip_client, event_poller


async def _async_get_sip_accounts(
    client: DomruApiClient,
    installation_id: str,
    discovered_access_controls: Any,
) -> dict[tuple[str, str], SipAccount]:
    """Load per-door SIP accounts for one serialized on-demand SIP client."""
    accounts: dict[tuple[str, str], SipAccount] = {}
    for access_control in valid_access_controls(discovered_access_controls):
        target = access_control_target(access_control)
        if target is None:
            continue
        credentials = await client.async_get_sip_credentials(
            installation_id,
            place_id=target[0],
            access_control_id=target[1],
        )
        if not all(credentials.get(key) for key in ("login", "password", "realm")):
            LOGGER.warning(
                "SIP credentials unavailable for place_id=%s access_control_id=%s",
                target[0],
                target[1],
            )
            continue
        accounts[target] = SipAccount(
            realm=credentials["realm"],
            username=credentials["login"],
            password=credentials["password"],
        )
    return accounts


def _sync_sip_access_control_targets(entry: DomruConfigEntry) -> None:
    """Keep the single SIP client aligned with coordinator-discovered doors."""
    data = entry.runtime_data
    if not data.sip_client:
        return
    data.sip_client.set_access_control_targets(
        access_control_targets((data.coordinator.data or {}).get("access_controls", []))
    )


def _setup_fcm_listener(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    client: DomruApiClient,
    installation_id: str,
) -> DomruFcmListener:
    """Set up the account-wide FCM listener."""
    fcm_listener: DomruFcmListener | None = None

    def on_fcm_event(event: dict[str, Any]) -> None:
        """Handle normalized FCM doorbell events."""
        event_type = event.get("event_type")
        attributes = event.get("attributes") or {}
        data = getattr(entry, "runtime_data", None)
        sip_client = getattr(data, "sip_client", None) if data else None
        place_id = event.get("place_id")
        access_control_id = event.get("access_control_id")
        sip_target_matches = bool(
            sip_client
            and sip_client.matches_access_control(
                place_id,
                access_control_id,
            )
        )
        courier_target_matches = bool(
            data
            and selected_access_control_matches(
                (data.coordinator.data or {}).get("access_controls", []),
                data.courier_auto_open_access_control_id,
                place_id,
                access_control_id,
            )
        )

        LOGGER.info(
            "FCM doorbell event type=%s place_id=%s access_control_id=%s",
            event_type,
            place_id,
            access_control_id,
        )
        if event_type == "ring":
            sip_session_started = False
            if sip_target_matches:
                call_id = str(attributes.get("call_id") or "")
                fcm_token = fcm_listener.fcm_token if fcm_listener else None
                sip_session_started = sip_client.register_for_incoming_call(
                    call_id=call_id or None,
                    fcm_token=fcm_token,
                    place_id=place_id,
                    access_control_id=access_control_id,
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
            if courier_target_matches and sip_session_started:
                _schedule_courier_auto_open(hass, entry)
        elif event_type == "ended":
            call_id = str(attributes.get("call_id") or "")
            if sip_target_matches and sip_client.is_current_fcm_call(
                call_id,
                place_id,
                access_control_id,
            ):
                sip_client.hangup_call()
                sip_client.end_fcm_call_session()
            hass.bus.async_fire(
                f"{DOMAIN}_call_ended",
                {
                    "source": "fcm",
                    "call_id": call_id,
                    "place_id": event.get("place_id", ""),
                    "access_control_id": event.get("access_control_id", ""),
                },
            )

        async_dispatcher_send(hass, SIGNAL_CALL_STATUS_UPDATE)

    fcm_listener = DomruFcmListener(
        hass,
        entry,
        client,
        installation_id,
        on_event=on_fcm_event,
    )
    return fcm_listener


def _schedule_courier_auto_open_for_sip_call(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
    sip_client: DomruSipClient,
) -> None:
    """Schedule courier auto-open only when the SIP call target is unambiguous."""
    data = entry.runtime_data
    if not data.courier_auto_open_enabled:
        return

    access_controls = (data.coordinator.data or {}).get("access_controls", [])
    current_target = sip_client.current_fcm_target
    if current_target is not None:
        if selected_access_control_matches(
            access_controls,
            data.courier_auto_open_access_control_id,
            current_target[0],
            current_target[1],
        ):
            _schedule_courier_auto_open(hass, entry)
        return

    targets = access_control_targets(access_controls)
    if len(targets) == 1:
        _schedule_courier_auto_open(hass, entry)
        return

    LOGGER.warning(
        "Courier auto-open remains armed because an incoming SIP call could not "
        "be matched to one of %d access controls",
        len(targets),
    )


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

    access_control = selected_access_control(
        coordinator_data.get("access_controls", []),
        selected_access_control_id,
    )
    return access_control.get("id") if access_control else None


async def async_unload_entry(
    hass: HomeAssistant,
    entry: DomruConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    if entry.runtime_data.fcm_start_task:
        if not entry.runtime_data.fcm_start_task.done():
            entry.runtime_data.fcm_start_task.cancel()
        with suppress(asyncio.CancelledError):
            await entry.runtime_data.fcm_start_task
        entry.runtime_data.fcm_start_task = None

    if entry.runtime_data.fcm_listener:
        await entry.runtime_data.fcm_listener.async_stop()
        LOGGER.info("FCM listener stopped")

        if entry.runtime_data.installation_id:
            await entry.runtime_data.client.unregister_push_device(
                entry.runtime_data.installation_id
            )

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
