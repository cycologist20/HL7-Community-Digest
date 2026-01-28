#!/usr/bin/env python
"""Check message timestamps to debug filtering."""

import os
import json
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()

ZULIP_SITE = os.getenv("ZULIP_SITE", "https://chat.fhir.org")
ZULIP_EMAIL = os.getenv("ZULIP_EMAIL")
ZULIP_API_KEY = os.getenv("ZULIP_API_KEY")

auth = (ZULIP_EMAIL, ZULIP_API_KEY)

now = datetime.now(timezone.utc)
print(f"Current time (UTC): {now}")
print(f"24 hours ago: {now - timedelta(hours=24)}")
print(f"48 hours ago: {now - timedelta(hours=48)}")
print(f"7 days ago: {now - timedelta(days=7)}")

channels = ["Da Vinci CRD", "cds hooks", "argonaut"]

for channel in channels:
    print(f"\n{'='*60}")
    print(f"Channel: {channel}")
    print('='*60)
    
    params = {
        "anchor": "newest",
        "num_before": 10,
        "num_after": 0,
        "narrow": json.dumps([{"operator": "channel", "operand": channel}]),
        "apply_markdown": "false",
    }
    
    response = requests.get(
        f"{ZULIP_SITE}/api/v1/messages",
        auth=auth,
        params=params
    )
    
    if response.status_code == 200:
        messages = response.json().get("messages", [])
        print(f"Found {len(messages)} messages\n")
        
        for msg in messages[:5]:
            ts = msg.get("timestamp", 0)
            msg_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            age = now - msg_time
            
            hours_ago = age.total_seconds() / 3600
            days_ago = age.days
            
            within_24h = "✅ WITHIN 24h" if hours_ago <= 24 else ""
            within_48h = "⚠️ within 48h" if 24 < hours_ago <= 48 else ""
            
            print(f"[{msg.get('subject', 'no topic')[:30]}]")
            print(f"  From: {msg.get('sender_full_name')}")
            print(f"  Time: {msg_time.strftime('%Y-%m-%d %H:%M UTC')}")
            print(f"  Age: {hours_ago:.1f} hours ({days_ago} days) {within_24h}{within_48h}")
            print()
