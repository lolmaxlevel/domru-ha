"""Test SIP credentials endpoint."""

import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp

from custom_components.domru.api import DomruApiClient


async def test_sip_credentials():
    """Test getting SIP credentials."""
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
        print("   ✓ Got data")
        print(f"   Places: {len(data.get('places', []))}")
        print(f"   Access controls: {len(data.get('access_controls', []))}")

        if data.get("places"):
            place = data["places"][0]
            print(f"\n   Place ID: {place.get('id')}")
            print(f"   Place Name: {place.get('name')}")

        if data.get("access_controls"):
            ac = data["access_controls"][0]
            print(f"\n   Access Control ID: {ac.get('id')}")
            print(f"   Access Control Name: {ac.get('name')}")

        print("\n3. Getting SIP credentials...")
        import hashlib
        import uuid

        # Generate installation ID (same as in __init__.py)
        instance_id = str(uuid.uuid4())
        h = hashlib.sha256(instance_id.encode()).hexdigest()
        installation_id = str(
            uuid.UUID(
                f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-"
                f"{format((int(h[16], 16) & 0x3) | 0x8, 'x')}{h[17:20]}-{h[20:32]}"
            )
        )

        print(f"   Installation ID: {installation_id}")

        try:
            sip_creds = await client.async_get_sip_credentials(installation_id)

            print("\n   ✓ SIP Credentials received:")
            print(f"   Login: {sip_creds.get('login')}")
            print(f"   Password: {sip_creds.get('password')}")
            print(f"   Realm: {sip_creds.get('realm')}")

            if not sip_creds.get("login"):
                print("\n   ⚠ WARNING: No login received!")

        except Exception as e:
            print(f"\n   ✗ Error: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sip_credentials())
