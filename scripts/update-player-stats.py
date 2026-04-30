#!/usr/bin/env python3
"""Update player season stats from FullTime API cache."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from app.database import SessionLocal
from app.models import Player, Team

db = SessionLocal()

# Load cache
with open("data/player_stats_cache.json") as f:
    cache = json.load(f)

TEAM_NAME_MAP = {
    "Peel Combination": "Peel", "Peel First": "Peel",
    "Corinthians First": "Corinthians", "Laxey First": "Laxey",
    "St Marys First": "St Marys",
    "St Johns United First": "St Johns", "St Johns United": "St Johns",
    "Onchan First": "Onchan", "Ramsey First": "Ramsey",
    "Rushen United First": "Rushen United", "Rushen United": "Rushen United",
    "Union Mills First": "Union Mills", "Ayre United First": "Ayre United",
    "Ayre United": "Ayre United", "Braddan First": "Braddan",
    "Foxdale First": "Foxdale", "DHSOB First": "DHSOB",
}

def normalize_team(team_name):
    for key, value in TEAM_NAME_MAP.items():
        if key.lower() in team_name.lower():
            return value
    return None

updated = 0
not_matched = 0

for person_id, stats in cache.items():
    name = stats.get("name", "").strip()
    if not name:
        continue

    team_name = normalize_team(stats.get("team", ""))
    if not team_name:
        continue

    goals = stats.get("goals", 0)
    apps = stats.get("appearances", 0)
    yellows = stats.get("yellows", 0)
    reds = stats.get("reds", 0)

    # Find player by name and team
    player = db.query(Player).filter(
        Player.name == name,
        Player.is_active == True
    ).first()

    if not player:
        # Try case-insensitive
        player = db.query(Player).filter(
            Player.name.ilike(name),
            Player.is_active == True
        ).first()

    if player and player.team:
        # Only update if team matches
        if player.team.name == team_name:
            old_goals = player.goals
            old_apps = player.apps
            player.goals = goals
            player.apps = apps
            player.yellow_cards = yellows
            player.red_cards = reds
            if old_goals != goals or old_apps != apps:
                updated += 1
        else:
            # Player exists but on wrong team - skip
            pass
    elif player:
        # Player exists without team - update anyway
        player.goals = goals
        player.apps = apps
        player.yellow_cards = yellows
        player.red_cards = reds
        updated += 1
    else:
        not_matched += 1

db.commit()
print(f"Updated {updated} players from cache")
print(f"Not matched: {not_matched}")

# Show a few examples
print("\nSample of updated players:")
for p in db.query(Player).filter(Player.is_active == True).order_by(Player.goals.desc()).limit(10):
    print(f"  {p.name:<30} {p.position:<4} goals={p.goals:>3} apps={p.apps:>3} pts={p.total_points_season:>4} team={p.team.name if p.team else '?':<15}")

db.close()
