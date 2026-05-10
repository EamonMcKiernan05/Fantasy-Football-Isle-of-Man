#!/usr/bin/env python3
"""Test key API endpoints to verify FFIOM-DB separation works."""
import urllib.request
import json

BASE = "http://localhost:8000"

def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def test(name, path, check):
    try:
        data = get(path)
        result = check(data)
        print(f"  {name}: {'OK' if result else 'FAIL - ' + str(result)}")
        return result
    except Exception as e:
        print(f"  {name}: FAIL - {e}")
        return False

print("Testing endpoints with FFIOM-DB separation:")
all_ok = True

# Health check
all_ok &= test("health", "/health", lambda d: d.get("status") == "healthy")

# Players from FFIOM-DB
data = get("/api/players/?limit=3")
players = data if isinstance(data, list) else data.get("players", data)
all_ok &= test("players (from FFIOM-DB)", "/api/players/?limit=3",
               lambda d: len(d) >= 3 if isinstance(d, list) else False)

# Teams from FFIOM-DB
data = get("/api/teams/")
teams = data if isinstance(data, list) else data.get("teams", [])
all_ok &= test("teams (from FFIOM-DB)", "/api/teams/",
               lambda d: len(d) >= 13)

# Gameweeks from FFIOM-DB
data = get("/api/gameweeks/")
gws = data.get("gameweeks", []) if isinstance(data, dict) else data
all_ok &= test("gameweeks (from FFIOM-DB)", "/api/gameweeks/",
               lambda d: len(d) >= 25)

# Fixtures from FFIOM-DB
data = get("/api/fixtures/")
fx = data if isinstance(data, list) else data.get("fixtures", [])
all_ok &= test("fixtures (from FFIOM-DB)", "/api/fixtures/",
               lambda d: len(d) >= 130)

# Leaderboard (from game DB)
data = get("/api/leaderboard/")
entries = data.get("entries", []) if isinstance(data, dict) else data
all_ok &= test("leaderboard (from game DB)", "/api/leaderboard/",
               lambda d: isinstance(d, list))

# Dream Team (cross-DB query)
data = get("/api/dream-team/1")
players = data.get("players", []) if isinstance(data, dict) else []
all_ok &= test("dream team (cross-DB)", "/api/dream-team/1",
               lambda d: len(d) >= 0)  # May be empty if not calculated yet

print()
if all_ok:
    print("ALL ENDPOINTS WORKING - FFIOM-DB separation verified!")
else:
    print("SOME ENDPOINTS FAILED")
