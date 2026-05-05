#!/usr/bin/env python3
"""Import FullTime player stats into the game database.

This script imports player data scraped from the FullTime website stat leaders pages.
It creates or updates players in the game database with their season stats.

Usage:
    python scripts/import_fulltime_players.py [--players-file data/fulltime_players.json]
"""

import json
import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Player, Team

# Team name normalization
TEAM_NAME_MAP = {
    "Peel First": "Peel",
    "Corinthians First": "Corinthians",
    "Laxey First": "Laxey",
    "St Marys First": "St Marys",
    "St Johns United First": "St Johns",
    "Onchan First": "Onchan",
    "Ramsey First": "Ramsey",
    "Rushen United First": "Rushen United",
    "Union Mills First": "Union Mills",
    "Ayre United First": "Ayre United",
    "Braddan First": "Braddan",
    "Foxdale First": "Foxdale",
    "DHSOB First": "DHSOB",
}

# Valid Premier League teams
VALID_TEAMS = set(TEAM_NAME_MAP.values())


def normalize_team_name(name: str) -> str:
    """Normalize team name to match our DB."""
    if not name:
        return ""
    
    # Handle multiple teams (player transferred) - use first team
    if ',' in name:
        name = name.split(',')[0].strip()
    
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    cleaned = name.replace(" First", "").replace(" Combination", "").strip()
    if cleaned in VALID_TEAMS:
        return cleaned
    return ""


def normalize_player_name(name: str) -> str:
    """Normalize player name for matching."""
    if not name:
        return ""
    return name.strip().title()


def main():
    parser = argparse.ArgumentParser(description="Import FullTime player stats")
    parser.add_argument("--players-file", default="data/fulltime_players.json", help="Players JSON file")
    args = parser.parse_args()

    # Load players
    if not os.path.exists(args.players_file):
        print(f"ERROR: Players file not found: {args.players_file}")
        print("Scrape players first using the browser extraction script.")
        sys.exit(1)

    with open(args.players_file) as f:
        players_data = json.load(f)

    print(f"Loaded {len(players_data)} players from {args.players_file}")

    db = SessionLocal()
    try:
        # Get all teams
        teams = {t.name: t for t in db.query(Team).all()}
        
        created = 0
        updated = 0
        skipped = 0

        for player_data in players_data:
            team_name = normalize_team_name(player_data["team"])
            player_name = normalize_player_name(player_data["name"])
            
            if not team_name or team_name not in VALID_TEAMS:
                print(f"  SKIP: {player_name} - invalid team: {player_data['team']}")
                skipped += 1
                continue

            # Get team
            team = teams.get(team_name)
            if not team:
                print(f"  SKIP: {player_name} - team not in DB: {team_name}")
                skipped += 1
                continue

            # Check if player exists
            existing = db.query(Player).filter(
                Player.name == player_name,
                Player.team_id == team.id,
                Player.is_active == True,
            ).first()

            if existing:
                # Update existing player
                existing.goals = int(player_data.get("goals") or 0)
                existing.assists = int(player_data.get("assists") or 0)
                existing.apps = int(player_data.get("appearances") or 0)
                existing.yellow_cards = int(player_data.get("yellows") or 0)
                existing.red_cards = int(player_data.get("reds") or 0)
                updated += 1
            else:
                # Create new player
                player = Player(
                    name=player_name,
                    team_id=team.id,
                    position="MID",  # Default position, will be updated later
                    price=5.0,  # Default price
                    is_active=True,
                    goals=int(player_data.get("goals") or 0),
                    assists=int(player_data.get("assists") or 0),
                    apps=int(player_data.get("appearances") or 0),
                    yellow_cards=int(player_data.get("yellows") or 0),
                    red_cards=int(player_data.get("reds") or 0),
                    total_points_season=0,
                )
                db.add(player)
                created += 1

        db.commit()
        print(f"\nImport complete:")
        print(f"  Created: {created}")
        print(f"  Updated: {updated}")
        print(f"  Skipped: {skipped}")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
