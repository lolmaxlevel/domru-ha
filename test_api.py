#!/usr/bin/env python3
"""Test script for Dom.ru Smart Intercom API."""

import asyncio
import json
import sys
from datetime import datetime

import aiohttp

# Add the custom_components to the path
sys.path.insert(0, str(__file__).rsplit("\\", 1)[0])

from custom_components.domru.api import DomruApiClient


async def main():
    """Main test function."""
    # Get credentials from user
    username = input("Enter username (login): ").strip()
    password = input("Enter password: ").strip()

    # Create aiohttp session
    session = aiohttp.ClientSession()

    try:
        # Create API client
        client = DomruApiClient(
            username=username,
            password=password,
            session=session,
        )

        print("\n" + "=" * 60)
        print("1. Testing authentication...")
        print("=" * 60)
        try:
            await client.async_authenticate()
            print("✓ Authentication successful!")
            print(f"  Access Token: {client._access_token[:20]}...")
            print(f"  Refresh Token: {client._refresh_token[:20]}...")
            print(f"  Operator ID: {client._operator_id}")
        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            return

        print("\n" + "=" * 60)
        print("2. Testing get_subscriber_places...")
        print("=" * 60)
        try:
            places = await client.get_subscriber_places()
            print(f"✓ Got {len(places)} place(s):")
            print(json.dumps(places, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"✗ Failed to get places: {e}")

        print("\n" + "=" * 60)
        print("3. Testing get_access_controls...")
        print("=" * 60)
        if client._place_id:
            try:
                access_controls = await client.get_access_controls(client._place_id)
                print(f"✓ Got {len(access_controls)} access control(s) for place {client._place_id}:")
                print(json.dumps(access_controls, indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"✗ Failed to get access controls: {e}")
        else:
            print("⚠ No place ID available (places list is empty)")

        print("\n" + "=" * 60)
        print("4. Testing get_cameras...")
        print("=" * 60)
        try:
            cameras = await client.get_cameras()
            print(f"✓ Got {len(cameras)} camera(s):")
            print(json.dumps(cameras, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"✗ Failed to get cameras: {e}")

        print("\n" + "=" * 60)
        print("5. Testing async_get_data (full data load)...")
        print("=" * 60)
        try:
            data = await client.async_get_data()
            print("✓ Full data loaded:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print(f"\n  Place ID set to: {client._place_id}")
            print(f"  Access Control ID set to: {client._access_control_id}")
        except Exception as e:
            print(f"✗ Failed to load data: {e}")

        print("\n" + "=" * 60)
        print("6. Testing async_open_door (DRY RUN - will NOT open)...")
        print("=" * 60)
        if client._place_id and client._access_control_id:
            print(f"Ready to open door:")
            print(f"  Place ID: {client._place_id}")
            print(f"  Access Control ID: {client._access_control_id}")
            confirm = input("\nDo you want to ACTUALLY OPEN the door? (yes/no): ").strip().lower()
            if confirm == "yes":
                try:
                    result = await client.async_open_door()
                    print("✓ Door opened!")
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                except Exception as e:
                    print(f"✗ Failed to open door: {e}")
            else:
                print("Skipped door opening")
        else:
            print("⚠ No place ID or access control ID available")

        print("\n" + "=" * 60)
        print("7. Testing async_get_camera_snapshot...")
        print("=" * 60)
        if client._session and not client._session.closed:
            cameras = await client.get_cameras()
            if cameras and len(cameras) > 0:
                camera_id = cameras[0].get("id")
                print(f"Attempting to get snapshot from camera ID: {camera_id}")
                try:
                    snapshot = await client.async_get_camera_snapshot(camera_id)
                    print(f"✓ Got snapshot! Size: {len(snapshot)} bytes")
                    # Save snapshot to file
                    with open("test_snapshot.jpg", "wb") as f:
                        f.write(snapshot)
                    print("  Saved to test_snapshot.jpg")
                except Exception as e:
                    print(f"✗ Failed to get snapshot: {e}")
            else:
                print("⚠ No cameras available")

        print("\n" + "=" * 60)
        print("Test completed!")
        print("=" * 60)

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())

