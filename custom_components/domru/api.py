"""Dom.ru Smart Intercom API Client."""

from __future__ import annotations

import base64
import hashlib
import json as jsonlib
import logging
import uuid
from datetime import UTC, datetime
from json.decoder import JSONDecodeError
from typing import Any
from urllib.parse import quote, urljoin

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError

try:
    from async_timeout import timeout as async_timeout
except ModuleNotFoundError:
    from asyncio import timeout as async_timeout

try:
    from .const import (
        ANDROID_APP_VERSION_CODE,
        ANDROID_APP_VERSION_NAME,
        ANDROID_DEVICE_MANUFACTURER,
        ANDROID_DEVICE_MODEL,
        ANDROID_OS_VERSION,
    )
except ImportError:  # pragma: no cover - standalone unit-test loading
    ANDROID_APP_VERSION_CODE = "8090200"
    ANDROID_APP_VERSION_NAME = "8.9.2"
    ANDROID_DEVICE_MANUFACTURER = "Google"
    ANDROID_DEVICE_MODEL = "sdk_gphone64_x86_64"
    ANDROID_OS_VERSION = "14"

_LOGGER = logging.getLogger(__name__)

_DEVICE_INSTALLATIONS = (
    "api/mh-customer-device/mobile/public/v1/customers/device-installations"
)
_SUBSCRIBER_NOTIFICATIONS = "rest/v1/subscriberNotifications"


def _device_id(installation_id: str) -> str:
    """Return a stable Android-like device ID for FCM registration."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"domru-fcm-{installation_id}").hex[:16]


def _auth_response_data(result: Any) -> dict[str, Any]:
    """Return auth fields from a direct or wrapped API response."""
    if not isinstance(result, dict):
        return {}

    data = result.get("data")
    if isinstance(data, dict):
        return data

    return result


def _auth_value(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present auth value from possible API key spellings."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _response_list(result: Any, *keys: str) -> list[dict[str, Any]]:
    """Return a list of dicts from common API response wrappers."""
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _dict_value(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present value from possible API key spellings."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _place_from_subscriber_place(place_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the place object from v3 subscriber-place data."""
    place = place_data.get("place", place_data)
    return place if isinstance(place, dict) else None


def _empty_sip_credentials() -> dict[str, str]:
    """Return empty SIP credentials."""
    return {"login": "", "password": "", "realm": ""}


def _sip_credentials_from_response(result: Any) -> dict[str, str]:
    """Return SIP credentials from an API response."""
    if isinstance(result, dict):
        data = result.get("data", result)
        return {
            "login": data.get("login", ""),
            "password": data.get("password", ""),
            "realm": data.get("realm", ""),
        }
    return _empty_sip_credentials()


class DomruApiClientError(Exception):
    """Exception to indicate a general API error."""


class DomruApiClientCommunicationError(
    DomruApiClientError,
):
    """Exception to indicate a communication error."""


class DomruApiClientAuthenticationError(
    DomruApiClientError,
):
    """Exception to indicate an authentication error."""


