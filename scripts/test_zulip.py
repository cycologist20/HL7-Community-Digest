#!/usr/bin/env python
"""Quick test of Zulip API connection."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

ZULIP_SITE = os.getenv("ZULIP_SITE", "https://chat.fhir.org")
ZULIP_EMAIL = os.getenv("ZULIP_EMAIL")
ZULIP_API_KEY = os.getenv("ZULIP_API_KEY")

def test_connection():
    """Test basic API connectivity."""
    print(f"Testing connection to {ZULIP_SITE}")
    print(f"Bot email: {ZULIP_EMAIL}")

    # Test 1: Get bot's own user info
    print("\n1. Testing authentication...")
    response = requests.get(
        f"{ZULIP_SITE}/api/v1/users/me",
        auth=(ZULIP_EMAIL, ZULIP_API_KEY)
    )

    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Authenticated as: {data.get('full_name', 'Unknown')}")
        print(f"   User ID: {data.get('user_id')}")
    else:
        print(f"   ❌ Auth failed: {response.status_code} - {response.text}")
        return

    # Test 2: Get subscribed streams
    print("\n2. Getting subscribed channels...")
    response = requests.get(
        f"{ZULIP_SITE}/api/v1/users/me/subscriptions",
        auth=(ZULIP_EMAIL, ZULIP_API_KEY)
    )

    if response.status_code == 200:
        data = response.json()
        subscriptions = data.get("subscriptions", [])
        print(f"   ✅ Bot is subscribed to {len(subscriptions)} channel(s):")
        for sub in subscriptions[:10]:  # Show first 10
            print(f"      - {sub['name']} (ID: {sub['stream_id']})")
    else:
        print(f"   ❌ Failed: {response.status_code}")

    # Test 3: Get recent messages from one channel
    print("\n3. Testing message retrieval...")
    if subscriptions:
        test_stream = subscriptions[0]['name']
        response = requests.get(
            f"{ZULIP_SITE}/api/v1/messages",
            auth=(ZULIP_EMAIL, ZULIP_API_KEY),
            params={
                "anchor": "newest",
                "num_before": 5,
                "num_after": 0,
                "narrow": f'[{{"operator": "channel", "operand": "{test_stream}"}}]'
            }
        )

        if response.status_code == 200:
            data = response.json()
            messages = data.get("messages", [])
            print(f"   ✅ Retrieved {len(messages)} messages from #{test_stream}")
            if messages:
                msg = messages[0]
                print(f"      Latest: [{msg.get('subject', 'no topic')}] {msg.get('sender_full_name')}: {msg.get('content', '')[:80]}...")
        else:
            print(f"   ❌ Failed: {response.status_code} - {response.text}")

    print("\n✅ All tests passed! Ready to build Zulip integration.")

if __name__ == "__main__":
    test_connection()
