#!/usr/bin/env python3
import requests
import json
import urllib3
urllib3.disable_warnings()

results = requests.get('https://faapi.jwhsolutions.co.uk/api/Results/175685803', timeout=15, verify=False).json()

# Look at first few matches
for r in results[:5]:
    home = r.get("homeTeam", "?")
    away = r.get("awayTeam", "?")
    score = r.get("score", "?")
    print(f"Match: {home} vs {away} score: {score}")
    
    events = r.get("events", [])
    event_types = set(e.get("event_type", "") for e in events)
    print(f"  Event types: {event_types}")
    
    # Show first few events
    for e in events[:5]:
        print(f"  Event: {json.dumps(e)[:250]}")
    print()
    
    # Look for goalkeeper-related events
    gk_events = [e for e in events if any(kw in str(e).lower() for kw in ["save", "gk", "goalkeeper", "conceded"])]
    print(f"  GK-related events: {len(gk_events)}")
    for e in gk_events[:3]:
        print(f"  {json.dumps(e)[:300]}")
    print("---")
