#!/usr/bin/env python3
"""Test API endpoints with FFIOM-DB separation using FastAPI TestClient."""
import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

print("=== Testing FFIOM-DB separation via API endpoints ===\n")

# Health check
resp = client.get('/health')
print(f"Health: {resp.status_code} - {resp.json()}")

# Players from FFIOM-DB
resp = client.get('/api/players/?limit=3')
if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, list):
        print(f"Players: OK - {len(data)} players (from FFIOM-DB)")
    else:
        print(f"Players: OK - {data}")
else:
    print(f"Players: FAIL {resp.status_code} - {resp.text[:200]}")

# Teams from FFIOM-DB
resp = client.get('/api/teams/')
if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, list):
        print(f"Teams: OK - {len(data)} teams (from FFIOM-DB)")
    else:
        print(f"Teams: OK - {data}")
else:
    print(f"Teams: FAIL {resp.status_code} - {resp.text[:200]}")

# Gameweeks from FFIOM-DB
resp = client.get('/api/gameweeks/')
if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, dict):
        print(f"Gameweeks: OK - {len(data.get('gameweeks',[]))} GWs (from FFIOM-DB)")
    else:
        print(f"Gameweeks: OK - {data}")
else:
    print(f"Gameweeks: FAIL {resp.status_code} - {resp.text[:200]}")

# Fixtures from FFIOM-DB
resp = client.get('/api/fixtures/')
if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, list):
        print(f"Fixtures: OK - {len(data)} fixtures (from FFIOM-DB)")
    else:
        print(f"Fixtures: OK - {data}")
else:
    print(f"Fixtures: FAIL {resp.status_code} - {resp.text[:200]}")

# Leaderboard (game DB)
resp = client.get('/api/leaderboard/')
if resp.status_code == 200:
    data = resp.json()
    if isinstance(data, dict):
        print(f"Leaderboard: OK - {len(data.get('entries',[]))} entries (from game DB)")
    else:
        print(f"Leaderboard: OK - {data}")
else:
    print(f"Leaderboard: FAIL {resp.status_code} - {resp.text[:200]}")

# Dream Team (cross-DB query)
resp = client.get('/api/dream-team/1')
if resp.status_code == 200:
    data = resp.json()
    print(f"Dream Team: OK - {len(data.get('players',[]))} players (cross-DB)")
else:
    print(f"Dream Team: FAIL {resp.status_code} - {resp.text[:200]}")

print("\n=== All API endpoint tests complete ===")
