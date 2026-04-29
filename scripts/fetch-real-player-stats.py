#!/usr/bin/env python3
"""Fetch real player stats from FullTime API and update the database.

The FullTime API endpoint: https://faapi.jwhsolutions.co.uk/api/player/{personID}
Returns detailed player stats including goals, assists, appearances, clean sheets, etc.
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from app.database import SessionLocal
from app.models import Player, Team

# Unique players found on stat leaders page
PLAYERS = [
    {"name": "Tomas Brown", "personID": "487023392"},
    {"name": "Tyler Hughes", "personID": "191366925"},
    {"name": "Josh Ridings", "personID": "335119348"},
    {"name": "Tom Creer", "personID": "548920357"},
    {"name": "Dan Simpson", "personID": "55171938"},
    {"name": "Sean Doyle", "personID": "43645031"},
    {"name": "Edward Kangah", "personID": "237755964"},
    {"name": "JASON CHATWOOD", "personID": "279160875"},
    {"name": "Jason Charmer", "personID": "788495443"},
    {"name": "Luke Murray", "personID": "635249162"},
    {"name": "MARK WOLFENDEN", "personID": "711190917"},
    {"name": "Lee Gale", "personID": "786077897"},
    {"name": "Taylor Andrews", "personID": "993485735"},
    {"name": "Andrew Asbridge", "personID": "739537985"},
    {"name": "ETHAN LEIVERS", "personID": "455448895"},
    {"name": "Callum Taggart", "personID": "646328783"},
    {"name": "Joe Bergquist", "personID": "728113140"},
    {"name": "Connor Clark", "personID": "431880554"},
    {"name": "Nicholas Harvey", "personID": "853569619"},
    {"name": "Dominic McHarrie-Brennan", "personID": "259345260"},
    {"name": "Oscar Bignall", "personID": "582651610"},
    {"name": "Rhys Oates", "personID": "841360462"},
    {"name": "Tyrese Thompson", "personID": "689510904"},
    {"name": "Mark O'Neill", "personID": "611951638"},
    {"name": "James Callister", "personID": "474645333"},
]

API_BASE = "https://faapi.jwhsolutions.co.uk/api"

def fetch_player_stats(person_id: str) -> dict:
    """Fetch player stats from FullTime API."""
    url = f"{API_BASE}/player/{person_id}"
    try:
        resp = requests.get(url, timeout=15, verify=False)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Error fetching {person_id}: {e}")
        return {}

def match_player(db: SessionLocal, name: str, person_id: str):
    """Find or create a player in the database matching the name."""
    # Normalize name for matching
    name_lower = name.lower().strip()

    # Try exact match first
    player = db.query(Player).filter(
        Player.name.ilike(name),
        Player.is_active == True
    ).first()

    if not player:
        # Try partial match on first name + last name
        parts = name_lower.split()
        if len(parts) >= 2:
            first = parts[0]
            last = parts[-1]
            player = db.query(Player).filter(
                Player.name.ilike(f"%{first}%{last}%"),
                Player.is_active == True
            ).first()

    if not player:
        # Try matching on just last name
        last = parts[-1] if parts else name_lower
        player = db.query(Player).filter(
            Player.name.ilike(f"%{last}%"),
            Player.is_active == True
        ).first()

    return player

def main():
    db = SessionLocal()

    # Get all teams for reference
    teams = db.query(Team).all()
    team_names = {t.name.lower(): t for t in teams}

    print(f"Fetching stats for {len(PLAYERS)} players...")
    print(f"Teams in database: {len(team_names)}")

    updated = 0
    not_found = []

    for p in PLAYERS:
        name = p["name"]
        person_id = p["personID"]

        print(f"\n{name} (ID: {person_id})")
        stats = fetch_player_stats(person_id)

        if not stats:
            print(f"  No stats returned")
            not_found.append(name)
            continue

        # Parse stats - the API returns season stats
        # Look for appearance/goal/assist data
        season_stats = stats.get("seasonStats", {}) or stats

        # Try to extract key stats
        goals = 0
        assists = 0
        appearances = 0
        minutes = 0
        clean_sheets = 0
        position = None
        team_name = None

        # The API returns various stat categories
        # Common fields in FullTime API player stats
        for key, value in stats.items():
            if isinstance(value, dict):
                # Look for goals, assists, appearances in nested stats
                if isinstance(value.get("goals"), (int, float)):
                    goals = int(value.get("goals", 0))
                if isinstance(value.get("assists"), (int, float)):
                    assists = int(value.get("assists", 0))
                if isinstance(value.get("appearances"), (int, float)):
                    appearances = int(value.get("appearances", 0))
                if isinstance(value.get("minutesPlayed"), (int, float)):
                    minutes = int(value.get("minutesPlayed", 0))
                if isinstance(value.get("cleanSheets"), (int, float)):
                    clean_sheets = int(value.get("cleanSheets", 0))
                if isinstance(value.get("position"), str):
                    position = value.get("position", "")
                if isinstance(value.get("teamName"), str):
                    team_name = value.get("teamName", "")

        # Also check top-level fields
        if isinstance(stats.get("goals"), (int, float)):
            goals = int(stats.get("goals", 0))
        if isinstance(stats.get("assists"), (int, float)):
            assists = int(stats.get("assists", 0))
        if isinstance(stats.get("appearances"), (int, float)):
            appearances = int(stats.get("appearances", 0))

        print(f"  Stats: goals={goals}, assists={assists}, apps={appearances}, team={team_name}")

        # Find matching player in database
        player = match_player(db, name, person_id)

        if player:
            print(f"  Found: {player.name} ({player.position}, {player.team.name})")
            # Update stats if we found real data
            if appearances > 0:
                player.apps = appearances
            if goals > 0:
                player.goals = goals
            if assists > 0:
                player.assists = assists
            if minutes > 0:
                player.minutes_played = minutes
            if clean_sheets > 0:
                player.clean_sheets = clean_sheets
            if team_name:
                # Try to match team
                for tn, team in team_names.items():
                    if tn in team_name.lower() or team_name.lower() in tn:
                        player.team_id = team.id
                        print(f"  Updated team to: {team.name}")
                        break
            db.flush()
            updated += 1
        else:
            print(f"  Not found in database")
            not_found.append(name)

    db.commit()
    print(f"\n=== Summary ===")
    print(f"Updated: {updated}")
    print(f"Not found: {len(not_found)}")
    if not_found:
        print(f"Missing players: {', '.join(not_found)}")

if __name__ == "__main__":
    main()
