#!/usr/bin/env python
"""Debug Zulip message fetching."""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ZULIP_SITE = os.getenv("ZULIP_SITE", "https://chat.fhir.org")
ZULIP_EMAIL = os.getenv("ZULIP_EMAIL")
ZULIP_API_KEY = os.getenv("ZULIP_API_KEY")

auth = (ZULIP_EMAIL, ZULIP_API_KEY)

def test_channel(stream_name: str):
    """Test fetching messages from a channel."""
    print(f"\n{'='*60}")
    print(f"Testing: {stream_name}")
    print('='*60)
    
    # Method 1: Using "channel" operator (newer API)
    print("\n1. Trying 'channel' operator...")
    params = {
        "anchor": "newest",
        "num_before": 10,
        "num_after": 0,
        "narrow": json.dumps([{"operator": "channel", "operand": stream_name}]),
        "apply_markdown": "false",
    }
    
    response = requests.get(
        f"{ZULIP_SITE}/api/v1/messages",
        auth=auth,
        params=params
    )
    
    print(f"   Status: {response.status_code}")
    data = response.json()
    
    if response.status_code == 200:
        messages = data.get("messages", [])
        print(f"   Messages found: {len(messages)}")
        if messages:
            for msg in messages[:3]:
                print(f"   - [{msg.get('subject')}] {msg.get('sender_full_name')}: {msg.get('content', '')[:50]}...")
    else:
        print(f"   Error: {data}")
    
    # Method 2: Using "stream" operator (older API)
    print("\n2. Trying 'stream' operator...")
    params2 = {
        "anchor": "newest",
        "num_before": 10,
        "num_after": 0,
        "narrow": json.dumps([{"operator": "stream", "operand": stream_name}]),
        "apply_markdown": "false",
    }
    
    response2 = requests.get(
        f"{ZULIP_SITE}/api/v1/messages",
        auth=auth,
        params=params2
    )
    
    print(f"   Status: {response2.status_code}")
    data2 = response2.json()
    
    if response2.status_code == 200:
        messages2 = data2.get("messages", [])
        print(f"   Messages found: {len(messages2)}")
        if messages2:
            for msg in messages2[:3]:
                print(f"   - [{msg.get('subject')}] {msg.get('sender_full_name')}: {msg.get('content', '')[:50]}...")
    else:
        print(f"   Error: {data2}")
    
    # Method 3: Using stream ID
    print("\n3. Getting stream ID first...")
    streams_response = requests.get(
        f"{ZULIP_SITE}/api/v1/users/me/subscriptions",
        auth=auth
    )
    
    stream_id = None
    if streams_response.status_code == 200:
        for sub in streams_response.json().get("subscriptions", []):
            if sub["name"] == stream_name:
                stream_id = sub["stream_id"]
                print(f"   Found stream ID: {stream_id}")
                break
    
    if stream_id:
        params3 = {
            "anchor": "newest",
            "num_before": 10,
            "num_after": 0,
            "narrow": json.dumps([{"operator": "stream", "operand": stream_id}]),
            "apply_markdown": "false",
        }
        
        response3 = requests.get(
            f"{ZULIP_SITE}/api/v1/messages",
            auth=auth,
            params=params3
        )
        
        print(f"   Status: {response3.status_code}")
        data3 = response3.json()
        
        if response3.status_code == 200:
            messages3 = data3.get("messages", [])
            print(f"   Messages found: {len(messages3)}")
            if messages3:
                for msg in messages3[:3]:
                    print(f"   - [{msg.get('subject')}] {msg.get('sender_full_name')}: {msg.get('content', '')[:50]}...")
        else:
            print(f"   Error: {data3}")

if __name__ == "__main__":
    print(f"Site: {ZULIP_SITE}")
    print(f"Email: {ZULIP_EMAIL}")
    
    # Test all channels
    channels = [
        "Da Vinci CRD",
        "Da Vinci DTR", 
        "Da Vinci PAS",
        "cds hooks",
        "argonaut",
    ]
    
    for channel in channels:
        test_channel(channel)