class DomruApiClient:
    """Dom.ru Smart Intercom API Client."""

    BASE_URL = "https://myhome.proptech.ru/"
    # Full User-Agent from go-impl/pkg/domru/helpers/upstream_request.go
    USER_AGENT = (
        "Google sdkgphone64x8664 | Android 14 | erth | 8.9.2 (8090200) |  | "
        "null | 10c99d90-9899-4a25-926f-067b34bc4a7f | null"
    )
    # HTTP status codes
    HTTP_BAD_REQUEST = 400
    HTTP_UNAUTHORIZED = 401
    HTTP_FORBIDDEN = 403
    HTTP_INTERNAL_ERROR = 500
    HTTP_OK = 200
    HTTP_CREATED = 201
    HTTP_NO_CONTENT = 204
    # Error codes
    ERROR_TEMPORARY_CODE_FAILED = 6005

    def __init__(
        self,
        username: str | None,
        password: str | None,
        session: aiohttp.ClientSession,
        refresh_token: str | None = None,
        operator_id: str | int | None = None,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._access_token: str | None = None
        self._refresh_token = refresh_token
        self._operator_id = operator_id
        self._place_id: str | None = None
        self._access_control_id: str | None = None
        # Hash parameters from go-impl/pkg/auth/password.go
        self._hash2_prefix = "DigitalHomeNTK"
        self._secret = "789sdgHJs678wertv34712376"  # noqa: S105

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token."""
        return self._refresh_token

    @property
    def operator_id(self) -> str | int | None:
        """Return the current operator ID."""
        return self._operator_id

    def _get_hash1(self) -> str:
        """Generate hash1 (SHA1 of password in base64)."""
        password_bytes = self._password.encode("iso-8859-1")
        sha1_digest = hashlib.sha1(password_bytes).digest()  # noqa: S324
        return base64.b64encode(sha1_digest).decode("utf-8")

    def _get_hash2(self, timestamp: datetime) -> str:
        """Generate hash2 (MD5 of combined string)."""
        timestamp_str = timestamp.strftime("%Y%m%d%H%M%S")
        # From go-impl/pkg/auth/password.go
        combined = (
            f"{self._hash2_prefix}password{self._username}{self._password}"
            f"{timestamp_str}{self._secret}"
        )
        return hashlib.md5(combined.encode("utf-8")).hexdigest()  # noqa: S324

    async def async_authenticate(self) -> None:
        """Authenticate with the API using login and password."""
        await self._set_access_token()

    async def _set_access_token(self) -> None:
        """Set access token using login/password or refresh token."""
        if self._refresh_token is not None and self._operator_id is not None:
            # Try to refresh token first
            try:
                await self._refresh_access_token()
            except (
                DomruApiClientError,
                DomruApiClientCommunicationError,
            ):  # pylint: disable=broad-except
                _LOGGER.debug("Failed to refresh access token")
            else:
                return

        # Authenticate with login and password
        if self._username is not None and self._password is not None:
            timestamp = datetime.now(UTC)
            url = urljoin(self.BASE_URL, f"auth/v2/auth/{self._username}/password")
            json_data = {
                "login": str(self._username),
                "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hash1": self._get_hash1(),
                "hash2": self._get_hash2(timestamp=timestamp),
            }

            headers = {
                "Content-Type": "application/json; charset=UTF-8",
                "User-Agent": self.USER_AGENT,
            }

            result = await self._api_wrapper(
                url=url,
                method="POST",
                json=json_data,
                headers=headers,
                authenticated=False,
            )
            auth_data = _auth_response_data(result)

            self._access_token = _auth_value(auth_data, "accessToken", "access_token")
            self._refresh_token = _auth_value(
                auth_data, "refreshToken", "refresh_token"
            )
            self._operator_id = _auth_value(auth_data, "operatorId", "operator_id")

            if not self._access_token:
                msg = "No access token in response"
                raise DomruApiClientAuthenticationError(msg)
        else:
            msg = "No credentials provided"
            raise DomruApiClientAuthenticationError(msg)

    async def _refresh_access_token(self) -> None:
        """Refresh access token using refresh token."""
        url = urljoin(self.BASE_URL, "auth/v2/session/refresh")
        headers = {
            "Bearer": self._refresh_token,
            "Operator": str(self._operator_id),
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": self.USER_AGENT,
        }

        result = await self._api_wrapper(
            url=url,
            method="GET",
            headers=headers,
            authenticated=False,
        )
        auth_data = _auth_response_data(result)

        self._access_token = _auth_value(auth_data, "accessToken", "access_token")
        self._refresh_token = _auth_value(auth_data, "refreshToken", "refresh_token")
        self._operator_id = _auth_value(auth_data, "operatorId", "operator_id")

        if not self._access_token:
            msg = "No access token in refresh response"
            raise DomruApiClientAuthenticationError(msg)

    async def async_get_phone_accounts(self, phone: str) -> list[dict[str, Any]]:
        """Get accounts available for a phone number."""
        escaped_phone = quote(phone, safe="")
        url = urljoin(self.BASE_URL, f"auth/v2/login/{escaped_phone}")
        result = await self._api_wrapper(
            url=url,
            method="GET",
            authenticated=False,
            success_statuses=(self.HTTP_OK, 300),
        )

        return result if isinstance(result, list) else []

    async def async_request_phone_confirmation(
        self,
        phone: str,
        account: dict[str, Any],
    ) -> None:
        """Request an SMS confirmation code for the selected account."""
        escaped_phone = quote(phone, safe="")
        url = urljoin(self.BASE_URL, f"auth/v2/confirmation/{escaped_phone}")
        await self._api_wrapper(
            url=url,
            method="POST",
            json=account,
            authenticated=False,
        )

    async def async_confirm_phone_code(
        self,
        phone: str,
        code: str,
        account: dict[str, Any],
    ) -> dict[str, Any]:
        """Confirm an SMS code and store returned authentication tokens."""
        escaped_phone = quote(phone, safe="")
        url = urljoin(self.BASE_URL, f"auth/v3/auth/{escaped_phone}/confirmation")
        json_data = {
            "operatorId": account.get("operatorId"),
            "login": phone,
            "accountId": account.get("accountId"),
            "profileId": account.get("profileId"),
            "confirm1": code,
            "confirm2": code,
            "subscriberId": str(account.get("subscriberId")),
        }

        result = await self._api_wrapper(
            url=url,
            method="POST",
            json=json_data,
            authenticated=False,
            bad_request_message="SMS code is wrong. Try again.",
        )
        auth_data = _auth_response_data(result)

        access_token = _auth_value(auth_data, "accessToken", "access_token")
        refresh_token = _auth_value(auth_data, "refreshToken", "refresh_token")
        operator_id = _auth_value(auth_data, "operatorId", "operator_id")

        if not access_token:
            msg = "No access token in phone confirmation response"
            raise DomruApiClientAuthenticationError(msg)
        if not refresh_token:
            msg = "No refresh token in phone confirmation response"
            raise DomruApiClientAuthenticationError(msg)
        if operator_id is None:
            msg = "No operator ID in phone confirmation response"
            raise DomruApiClientAuthenticationError(msg)

        self._access_token = access_token
        self._refresh_token = refresh_token
        self._operator_id = operator_id

        return auth_data

    async def async_get_data(self) -> dict[str, Any]:
        """Get data from the API (places and devices)."""
        data = {
            "places": [],
            "cameras": [],
            "access_controls": [],
            "finances": {},
            "events": [],
        }

        # Get subscriber places
        try:
            await self._async_add_places_and_access_controls(data)
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
            TimeoutError,
        ):  # pylint: disable=broad-except
            _LOGGER.debug("Failed to get subscriber places")

        # Get cameras
        try:
            cameras = []
            for place in data["places"]:
                place_id = place.get("id")
                if place_id is None:
                    continue
                cameras.extend(
                    await self.get_cameras(place_id=place_id, fallback=False)
                )
            data["cameras"] = cameras or await self.get_cameras()
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
            TimeoutError,
        ):  # pylint: disable=broad-except
            _LOGGER.debug("Failed to get cameras")

        # Get finances
        try:
            finances = await self.get_finances()
            data["finances"] = finances
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
            TimeoutError,
        ):  # pylint: disable=broad-except
            _LOGGER.debug("Failed to get finances")

        # Get events (if we have place_id)
        if self._place_id:
            try:
                events = await self.async_get_events(self._place_id, limit=20)
                data["events"] = events
            except (
                DomruApiClientError,
                DomruApiClientCommunicationError,
                TimeoutError,
            ):  # pylint: disable=broad-except
                pass

        return data

    async def _async_add_places_and_access_controls(
        self,
        data: dict[str, Any],
    ) -> None:
        """Populate places and access controls in coordinator data."""
        places_response = await self.get_subscriber_places()
        for place_data in places_response:
            place = _place_from_subscriber_place(place_data)
            if place is None:
                continue

            place_id = place.get("id")
            data["places"].append(place)

            if self._place_id is None and place_id is not None:
                self._place_id = place_id

            if place_id is None:
                continue

            access_controls = await self._async_get_place_access_controls(place_id)
            for access_control in access_controls:
                access_control.setdefault("placeId", place_id)
                access_control.setdefault("place_id", place_id)
            data["access_controls"].extend(access_controls)

        if data["access_controls"]:
            device = data["access_controls"][0]
            self._access_control_id = device.get("id")

    async def _async_get_place_access_controls(
        self,
        place_id: str | int,
    ) -> list[dict[str, Any]]:
        """Return access controls for a place without failing whole discovery."""
        try:
            return await self.get_access_controls(place_id)
        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
            TimeoutError,
        ):
            _LOGGER.debug("Failed to get access controls for place %s", place_id)
            return []

    async def get_subscriber_places(self) -> list[dict[str, Any]]:
        """Get subscriber places (addresses)."""
        url = urljoin(self.BASE_URL, "rest/v3/subscriber-places")
        result = await self._api_wrapper(url=url, method="GET")

        return _response_list(result, "data", "subscriberPlaces", "places")

    async def get_access_controls(
        self,
        place_id: str | int,
    ) -> list[dict[str, Any]]:
        """Get access controls for a place."""
        url = urljoin(self.BASE_URL, f"rest/v1/places/{place_id}/accesscontrols")
        result = await self._api_wrapper(url=url, method="GET")

        return _response_list(result, "data", "accessControls", "access_controls")

    async def get_cameras(
        self,
        place_id: str | int | None = None,
        *,
        fallback: bool = True,
    ) -> list[dict[str, Any]]:
        """Get cameras list."""
        place = place_id or self._place_id
        if place is not None:
            url = urljoin(self.BASE_URL, f"rest/v1/places/{place}/cameras")
            try:
                result = await self._api_wrapper(url=url, method="GET")
            except (
                DomruApiClientError,
                DomruApiClientCommunicationError,
                TimeoutError,
            ):
                _LOGGER.debug("Failed to get place-scoped cameras for place %s", place)
            else:
                cameras = _response_list(result, "data", "cameras")
                if cameras or not fallback:
                    return cameras
            if not fallback:
                return []

        url = urljoin(self.BASE_URL, "rest/v1/forpost/cameras")
        result = await self._api_wrapper(url=url, method="GET")

        return _response_list(result, "data", "cameras")

    async def get_finances(self) -> dict[str, Any]:
        """Get subscriber finances (balance, block status, etc)."""
        url = urljoin(self.BASE_URL, "rest/v1/subscribers/profiles/finances")
        result = await self._api_wrapper(url=url, method="GET")

        # Response format: {"balance": 0.0, "blockType": "NOT_BLOCKED",
        # "amountSum": 150.0, ...}
        if isinstance(result, dict):
            return result
        return {}

    async def async_open_door(
        self,
        access_control_id: str | int | None = None,
        place_id: str | int | None = None,
        access_control: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open the door."""
        device_id = access_control_id or self._access_control_id
        place = place_id or self._place_id

        if not device_id or not place:
            msg = (
                f"Device ID or Place ID not set (device_id={device_id}, "
                f"place_id={place})"
            )
            raise DomruApiClientError(msg)

        if (
            access_control
            and _dict_value(access_control, "openMethod", "open_method") == "FORPOST"
        ):
            camera_id = _dict_value(
                access_control,
                "externalCameraId",
                "external_camera_id",
            )
            external_device_id = _dict_value(
                access_control,
                "externalDeviceId",
                "external_device_id",
            )
            if not camera_id or not external_device_id:
                msg = "FORPOST access control is missing external camera or device ID"
                raise DomruApiClientError(msg)

            url = urljoin(
                self.BASE_URL,
                f"rest/v1/forpost/cameras/{camera_id}/devices/"
                f"{external_device_id}/open",
            )
            result = await self._api_wrapper(
                url=url,
                method="POST",
                headers={"X-Payment-PlaceId": str(place)},
            )
            return result.get("data", result) if isinstance(result, dict) else {}

        url = urljoin(
            self.BASE_URL, f"rest/v1/places/{place}/accesscontrols/{device_id}/actions"
        )
        json_data = {"name": "accessControlOpen"}

        result = await self._api_wrapper(
            url=url,
            method="POST",
            json=json_data,
        )
        return result.get("data", result)

    async def async_open_entrance(
        self,
        place_id: str | int,
        access_control_id: str | int,
        entrance_id: str | int,
    ) -> dict[str, Any]:
        """Open a specific entrance on an access control."""
        url = urljoin(
            self.BASE_URL,
            f"rest/v1/places/{place_id}/accesscontrols/{access_control_id}/"
            f"entrances/{entrance_id}/actions",
        )
        result = await self._api_wrapper(
            url=url,
            method="POST",
            json={"name": "accessControlOpen"},
        )
        return result.get("data", result) if isinstance(result, dict) else {}

    async def async_get_camera_snapshot(self, camera_id: str | int) -> bytes:
        """Get camera snapshot."""
        try:
            async with async_timeout(10):
                url = urljoin(
                    self.BASE_URL, f"rest/v1/forpost/cameras/{camera_id}/snapshots"
                )
                response = await self._session.request(
                    method="GET",
                    url=url,
                    headers=self._get_headers(),
                )
                if response.status == self.HTTP_UNAUTHORIZED:
                    await self._set_access_token()
                    response = await self._session.request(
                        method="GET",
                        url=url,
                        headers=self._get_headers(),
                    )
                response.raise_for_status()
                return await response.read()
        except TimeoutError as exception:
            msg = f"Timeout fetching snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception
        except aiohttp.ClientError as exception:
            msg = f"Error fetching snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception

    async def async_get_access_control_snapshot(
        self,
        place_id: str | int,
        access_control_id: str | int,
    ) -> bytes:
        """Get an access control snapshot."""
        try:
            async with async_timeout(10):
                url = urljoin(
                    self.BASE_URL,
                    f"rest/v1/places/{place_id}/accesscontrols/"
                    f"{access_control_id}/videosnapshots",
                )
                response = await self._session.request(
                    method="GET",
                    url=url,
                    headers=self._get_headers(),
                )
                if response.status == self.HTTP_UNAUTHORIZED:
                    await self._set_access_token()
                    response = await self._session.request(
                        method="GET",
                        url=url,
                        headers=self._get_headers(),
                    )
                response.raise_for_status()
                return await response.read()
        except TimeoutError as exception:
            msg = f"Timeout fetching access control snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception
        except aiohttp.ClientError as exception:
            msg = f"Error fetching access control snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception

    async def async_get_camera_stream_url(self, camera_id: str | int) -> str:
        """Get camera stream URL (RTSP format)."""
        url = urljoin(
            self.BASE_URL, f"rest/v1/forpost/cameras/{camera_id}/video?LightStream=0"
        )
        response = await self._api_wrapper(
            url=url,
            method="GET",
        )

        # Parse VideoResponse structure from
        # go-impl/pkg/domru/models/cameras.go
        # Response: {"data": {"URL": "...", "Error": "...", "ErrorCode": "...",
        # "Status": "..."}}
        if (
            isinstance(response, dict)
            and "data" in response
            and isinstance(response["data"], dict)
        ):
            video_data = response["data"]

            # Check for error in response
            if video_data.get("Error"):
                error_msg = video_data.get("Error")
                error_code = video_data.get("ErrorCode")
                msg = f"API Error: {error_msg} (Code: {error_code})"
                raise DomruApiClientError(msg)

            # Get URL - it should be RTSP URL
            url_value = video_data.get("URL", "")

            # Validate and fix URL if needed
            if (
                url_value
                and not url_value.startswith("rtsp://")
                and "://" not in url_value
            ):
                url_value = "rtsp://" + url_value

            if url_value:
                return url_value

        # Fallback for different response formats
        if isinstance(response, dict):
            if "url" in response:
                return response["url"]
            if "hlsUrl" in response:
                return response["hlsUrl"]
            if "URL" in response:
                return response["URL"]

        return str(response) if response else ""

    async def async_get_sip_credentials(self, installation_id: str) -> dict[str, str]:
        """Get SIP credentials for receiving calls."""
        # Need to get the sipdevices URL from place data
        # First, try to get it from the subscriber place
        try:
            places_data = await self.get_subscriber_places()
            if not places_data:
                return _empty_sip_credentials()

            # Extract place from response
            first_place_data = (
                places_data[0] if isinstance(places_data, list) else places_data
            )
            place = (
                first_place_data.get("place", first_place_data)
                if isinstance(first_place_data, dict)
                else {}
            )

            place_id = place.get("id")

            if not place_id:
                return _empty_sip_credentials()

            access_controls = place.get("accessControls", [])
            if not access_controls:
                access_controls = await self.get_access_controls(place_id)

            # Get first access control device
            device = access_controls[0] if access_controls else {}
            device_id = device.get("id")

            if not device_id:
                return _empty_sip_credentials()

            # Build sipdevices URL
            url = urljoin(
                self.BASE_URL,
                f"rest/v1/places/{place_id}/accesscontrols/{device_id}/sipdevices",
            )

            json_data = {"installationId": installation_id}

            result = await self._api_wrapper(
                url=url,
                method="POST",
                json=json_data,
            )

            return _sip_credentials_from_response(result)

        except Exception:  # pylint: disable=broad-except
            # Log error but don't fail setup
            _LOGGER.exception("Failed to get SIP credentials")
            return _empty_sip_credentials()

    def _push_registration_body(
        self,
        installation_id: str,
        fcm_token: str | None = None,
    ) -> dict[str, Any]:
        """Build the Android device payload used for push registration."""
        body: dict[str, Any] = {
            "appVersionCode": int(ANDROID_APP_VERSION_CODE),
            "installationId": installation_id,
            "appId": 2,
            "appVersion": ANDROID_APP_VERSION_NAME,
            "platform": "google",
            "isDevelop": False,
            "deviceManufacturer": ANDROID_DEVICE_MANUFACTURER,
            "deviceModelName": ANDROID_DEVICE_MODEL,
            "osVersion": ANDROID_OS_VERSION,
            "deviceId": _device_id(installation_id),
            "deviceType": "MOBILE_APPLICATION",
        }
        if fcm_token is not None:
            body["pushToken"] = fcm_token
        return body

    async def register_push_device(
        self,
        fcm_token: str,
        installation_id: str,
    ) -> bool:
        """Bind the generated FCM token to the Dom.ru account."""
        body = self._push_registration_body(installation_id, fcm_token)
        try:
            for endpoint in (_DEVICE_INSTALLATIONS, _SUBSCRIBER_NOTIFICATIONS):
                await self._api_wrapper(
                    url=urljoin(self.BASE_URL, endpoint),
                    method="POST",
                    json=body,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to register FCM push token", exc_info=True)
            return False
        return True

    async def unregister_push_device(self, installation_id: str) -> bool:
        """Remove this integration instance from push notifications."""
        try:
            await self._api_wrapper(
                url=urljoin(self.BASE_URL, _SUBSCRIBER_NOTIFICATIONS),
                method="DELETE",
                json=self._push_registration_body(installation_id),
                success_statuses=(
                    self.HTTP_OK,
                    self.HTTP_CREATED,
                    self.HTTP_NO_CONTENT,
                ),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to unregister FCM push token", exc_info=True)
            return False
        return True

    async def async_get_events(
        self, place_id: str | int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get events history for a place."""
        try:
            url = urljoin(
                self.BASE_URL,
                f"rest/v1/places/{place_id}/events?allowExtentedActions=true",
            )

            result = await self._api_wrapper(
                url=url,
                method="GET",
            )

            # Response format: {"data": [{"event": {...}}, ...]} or direct list
            if isinstance(result, dict):
                events = result.get("data", result.get("events", []))
            elif isinstance(result, list):
                events = result
            else:
                events = []

            # Limit number of events
            if events and len(events) > limit:
                events = events[:limit]

            return events if isinstance(events, list) else []

        except (
            DomruApiClientError,
            DomruApiClientCommunicationError,
            TimeoutError,
        ):  # pylint: disable=broad-except
            _LOGGER.warning("Failed to get events")
            return []

    def _get_headers(self) -> dict[str, str]:
        """Get default headers for API requests."""
        headers = {
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/json; charset=UTF-8",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip, deflate",
        }

        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        if self._operator_id:
            headers["Operator"] = str(self._operator_id)

        return headers

    def _handle_forbidden_error(self, json_response: Any) -> None:
        """Handle 403 Forbidden error."""
        msg = json_response if isinstance(json_response, str) else "Forbidden"
        raise DomruApiClientAuthenticationError(msg)

    def _handle_server_error(self, json_response: Any) -> None:
        """Handle 500 Server error."""
        error_code = (
            json_response.get("errorCode") if isinstance(json_response, dict) else None
        )
        if error_code == self.ERROR_TEMPORARY_CODE_FAILED:
            msg = (
                json_response.get("message")
                or json_response.get("errorMessage")
                or "Invalid SMS confirmation code"
            )
            raise DomruApiClientError(msg)
        msg = json_response if isinstance(json_response, str) else "Server error"
        raise DomruApiClientError(msg)

    def _handle_http_error(self, json_response: Any, status: int) -> None:
        """Handle other HTTP errors."""
        msg = json_response if isinstance(json_response, str) else f"HTTP {status}"
        raise DomruApiClientError(msg)

    def _handle_bad_request_error(self, message: str) -> None:
        """Handle a request-specific 400 Bad Request error."""
        raise DomruApiClientError(message)

    async def _parse_response(
        self,
        response: aiohttp.ClientResponse,
        allowed_statuses: tuple[int, ...],
    ) -> Any:
        """Parse JSON or text response bodies from the API."""
        try:
            return await response.json()
        except (JSONDecodeError, ContentTypeError) as exception:
            text_response = await response.text()
            if not text_response and response.status in allowed_statuses:
                return None
            if text_response:
                try:
                    return jsonlib.loads(text_response)
                except JSONDecodeError:
                    return text_response

            msg = f"Failed to parse response: {response.status} {response.reason}"
            raise DomruApiClientError(msg) from exception

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        json: dict | None = None,
        headers: dict | None = None,
        *,
        authenticated: bool = True,
        success_statuses: tuple[int, ...] | None = None,
        bad_request_message: str | None = None,
    ) -> Any:
        """Make an API request with automatic token refresh on 401."""
        allowed_statuses = success_statuses or (self.HTTP_OK, self.HTTP_CREATED)
        while True:
            try:
                headers_to_use = headers or (
                    self._get_headers()
                    if authenticated
                    else {
                        "User-Agent": self.USER_AGENT,
                        "Content-Type": "application/json; charset=UTF-8",
                        "Connection": "Keep-Alive",
                    }
                )

                async with async_timeout(10):
                    response = await self._session.request(
                        method=method,
                        url=url,
                        json=json,
                        headers=headers_to_use,
                    )

                    # Handle 401 - try to refresh token and retry
                    if response.status == self.HTTP_UNAUTHORIZED and authenticated:
                        await self._set_access_token()
                        continue  # Retry the request with new token

                    json_response = await self._parse_response(
                        response,
                        allowed_statuses,
                    )

                    # Check for error responses
                    if response.status == self.HTTP_FORBIDDEN:
                        self._handle_forbidden_error(json_response)

                    if response.status == self.HTTP_INTERNAL_ERROR:
                        self._handle_server_error(json_response)

                    if response.status == self.HTTP_BAD_REQUEST and bad_request_message:
                        self._handle_bad_request_error(bad_request_message)

                    if response.status not in allowed_statuses:
                        self._handle_http_error(json_response, response.status)

                    return json_response

            except TimeoutError as exception:
                msg = f"Timeout error - {exception}"
                raise DomruApiClientCommunicationError(msg) from exception
            except ClientConnectorError as exception:
                msg = f"Client connector error - {exception}"
                raise DomruApiClientCommunicationError(msg) from exception
            except (
                DomruApiClientAuthenticationError,
                DomruApiClientCommunicationError,
            ):
                raise
            except DomruApiClientError:
                raise
            except Exception as exception:  # pylint: disable=broad-except
                msg = f"Unexpected error - {exception}"
                raise DomruApiClientError(msg) from exception

    def set_ids(
        self,
        place_id: str | int | None = None,
        access_control_id: str | int | None = None,
    ) -> None:
        """Set place_id and access_control_id."""
        if place_id is not None:
            self._place_id = place_id
        if access_control_id is not None:
            self._access_control_id = access_control_id
