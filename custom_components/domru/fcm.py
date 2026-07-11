"""FCM listener for realtime Dom.ru intercom call notifications."""

from __future__ import annotations

import asyncio
import importlib
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

try:
    from .api import DomruApiClient
    from .const import (
        CONF_FCM_CREDENTIALS,
        FCM_API_KEY,
        FCM_APP_ID,
        FCM_BUNDLE_ID,
        FCM_PROJECT_ID,
        FCM_SENDER_ID,
        LOGGER,
        SIGNAL_DOORBELL,
    )
except ImportError:  # pragma: no cover - used by standalone unit-test loading
    import logging

    DomruApiClient = Any
    CONF_FCM_CREDENTIALS = "fcm_credentials"
    FCM_PROJECT_ID = "ntk-myhome"
    FCM_APP_ID = "1:369367231553:android:323a999f9f228a40"
    FCM_SENDER_ID = "369367231553"
    FCM_API_KEY = "AIzaSyB_26K8ZB7iu7qZBpBf5c4NLgvTC3Yrgpk"
    FCM_BUNDLE_ID = "ru.inetra.intercom"
    LOGGER = logging.getLogger(__name__)
    SIGNAL_DOORBELL = "domru_doorbell"

FCM_WATCHDOG_INTERVAL = timedelta(minutes=2)

_PUSH_TYPE_EVENT = {
    "CALL_INCOMING": "ring",
    "CALL_END_ANSWERED_MOBILE": "ended",
    "CALL_END_UNKNOWN": "ended",
}

_PUSH_TYPE_END_REASON = {
    "CALL_END_ANSWERED_MOBILE": "answered_elsewhere",
    "CALL_END_UNKNOWN": "unknown",
}


