"""Test Events API endpoint."""

import asyncio
import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custom_components.domru.api import DomruApiClient
import aiohttp


async def test_events():
    """Test getting events."""
    # Read credentials from environment or hardcode for testing
    username = input("Enter username (phone): ")
    password = input("Enter password: ")

    async with aiohttp.ClientSession() as session:
        client = DomruApiClient(
            username=username,
            password=password,
            session=session,
        )

        print("\n1. Authenticating...")
        await client.async_authenticate()
        print("   ✓ Authenticated")

        print("\n2. Getting data...")
        data = await client.async_get_data()
        print(f"   ✓ Got data")
        print(f"   Places: {len(data.get('places', []))}")

        place_id = None
        if data.get('places'):
            place = data['places'][0]
            place_id = place.get('id')
            print(f"   Place ID: {place_id}")
            print(f"   Place Name: {place.get('name')}")

        if not place_id:
            print("\n   ✗ No place_id found!")
            return

        print("\n3. Getting events...")
        try:
            events = await client.async_get_events(place_id, limit=10)

            print(f"\n   ✓ Events received: {len(events)}")

            if events:
                print("\n   📜 Last 3 events:")
                for i, event in enumerate(events[:3], 1):
                    print(f"\n   Event #{i}:")
                    print(f"   {json.dumps(event, indent=6, ensure_ascii=False)}")
            else:
                print("\n   ⚠ No events found (это нормально если давно не было активности)")

        except Exception as e:
            print(f"\n   ✗ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_events())

