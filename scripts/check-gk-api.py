#!/usr/bin/env python3
"""Check FullTime API for goalkeeper data."""
import requests
import json
import urllib3
urllib3.disable_warnings()

# Players with 0 goals and many apps - likely GKs
possible_gks = [
    ("MATTHEW QUIRK", "775061734"),
    ("Owen Dawson", "730360489"),
    ("Dean Kearns", "225415565"),
    ("DARREN CAIN", "602510397"),
    ("Freddie Quilliam", "451464398"),
    ("James Callow", "993449735"),
    ("Aidan Pickering", "226996861"),
]

API_BASE = "https://faapi.jwhsolutions.co.uk/api"

for name, pid in possible_gks:
    try:
        r = requests.get(f"{API_BASE}/player/{pid}", timeout=15, verify=False)
        data = r.json()
        print(f"{name}:")
        print(json.dumps(data, indent=2)[:500])
        print()
    except Exception as e:
        print(f"{name}: ERROR {e}")
        print()
