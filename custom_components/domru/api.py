"""Dom.ru Smart Intercom API Client."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime, timezone
from json.decoder import JSONDecodeError
from typing import Any
from urllib.parse import urljoin

import aiohttp
import async_timeout
from aiohttp import AsyncResolver, TCPConnector
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError


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
    USER_AGENT = "Google sdkgphone64x8664 | Android 14 | erth | 8.9.2 (8090200) |  | null | 10c99d90-9899-4a25-926f-067b34bc4a7f | null"

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._operator_id: str | None = None
        self._place_id: str | None = None
        self._access_control_id: str | None = None
        # Hash parameters from go-impl/pkg/auth/password.go
        self._hash2_prefix = "DigitalHomeNTK"
        self._secret = "789sdgHJs678wertv34712376"

        # Replace connector with one using AsyncResolver instead of aiodns
        self._patch_session_resolver()

    def _patch_session_resolver(self) -> None:
        """Replace the session connector's resolver with AsyncResolver."""
        try:
            connector = self._session.connector
            if connector is None:
                return
            new_connector = TCPConnector(
                resolver=AsyncResolver(),
                force_close=False,
                enable_cleanup_closed=True,
            )
            self._session._connector = new_connector
        except Exception:  # pylint: disable=broad-except
            pass

    def _get_hash1(self) -> str:
        """Generate hash1 (SHA1 of password in base64)."""
        password_bytes = self._password.encode("iso-8859-1")
        sha1_digest = hashlib.sha1(password_bytes).digest()
        hash1 = base64.b64encode(sha1_digest).decode("utf-8")
        return hash1

    def _get_hash2(self, timestamp: datetime) -> str:
        """Generate hash2 (MD5 of combined string)."""
        timestamp_str = timestamp.strftime("%Y%m%d%H%M%S")
        # From go-impl/pkg/auth/password.go
        combined = f"{self._hash2_prefix}password{self._username}{self._password}{timestamp_str}{self._secret}"
        hash2 = hashlib.md5(combined.encode("utf-8")).hexdigest()
        return hash2

    async def async_authenticate(self) -> None:
        """Authenticate with the API using login and password."""
        await self._set_access_token()

    async def _set_access_token(self) -> None:
        """Set access token using login/password or refresh token."""
        if self._refresh_token is not None and self._operator_id is not None:
            # Try to refresh token first
            try:
                await self._refresh_access_token()
                return
            except Exception:  # pylint: disable=broad-except
                pass

        # Authenticate with login and password
        if self._username is not None and self._password is not None:
            timestamp = datetime.now(timezone.utc)
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

            self._access_token = result.get("accessToken")
            self._refresh_token = result.get("refreshToken")
            self._operator_id = result.get("operatorId")

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

        self._access_token = result.get("accessToken")
        self._refresh_token = result.get("refreshToken")
        self._operator_id = result.get("operatorId")

    async def async_get_data(self) -> dict[str, Any]:
        """Get data from the API (places and devices)."""
        data = {
            "places": [],
            "cameras": [],
            "access_controls": [],
            "finances": {},
        }

        # Get subscriber places
        try:
            places_response = await self.get_subscriber_places()

            # Parse places according to Go model structure
            # Response: {"data": [{"place": {...}, ...}]}
            if places_response:
                first_place_data = places_response[0] if isinstance(places_response, list) else places_response

                # Extract place object from the response
                if isinstance(first_place_data, dict):
                    place = first_place_data.get("place", first_place_data)
                    data["places"] = [place]

                    self._place_id = place.get("id")

                    # Get access controls from place object
                    access_controls = place.get("accessControls", [])
                    data["access_controls"] = access_controls

                    if access_controls and len(access_controls) > 0:
                        device = access_controls[0]
                        self._access_control_id = device.get("id")
        except Exception:  # pylint: disable=broad-except
            pass

        # Get cameras
        try:
            cameras = await self.get_cameras()
            data["cameras"] = cameras
        except Exception:  # pylint: disable=broad-except
            pass

        # Get finances
        try:
            finances = await self.get_finances()
            data["finances"] = finances
        except Exception:  # pylint: disable=broad-except
            pass

        return data

    async def get_subscriber_places(self) -> list[dict[str, Any]]:
        """Get subscriber places (addresses)."""
        url = urljoin(self.BASE_URL, "rest/v1/subscriberplaces")
        result = await self._api_wrapper(url=url, method="GET")

        # Handle different response formats
        # Response: {"data": [{"place": {...}, ...}]}
        if isinstance(result, dict):
            places = result.get("data", result.get("subscriberPlaces", result.get("places", [])))
        else:
            places = result if isinstance(result, list) else []

        return places if isinstance(places, list) else []


    async def get_cameras(self) -> list[dict[str, Any]]:
        """Get cameras list."""
        url = urljoin(self.BASE_URL, "rest/v1/forpost/cameras")
        result = await self._api_wrapper(url=url, method="GET")

        # Handle different response formats
        if isinstance(result, dict):
            cameras = result.get("data", result.get("cameras", []))
        else:
            cameras = result if isinstance(result, list) else []

        return cameras if isinstance(cameras, list) else []

    async def get_finances(self) -> dict[str, Any]:
        """Get subscriber finances (balance, block status, etc)."""
        url = urljoin(self.BASE_URL, "rest/v1/subscribers/profiles/finances")
        result = await self._api_wrapper(url=url, method="GET")

        # Response format: {"balance": 0.0, "blockType": "NOT_BLOCKED", "amountSum": 150.0, ...}
        if isinstance(result, dict):
            return result
        return {}

    async def async_open_door(self, access_control_id: str | int | None = None, place_id: str | int | None = None) -> dict[str, Any]:
        """Open the door."""
        device_id = access_control_id or self._access_control_id
        place = place_id or self._place_id

        if not device_id or not place:
            msg = f"Device ID or Place ID not set (device_id={device_id}, place_id={place})"
            raise DomruApiClientError(msg)

        url = urljoin(self.BASE_URL, f"rest/v1/places/{place}/accesscontrols/{device_id}/actions")
        json_data = {"name": "accessControlOpen"}

        result = await self._api_wrapper(
            url=url,
            method="POST",
            json=json_data,
        )
        return result.get("data", result)

    async def async_get_camera_snapshot(self, camera_id: str | int) -> bytes:
        """Get camera snapshot."""
        try:
            async with async_timeout.timeout(10):
                url = urljoin(self.BASE_URL, f"rest/v1/forpost/cameras/{camera_id}/snapshots")
                response = await self._session.request(
                    method="GET",
                    url=url,
                    headers=self._get_headers(),
                )
                if response.status == 401:
                    await self._set_access_token()
                    response = await self._session.request(
                        method="GET",
                        url=url,
                        headers=self._get_headers(),
                    )
                response.raise_for_status()
                return await response.read()
        except asyncio.TimeoutError as exception:
            msg = f"Timeout fetching snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception
        except aiohttp.ClientError as exception:
            msg = f"Error fetching snapshot - {exception}"
            raise DomruApiClientCommunicationError(msg) from exception

    async def async_get_camera_stream_url(self, camera_id: str | int) -> str:
        """Get camera stream URL (RTSP format)."""
        url = urljoin(self.BASE_URL, f"rest/v1/forpost/cameras/{camera_id}/video?LightStream=0")
        response = await self._api_wrapper(
            url=url,
            method="GET",
        )

        # Parse VideoResponse structure from go-impl/pkg/domru/models/cameras.go
        # Response: {"data": {"URL": "...", "Error": "...", "ErrorCode": "...", "Status": "..."}}
        if isinstance(response, dict) and "data" in response and isinstance(response["data"], dict):
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
            if url_value:
                # Check if URL starts with rtsp://
                if not url_value.startswith("rtsp://"):
                    # Try to fix if it looks like domain without protocol
                    if "://" not in url_value:
                        url_value = "rtsp://" + url_value
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

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        json: dict | None = None,
        headers: dict | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Make an API request with automatic token refresh on 401."""
        while True:
            try:
                headers_to_use = headers or (
                    self._get_headers() if authenticated else {
                        "User-Agent": self.USER_AGENT,
                        "Content-Type": "application/json; charset=UTF-8",
                    }
                )

                async with async_timeout.timeout(10):
                    response = await self._session.request(
                        method=method,
                        url=url,
                        json=json,
                        headers=headers_to_use,
                    )

                    # Handle 401 - try to refresh token and retry
                    if response.status == 401 and authenticated:
                        try:
                            await self._set_access_token()
                            continue  # Retry the request with new token
                        except DomruApiClientAuthenticationError:
                            raise

                    # Try to parse response
                    try:
                        json_response = await response.json()
                    except (JSONDecodeError, ContentTypeError) as e:
                        raw_response = await response.text()
                        msg = f"Failed to parse response: {response.status} {response.reason}"
                        raise DomruApiClientError(msg) from e

                    # Check for error responses
                    if response.status == 403:
                        msg = json_response if isinstance(json_response, str) else "Forbidden"
                        raise DomruApiClientAuthenticationError(msg)

                    if response.status == 500:
                        error_code = (json_response.get("errorCode")
                                     if isinstance(json_response, dict) else None)
                        if error_code == 6005:
                            msg = "Temporary code failed"
                            raise DomruApiClientError(msg)
                        msg = json_response if isinstance(json_response, str) else "Server error"
                        raise DomruApiClientError(msg)

                    if response.status not in (200, 201):
                        msg = json_response if isinstance(json_response, str) else f"HTTP {response.status}"
                        raise DomruApiClientError(msg)

                    return json_response

            except asyncio.TimeoutError as exception:
                msg = f"Timeout error - {exception}"
                raise DomruApiClientCommunicationError(msg) from exception
            except ClientConnectorError as exception:
                msg = f"Client connector error - {exception}"
                raise DomruApiClientCommunicationError(msg) from exception
            except (DomruApiClientAuthenticationError, DomruApiClientCommunicationError):
                raise
            except DomruApiClientError:
                raise
            except Exception as exception:  # pylint: disable=broad-except
                msg = f"Unexpected error - {exception}"
                raise DomruApiClientError(msg) from exception
