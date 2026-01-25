#!/usr/bin/env python3
"""Advanced test script with detailed logging."""

import asyncio
import json
import logging
import sys
from datetime import datetime
from urllib.parse import urljoin

import aiohttp

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the custom_components to the path
sys.path.insert(0, str(__file__).rsplit("\\", 1)[0])

from custom_components.domru.api import DomruApiClient


class LoggingAioHttpSession(aiohttp.ClientSession):
    """ClientSession with request/response logging."""

    async def request(self, method, url, **kwargs):
        """Override request to log details."""
        print(f"\n📤 REQUEST: {method.upper()} {url}")
        if "json" in kwargs and kwargs["json"]:
            print(f"   Body: {json.dumps(kwargs['json'], indent=2)}")
        if "headers" in kwargs:
            print(f"   Headers: {json.dumps(dict(kwargs['headers']), indent=2)}")

        response = await super().request(method, url, **kwargs)

        print(f"📥 RESPONSE: {response.status} {response.reason}")
        print(f"   Headers: {json.dumps(dict(response.headers), indent=2)}")

        # Read body and re-wrap it
        try:
            body = await response.text()
            print(f"   Body: {body[:500]}..." if len(body) > 500 else f"   Body: {body}")
        except Exception:
            pass

        return response


async def test_single_request():
    """Test a single request."""
    print("=" * 80)
    print("SINGLE REQUEST TEST MODE")
    print("=" * 80)

    username = input("\nEnter username: ").strip()
    password = input("Enter password: ").strip()

    session = LoggingAioHttpSession()

    try:
        client = DomruApiClient(
            username=username,
            password=password,
            session=session,
        )

        print("\nSelect test:")
        print("1. Authenticate")
        print("2. Get subscriber places")
        print("3. Get access controls")
        print("4. Get cameras")
        print("5. Get full data")
        print("6. Open door")
        print("7. Get camera snapshot")

        choice = input("\nEnter choice (1-7): ").strip()

        if choice == "1":
            print("\n>>> Testing authentication...")
            await client.async_authenticate()
            print(f"✓ Success! Token: {client._access_token[:30]}...")

        elif choice == "2":
            print("\n>>> Testing get_subscriber_places...")
            await client.async_authenticate()
            places = await client.get_subscriber_places()
            print(f"✓ Got {len(places)} place(s)")
            for i, place in enumerate(places):
                print(f"\n  Place {i}:")
                print(f"    {json.dumps(place, indent=6, ensure_ascii=False)}")

        elif choice == "3":
            print("\n>>> Testing get_access_controls...")
            await client.async_authenticate()
            place_id = input("Enter place ID: ").strip()
            controls = await client.get_access_controls(place_id)
            print(f"✓ Got {len(controls)} control(s)")
            for i, control in enumerate(controls):
                print(f"\n  Control {i}:")
                print(f"    {json.dumps(control, indent=6, ensure_ascii=False)}")

        elif choice == "4":
            print("\n>>> Testing get_cameras...")
            await client.async_authenticate()
            cameras = await client.get_cameras()
            print(f"✓ Got {len(cameras)} camera(s)")
            for i, camera in enumerate(cameras):
                print(f"\n  Camera {i}:")
                print(f"    {json.dumps(camera, indent=6, ensure_ascii=False)}")

        elif choice == "5":
            print("\n>>> Testing async_get_data...")
            await client.async_authenticate()
            data = await client.async_get_data()
            print("✓ Got data:")
            print(json.dumps(data, indent=2, ensure_ascii=False))

        elif choice == "6":
            print("\n>>> Testing async_open_door...")
            await client.async_authenticate()
            place_id = input("Enter place ID: ").strip()
            device_id = input("Enter device/access control ID: ").strip()
            result = await client.async_open_door(
                place_id=place_id,
                access_control_id=device_id
            )
            print("✓ Door opened:")
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif choice == "7":
            print("\n>>> Testing async_get_camera_snapshot...")
            await client.async_authenticate()
            camera_id = input("Enter camera ID: ").strip()
            snapshot = await client.async_get_camera_snapshot(camera_id)
            print(f"✓ Got snapshot: {len(snapshot)} bytes")
            with open("test_snapshot.jpg", "wb") as f:
                f.write(snapshot)
            print("  Saved to test_snapshot.jpg")

    finally:
        await session.close()


async def main():
    """Main function."""
    print("\n🔧 DOM.RU INTERCOM API TEST TOOL\n")
    print("Modes:")
    print("1. Full test (all endpoints)")
    print("2. Single request test (with detailed logging)")

    mode = input("\nSelect mode (1-2): ").strip()

    if mode == "2":
        await test_single_request()
    else:
        # Import and run full test
        from test_api import main as full_test
        await full_test()


if __name__ == "__main__":
    asyncio.run(main())

