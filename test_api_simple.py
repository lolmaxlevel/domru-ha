#!/usr/bin/env python3
"""Simple API integration test - tests API endpoints without Home Assistant.

Based on Go implementation from go-impl/
Using endpoints and models from:
- go-impl/pkg/domru/constants/main.go
- go-impl/pkg/domru/models/
- go-impl/pkg/auth/password.go
- go-impl/pkg/antiblock_client/main.go
"""

import asyncio
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

# Constants from go-impl/pkg/domru/constants/main.go
BASE_URL = "https://myhome.proptech.ru"
# Full User-Agent from go-impl/pkg/domru/helpers/upstream_request.go
USER_AGENT = "Google sdkgphone64x8664 | Android 14 | erth | 8.9.2 (8090200) |  | null | 10c99d90-9899-4a25-926f-067b34bc4a7f | null"

# API endpoints
API_AUTH_PASSWORD = "{base_url}/auth/v2/auth/{login}/password"
API_CAMERAS = "{base_url}/rest/v1/forpost/cameras"
API_SUBSCRIBER_PLACES = "{base_url}/rest/v1/subscriberplaces"
API_CAMERA_GET_STREAM = "{base_url}/rest/v1/forpost/cameras/{camera_id}/video"
API_VIDEO_SNAPSHOT = "{base_url}/rest/v1/places/{place_id}/accesscontrols/{access_control_id}/videosnapshots"
API_OPEN_DOOR = "{base_url}/rest/v1/places/{place_id}/accesscontrols/{access_control_id}/actions"
API_FINANCES = "{base_url}/rest/v1/subscribers/profiles/finances"
API_SUBSCRIBER_PROFILE = "{base_url}/rest/v1/subscribers/profiles"


