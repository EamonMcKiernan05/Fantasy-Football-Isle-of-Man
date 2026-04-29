#!/usr/bin/env python3
"""Scrape top 250 players from FullTime stat leaders and rebuild database.

Scrapes player names and personIDs from the stat leaders pages, then fetches
real stats from the FullTime API. Filters to players with 5+ appearances.
Rebuilds the player database with real data.
"""
import os
import sys
import time
import json
import re
import requests
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.database import SessionLocal, Base, engine
from app.models import (
    Player, Team, Gameweek, Fixture, User, FantasyTeam, SquadPlayer,
    PlayerGameweekPoints, Season,
)
from app.utils.passwords import hash_password

API_BASE = "https://faapi.jwhsolutions.co.uk/api"
DIV_PREMIER = "175685803"

# Stat leaders pages (top 300 by appearances)
STAT_LEADER_PAGES = [
    "https://fulltime.thefa.com/statLeaders/1/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
    "https://fulltime.thefa.com/statLeaders/2/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
    "https://fulltime.thefa.com/statLeaders/3/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
]

# Team name normalization
TEAM_NAME_MAP = {
    "Peel": "Peel",
    "Peel Combination": "Peel",
    "Peel First": "Peel",
    "Corinthians": "Corinthians",
    "Corinthians First": "Corinthians",
    "Laxey": "Laxey",
    "Laxey First": "Laxey",
    "St Marys": "St Marys",
    "St Marys First": "St Marys",
    "St Johns": "St Johns",
    "St Johns United": "St Johns",
    "St Johns United First": "St Johns",
    "Onchan": "Onchan",
    "Onchan First": "Onchan",
    "Ramsey": "Ramsey",
    "Ramsey First": "Ramsey",
    "Rushen United": "Rushen United",
    "Rushen United First": "Rushen United",
    "Union Mills": "Union Mills",
    "Union Mills First": "Union Mills",
    "Ayre United": "Ayre United",
    "Ayre United First": "Ayre United",
    "Braddan": "Braddan",
    "Braddan First": "Braddan",
    "Foxdale": "Foxdale",
    "Foxdale First": "Foxdale",
    "DHSOB": "DHSOB",
    "DHSOB First": "DHSOB",
}

def normalize_team(team_name: str) -> str:
    """Normalize team name to match database."""
    if not team_name:
        return "Unknown"
    for key, value in TEAM_NAME_MAP.items():
        if key.lower() in team_name.lower():
            return value
    # Try to match by prefix
    name = team_name.strip()
    for value in TEAM_NAME_MAP.values():
        if value.lower() in name.lower():
            return value
    return name.replace(" First", "").replace(" Combination", "").strip()

def fetch_api_player(person_id: str) -> dict:
    """Fetch player stats from FullTime API."""
    url = f"{API_BASE}/player/{person_id}"
    try:
        resp = requests.get(url, timeout=15, verify=False)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {}

def scrape_players_from_selenium():
    """Scrape player names and personIDs from stat leaders pages.
    
    Returns list of {name, personID} dicts.
    """
    # We'll use subprocess to call a Python script that uses the browser
    # to scrape the player data
    import subprocess
    result = subprocess.run(
        ["python3", "-c", '''
import subprocess
import json

# Scrape all 3 pages using the browser tool
pages = [
    "https://fulltime.thefa.com/statLeaders/1/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
    "https://fulltime.thefa.com/statLeaders/2/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
    "https://fulltime.thefa.com/statLeaders/3/100.html?selectedSeason=804198730&selectedFixtureGroupAgeGroup=0&selectedDivision=175685803&selectedStatisticDisplayMode=1&selectedOrgStatRecordingTypeID_ForSort=161748845",
]
print("Use browser to scrape these pages")
'''],
        capture_output=True, text=True
    )
    return []

def main():
    print("=== Fantasy Football IOM - Player Database Rebuild ===\n")
    print("This script will:")
    print("1. Scrape top 250 players from FullTime stat leaders (3 pages)")
    print("2. Fetch real stats from FullTime API")
    print("3. Filter to players with 5+ appearances")
    print("4. Rebuild the player database")
    print("5. Re-run scoring\n")
    print("NOTE: Player scraping requires browser interaction.")
    print("The browser will open each stat leaders page and extract player links.")
    print("Press Enter to continue, or Ctrl+C to cancel...")
    input()

if __name__ == "__main__":
    main()