def fcm_event_from_notification(notification: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalized doorbell event from an FCM data notification."""
    data = (notification or {}).get("data") or {}
    push_type = data.get("PushType") or data.get("google.c.a.m_l")
    event_type = _PUSH_TYPE_EVENT.get(push_type)
    if not event_type:
        return None

    attributes: dict[str, Any] = {
        "gate_name": data.get("GateName"),
        "apartment": data.get("Apartment"),
        "call_id": data.get("Call-ID"),
        "allow_open": data.get("AllowOpen"),
        "call_started": data.get("CallStarted"),
        "call_invalidated": data.get("CallInvalidated"),
    }
    if event_type == "ended":
        attributes["reason"] = _PUSH_TYPE_END_REASON.get(push_type, "unknown")

    return {
        "event_type": event_type,
        "place_id": str(data.get("PlaceId") or ""),
        "access_control_id": str(data.get("AccessControlId") or ""),
        "attributes": attributes,
    }


class DomruFcmListener:
    """Keep an FCM connection open and emit normalized intercom call events."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DomruApiClient,
        installation_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_token_ready: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the listener."""
        self._hass = hass
        self._entry = entry
        self._api = api
        self._installation_id = installation_id
        self._on_event = on_event
        self._on_token_ready = on_token_ready
        self._client: Any = None
        self._watchdog_unsub: Callable[[], None] | None = None
        self._connect_lock = asyncio.Lock()
        self._reconnecting = False
        self._stopped = True
        self.fcm_token: str | None = None

    async def async_start(self) -> None:
        """Connect to FCM and start watchdog checks."""
        self._stopped = False
        await self._async_connect()
        if not self._stopped and self._watchdog_unsub is None:
            self._watchdog_unsub = async_track_time_interval(
                self._hass,
                self._async_watchdog,
                FCM_WATCHDOG_INTERVAL,
            )

    async def _async_connect(self) -> None:
        """Create the FCM client, register the token, and start receiving pushes."""
        async with self._connect_lock:
            await self._async_connect_locked()

    async def _async_connect_locked(self) -> None:  # noqa: PLR0911
        """Create the FCM client while holding the connection lock."""
        if self._stopped:
            return

        try:
            firebase_messaging = await self._hass.async_add_executor_job(
                importlib.import_module,
                "firebase_messaging",
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.warning(
                "FCM listener disabled: firebase-messaging is unavailable (%s)",
                err,
            )
            return

        if self._stopped:
            return

        try:
            credentials = self._entry.data.get(CONF_FCM_CREDENTIALS)
            LOGGER.info(
                "FCM firebase-messaging module loaded module=%s version=%s "
                "file=%s stored_credentials=%s",
                getattr(firebase_messaging, "__name__", "firebase_messaging"),
                getattr(firebase_messaging, "__version__", "unknown"),
                getattr(firebase_messaging, "__file__", "unknown"),
                "yes" if credentials else "no",
            )
            register_config = firebase_messaging.FcmRegisterConfig(
                project_id=FCM_PROJECT_ID,
                app_id=FCM_APP_ID,
                api_key=FCM_API_KEY,
                messaging_sender_id=FCM_SENDER_ID,
                bundle_id=FCM_BUNDLE_ID,
            )
            client = firebase_messaging.FcmPushClient(
                self._on_notification,
                register_config,
                credentials,
                self._on_credentials_updated,
                config=firebase_messaging.FcmPushClientConfig(
                    abort_on_sequential_error_count=None
                ),
            )
            if client is None:
                LOGGER.warning(
                    "FCM listener disabled: firebase_messaging.FcmPushClient "
                    "returned no FCM client (module=%s version=%s file=%s)",
                    getattr(firebase_messaging, "__name__", "firebase_messaging"),
                    getattr(firebase_messaging, "__version__", "unknown"),
                    getattr(firebase_messaging, "__file__", "unknown"),
                )
                return
            self._client = client
            fcm_token = await client.checkin_or_register()
            if self._stopped:
                with suppress(Exception):
                    await client.stop()
                return

            self._client = client
            self.fcm_token = fcm_token
            LOGGER.info(
                "FCM check-in returned token token_length=%d",
                len(fcm_token),
            )
            token_registered = await self._api.register_push_device(
                fcm_token,
                self._installation_id,
            )
            if token_registered:
                LOGGER.info("FCM push token registration succeeded")
            else:
                LOGGER.warning("FCM push token registration failed")
            if self._stopped:
                with suppress(Exception):
                    await client.stop()
                return

            await client.start()
            if self._stopped:
                with suppress(Exception):
                    await client.stop()
                return

            LOGGER.info("FCM intercom listener started")
            if token_registered and self._on_token_ready:
                self._on_token_ready(fcm_token)
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("Failed to start FCM listener: %s", err, exc_info=True)
            self._client = None

    async def _async_watchdog(self, _now: Any = None) -> None:
        """Reconnect if the FCM receiver is no longer active."""
        if self._stopped:
            return
        if self._reconnecting:
            return
        client = self._client
        if client is not None and client.is_started():
            return

        self._reconnecting = True
        try:
            LOGGER.warning("FCM listener is inactive; reconnecting")
            await self._async_disconnect()
            await self._async_connect()
        finally:
            self._reconnecting = False

    async def _async_disconnect(self) -> None:
        """Stop the current FCM client without touching the watchdog."""
        client, self._client = self._client, None
        if client is not None:
            with suppress(Exception):
                await client.stop()

    async def async_stop(self) -> None:
        """Stop watchdog checks and close the FCM connection."""
        self._stopped = True
        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
            self._watchdog_unsub = None
        await self._async_disconnect()

    @callback
    def _on_credentials_updated(self, credentials: dict[str, Any], *_: Any) -> None:
        """Persist FCM credentials in the config entry."""
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_FCM_CREDENTIALS: credentials},
        )

    @callback
    def _on_notification(
        self,
        notification: dict[str, Any],
        _persistent_id: str,
        *_: Any,
    ) -> None:
        """Normalize an FCM push and forward it through Home Assistant."""
        event = fcm_event_from_notification(notification)
        if event is None:
            data = (notification or {}).get("data") or {}
            LOGGER.debug(
                "Ignoring unsupported FCM PushType %s",
                data.get("PushType") or data.get("google.c.a.m_l"),
            )
            return

        async_dispatcher_send(self._hass, SIGNAL_DOORBELL, event)
        if self._on_event:
            self._on_event(event)