class DomruAPIClient:
    """DOM.RU API Client based on Go implementation."""

    def __init__(self, login: str, password: str):
        self.login = login
        self.password = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.operator_id: Optional[int] = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self):
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, include_auth: bool = False) -> Dict[str, str]:
        """Get headers based on antiblock_client implementation."""
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json; charset=UTF-8",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip, deflate",
        }
        if include_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def authenticate(self) -> Dict[str, Any]:
        """Authenticate using password (from go-impl/pkg/auth/password.go)."""
        print(f"\n[AUTH] Authenticating user: {self.login}")

        # Generate auth request body
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        earth_timestamp = now.strftime("%Y%m%d%H%M%S")

        # hash1: SHA1 of password, base64 encoded
        hash1 = base64.b64encode(
            hashlib.sha1(self.password.encode()).digest()
        ).decode()

        # hash2: MD5 of concatenated strings
        hash2_input = "".join([
            "DigitalHomeNTK",
            "password",
            self.login,
            self.password,
            earth_timestamp,
            "789sdgHJs678wertv34712376"
        ])
        hash2 = hashlib.md5(hash2_input.encode()).hexdigest()

        body = {
            "login": self.login,
            "timestamp": timestamp,
            "hash1": hash1,
            "hash2": hash2,
        }

        url = API_AUTH_PASSWORD.format(base_url=BASE_URL, login=self.login)

        # Create session if not exists
        if self.session is None:
            self.session = aiohttp.ClientSession()

        async with self.session.post(
            url,
            json=body,
            headers=self._get_headers(include_auth=False),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

            self.access_token = data.get("accessToken")
            self.refresh_token = data.get("refreshToken")
            self.operator_id = data.get("operatorId")

            print(f"✓ Authentication successful!")
            print(f"  Operator ID: {self.operator_id}")
            print(f"  Access Token: {self.access_token[:20]}...")
            print(f"  Refresh Token: {self.refresh_token[:20]}...")

            return data

    async def get_cameras(self) -> Dict[str, Any]:
        """Get cameras (from go-impl/pkg/domru/apiWrapper.go)."""
        url = API_CAMERAS.format(base_url=BASE_URL)

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_places(self) -> Dict[str, Any]:
        """Get subscriber places (from go-impl/pkg/domru/apiWrapper.go)."""
        url = API_SUBSCRIBER_PLACES.format(base_url=BASE_URL)

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_stream_url(self, camera_id: int) -> str:
        """Get camera stream URL."""
        # Add LightStream=0 query parameter (from custom_components/domru/api.py)
        url = API_CAMERA_GET_STREAM.format(base_url=BASE_URL, camera_id=camera_id) + "?LightStream=0"

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

            print(f"  DEBUG: Full API response:")
            print(f"  {json.dumps(data, indent=4, ensure_ascii=False)}")

            # Parse VideoResponse structure from go-impl/pkg/domru/models/cameras.go
            # Response: {"data": {"URL": "...", "Error": "...", "ErrorCode": "...", "Status": "..."}}
            if "data" in data and isinstance(data["data"], dict):
                video_data = data["data"]

                # Check for error in response
                if video_data.get("Error"):
                    error_msg = video_data.get('Error')
                    error_code = video_data.get('ErrorCode')
                    raise Exception(f"API Error: {error_msg} (Code: {error_code})")

                # Get URL - it should be RTSP URL
                url_value = video_data.get("URL", "")

                # Validate and fix URL if needed
                if url_value:
                    # Check if URL starts with rtsp://
                    if not url_value.startswith("rtsp://"):
                        print(f"  WARNING: URL doesn't start with rtsp://: {url_value}")
                        # Try to fix if it looks like domain without protocol
                        if "://" not in url_value:
                            url_value = "rtsp://" + url_value
                            print(f"  Fixed URL: {url_value}")
                    return url_value
                else:
                    print(f"  Warning: Empty URL in response")
                    return ""

            # Fallback for different response formats
            if "url" in data:
                return data["url"]
            elif "hlsUrl" in data:
                return data["hlsUrl"]

            print(f"  Warning: Unexpected response format")
            return ""

    async def get_snapshot(self, place_id: int, access_control_id: int) -> bytes:
        """Get video snapshot from access control."""
        url = API_VIDEO_SNAPSHOT.format(
            base_url=BASE_URL,
            place_id=place_id,
            access_control_id=access_control_id
        )

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def open_door(self, place_id: int, access_control_id: int) -> Dict[str, Any]:
        """Open door via access control."""
        url = API_OPEN_DOOR.format(
            base_url=BASE_URL,
            place_id=place_id,
            access_control_id=access_control_id
        )

        # Send accessControlOpen action (from custom_components/domru/api.py)
        json_data = {"name": "accessControlOpen"}

        async with self.session.post(
            url,
            json=json_data,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            # Return data field if exists, otherwise full response
            return data.get("data", data)

    async def get_finances(self) -> Dict[str, Any]:
        """Get subscriber finances."""
        url = API_FINANCES.format(base_url=BASE_URL)

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_profile(self) -> Dict[str, Any]:
        """Get subscriber profile."""
        url = API_SUBSCRIBER_PROFILE.format(base_url=BASE_URL)

        async with self.session.get(
            url,
            headers=self._get_headers(include_auth=True),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def test_api_flow():
    """Test the API flow by calling each endpoint."""

    print("\n" + "=" * 80)
    print("🔌 DOM.RU API INTEGRATION TEST (Go Implementation)")
    print("=" * 80)
    print(f"\nBase URL: {BASE_URL}")
    print(f"User-Agent: {USER_AGENT}")

    # Get credentials
    print("\n[INPUT] Getting credentials...")
    username = "780059056016"
    password = "E#X1fu-2"

    if not username or not password:
        print("✗ Username and password are required")
        return

    # Create API client with async context manager
    print("\n[STEP 1] Creating API client...")
    async with DomruAPIClient(login=username, password=password) as client:
        print("✓ Client created")

        # Test 1: Authentication
        print("\n[TEST 1] Testing authentication...")
        print(f"  Endpoint: POST {API_AUTH_PASSWORD.format(base_url='BASE_URL', login='{username}')}")
        try:
            auth_response = await client.authenticate()
            print("✓ Authentication successful!")
            print(f"  Full response:")
            print(f"  {json.dumps(auth_response, indent=4, ensure_ascii=False)}")
        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            import traceback
            traceback.print_exc()
            return

        # Test 2: Get subscriber places
        print("\n[TEST 2] Getting subscriber places...")
        print(f"  Endpoint: GET {API_SUBSCRIBER_PLACES.format(base_url='BASE_URL')}")
        try:
            places_response = await client.get_places()
            print(f"✓ Retrieved places successfully")
            print(f"  Response:")
            print(f"  {json.dumps(places_response, indent=4, ensure_ascii=False)}")

            # Extract place info from Go model structure
            places = places_response.get("data", [])
            if not places:
                print("⚠ No places found, stopping tests")
                return

            # Get first place
            first_place_data = places[0]
            place = first_place_data.get("place", {})
            place_id = place.get("id")
            address = place.get("address", {}).get("visibleAddress", "Unknown")
            access_controls = place.get("accessControls", [])

            print(f"\n  Using place:")
            print(f"    ID: {place_id}")
            print(f"    Address: {address}")
            print(f"    Access Controls: {len(access_controls)}")

            access_control_id = None
            if access_controls:
                ac = access_controls[0]
                access_control_id = ac.get("id")
                ac_name = ac.get("name", "Unknown")
                ac_allow_open = ac.get("allowOpen", False)
                print(f"    First Access Control:")
                print(f"      ID: {access_control_id}")
                print(f"      Name: {ac_name}")
                print(f"      Allow Open: {ac_allow_open}")

        except Exception as e:
            print(f"✗ Failed to get places: {e}")
            import traceback
            traceback.print_exc()
            return

        # Test 3: Get cameras
        print("\n[TEST 3] Getting cameras...")
        print(f"  Endpoint: GET {API_CAMERAS.format(base_url='BASE_URL')}")
        try:
            cameras_response = await client.get_cameras()
            print(f"✓ Retrieved cameras successfully")
            print(f"  Response:")
            print(f"  {json.dumps(cameras_response, indent=4, ensure_ascii=False)}")

            cameras = cameras_response.get("data", [])
            camera_id = None
            if cameras:
                camera = cameras[0]
                camera_id = camera.get("ID")
                camera_name = camera.get("Name", "Unknown")
                camera_active = camera.get("IsActive", 0)
                print(f"\n  First Camera:")
                print(f"    ID: {camera_id}")
                print(f"    Name: {camera_name}")
                print(f"    Active: {camera_active}")

        except Exception as e:
            print(f"✗ Failed to get cameras: {e}")
            import traceback
            traceback.print_exc()
            camera_id = None

        # Test 4: Get finances
        print("\n[TEST 4] Getting finances...")
        print(f"  Endpoint: GET {API_FINANCES.format(base_url='BASE_URL')}")
        try:
            finances = await client.get_finances()
            print(f"✓ Retrieved finances successfully")
            print(f"  Response:")
            print(f"  {json.dumps(finances, indent=4, ensure_ascii=False)}")
        except Exception as e:
            print(f"✗ Failed to get finances: {e}")
            import traceback
            traceback.print_exc()

        # Test 5: Get subscriber profile
        print("\n[TEST 5] Getting subscriber profile...")
        print(f"  Endpoint: GET {API_SUBSCRIBER_PROFILE.format(base_url='BASE_URL')}")
        try:
            profile = await client.get_profile()
            print(f"✓ Retrieved profile successfully")
            print(f"  Response:")
            print(f"  {json.dumps(profile, indent=4, ensure_ascii=False)}")
        except Exception as e:
            print(f"✗ Failed to get profile: {e}")
            import traceback
            traceback.print_exc()

        # Test 6: Get camera stream URL (if cameras available)
        if camera_id:
            print(f"\n[TEST 6] Testing camera stream URL...")
            print(f"  Endpoint: GET {API_CAMERA_GET_STREAM.format(base_url='BASE_URL', camera_id='{camera_id}')}")
            try:
                stream_url = await client.get_stream_url(camera_id)
                print(f"✓ Stream URL retrieved successfully!")
                print(f"  Stream URL: {stream_url}")

                # Offer to play the stream
                if stream_url and stream_url.startswith("rtsp://"):
                    print(f"\n  This is an RTSP stream. You can:")
                    print(f"    1. Play it with VLC: vlc {stream_url}")
                    print(f"    2. Play it with ffplay: ffplay -rtsp_transport tcp {stream_url}")
                    print(f"    3. Use play_rtsp_stream.py script")

                    play_stream = input("\n  Do you want to play the stream now? (yes/no): ").strip().lower()
                    if play_stream == "yes":
                        # Try to use the play_rtsp_stream.py script
                        import subprocess
                        script_path = Path(__file__).parent / "play_rtsp_stream.py"
                        if script_path.exists():
                            print(f"\n  Launching stream player...")
                            try:
                                subprocess.Popen([sys.executable, str(script_path), stream_url])
                                print(f"  ✓ Stream player launched in background")
                            except Exception as e:
                                print(f"  ✗ Failed to launch player: {e}")
                                print(f"  You can manually run: python play_rtsp_stream.py {stream_url}")
                        else:
                            print(f"  ✗ play_rtsp_stream.py not found")
                            print(f"  You can manually open with VLC: vlc {stream_url}")

            except Exception as e:
                print(f"✗ Stream URL retrieval failed: {e}")
                import traceback
                traceback.print_exc()
                stream_url = None
        else:
            print("\n[TEST 6] Skipping stream URL test (no cameras found)")
            stream_url = None

        # Test 7: Get snapshot (if access control available)
        if access_control_id and place_id:
            print(f"\n[TEST 7] Testing video snapshot...")
            print(f"  Endpoint: GET {API_VIDEO_SNAPSHOT.format(base_url='BASE_URL', place_id='{place_id}', access_control_id='{access_control_id}')}")
            test_snapshot = input("  Do you want to test snapshot retrieval? (yes/no): ").strip().lower()

            if test_snapshot == "yes":
                try:
                    snapshot_data = await client.get_snapshot(place_id, access_control_id)
                    print(f"✓ Snapshot retrieved successfully!")
                    print(f"  Snapshot size: {len(snapshot_data)} bytes")

                    # Save snapshot to file
                    snapshot_path = Path("snapshot.jpg")
                    with open(snapshot_path, "wb") as f:
                        f.write(snapshot_data)
                    print(f"  Saved to: {snapshot_path}")
                except Exception as e:
                    print(f"✗ Snapshot retrieval failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("  Skipped snapshot test")
        else:
            print("\n[TEST 7] Skipping snapshot test (no access control found)")

        # Test 8: Open door (if access control available)
        if access_control_id and place_id:
            print(f"\n[TEST 8] Testing door open action...")
            print(f"  Endpoint: POST {API_OPEN_DOOR.format(base_url='BASE_URL', place_id='{place_id}', access_control_id='{access_control_id}')}")
            test_open = input("  Do you want to test door opening? (yes/no): ").strip().lower()

            if test_open == "yes":
                try:
                    result = await client.open_door(place_id, access_control_id)
                    print("✓ Door open request successful!")
                    print(f"  Response:")
                    print(f"  {json.dumps(result, indent=4, ensure_ascii=False)}")
                except Exception as e:
                    print(f"✗ Door opening failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("  Skipped door open test")
        else:
            print("\n[TEST 8] Skipping door open test (no access control found)")

        # Test 9: Custom request to any endpoint
        print("\n[TEST 9] Custom API request...")
        print("  You can send a custom request to any endpoint with current tokens and headers")
        test_custom = input("  Do you want to test a custom endpoint? (yes/no): ").strip().lower()

        while test_custom == "yes":
            print("\n  [Custom Request]")
            method = input("    Method (GET/POST/PUT/DELETE) [default: GET]: ").strip().upper() or "GET"
            endpoint = input("    Endpoint (e.g., /rest/v1/forpost/cameras/123): ").strip()

            if not endpoint:
                print("    ✗ Endpoint is required")
                test_custom = input("  Do you want to test another custom endpoint? (yes/no): ").strip().lower()
                continue

            if not endpoint.startswith("/"):
                endpoint = "/" + endpoint

            url = f"{BASE_URL}{endpoint}"

            json_data = None
            if method in ("POST", "PUT"):
                json_input = input("    JSON body (or press Enter to skip): ").strip()
                if json_input:
                    try:
                        json_data = json.loads(json_input)
                    except json.JSONDecodeError as e:
                        print(f"    ✗ Invalid JSON: {e}")
                        test_custom = input("  Do you want to test another custom endpoint? (yes/no): ").strip().lower()
                        continue

            try:
                print(f"    Sending {method} request to: {url}")

                if method == "GET":
                    async with client.session.get(
                        url,
                        headers=client._get_headers(include_auth=True),
                    ) as resp:
                        resp.raise_for_status()
                        result = await resp.json()
                else:
                    async with client.session.request(
                        method,
                        url,
                        json=json_data,
                        headers=client._get_headers(include_auth=True),
                    ) as resp:
                        resp.raise_for_status()
                        result = await resp.json()

                print(f"    ✓ Request successful!")
                print(f"    Response:")
                print(f"    {json.dumps(result, indent=6, ensure_ascii=False)}")

            except Exception as e:
                print(f"    ✗ Request failed: {e}")
                import traceback
                traceback.print_exc()

            test_custom = input("\n  Do you want to test another custom endpoint? (yes/no): ").strip().lower()

        print("\n" + "=" * 80)
        print("✅ API INTEGRATION TEST COMPLETED!")
        print("=" * 80)



if __name__ == "__main__":
    try:
        asyncio.run(test_api_flow())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()

