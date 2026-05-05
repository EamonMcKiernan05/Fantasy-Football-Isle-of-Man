#!/usr/bin/env python3
"""Scrape FullTime website for per-match player events.

Extracts goal scorers, assists, and appearances from individual fixture pages
on the FullTime website using browser automation.

Data sources:
- Results page: https://fulltime.thefa.com/results.html?selectedLeague=9057188&selectedSeason=804198730&selectedDivision=175685803
- Individual fixtures: https://fulltime.thefa.com/displayFixture.html?id=<fixture_id>

Player events extracted:
- Goal scorers (td[3] = "Overall Goals")
- Assists (td[3] = "Assists")
- Appearances (td[3] = "Appearances")
- Bench Used (td[3] = "Bench Used")
- Bench Unused (td[3] = "Bench Unused")

Row structure:
  td[0]: empty
  td[1]: team name (e.g., "Foxdale First")
  td[2]: player name
  td[3]: event type
  td[4]: count

Usage:
    python scripts/scrape_fulltime_results.py [--season 2025-26] [--output data/fulltime_events.json]
    python scripts/scrape_fulltime_results.py --fixture-id 28260929
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from app.database import SessionLocal
from app.models import Player, Team, Fixture, Gameweek, PlayerGameweekPoints

# Configuration
RESULTS_URL = "https://fulltime.thefa.com/results.html?selectedLeague=9057188&selectedSeason=804198730&selectedDivision=175685803"
FIXTURE_BASE = "https://fulltime.thefa.com/displayFixture.html?id="

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


def normalize_team_name(name: str) -> str:
    """Normalize team name to match our DB."""
    if not name:
        return ""
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    cleaned = name.replace(" First", "").replace(" Combination", "").strip()
    if cleaned in TEAM_NAME_MAP.values():
        return cleaned
    return name


def normalize_player_name(name: str) -> str:
    """Normalize player name for matching."""
    if not name:
        return ""
    # Convert to title case for consistent matching
    return name.strip().title()


def match_player_to_db(player_name: str, team_name: str, db: Session) -> Optional[Player]:
    """Match a scraped player name to our game DB.

    Uses normalized name + team matching.
    """
    normalized_name = normalize_player_name(player_name)
    normalized_team = normalize_team_name(team_name)
    
    # Get team ID
    team = db.query(Team).filter(Team.name == normalized_team).first()
    if not team:
        return None
    
    # Match by normalized name
    players = db.query(Player).filter(
        Player.team_id == team.id,
        Player.is_active == True,
    ).all()
    
    for p in players:
        if normalize_player_name(p.name) == normalized_name:
            return p
    
    # Fuzzy match (case-insensitive, partial)
    normalized_lower = normalized_name.lower()
    for p in players:
        if normalized_lower in p.name.lower() or p.name.lower() in normalized_lower:
            return p
    
    return None


def score_fixture_from_events(db: Session, fixture_id: str, events: dict, gw_id: int) -> int:
    """Score a fixture based on scraped events.

    Args:
        db: SQLAlchemy session
        fixture_id: FullTime fixture ID
        events: Extracted events from fixture page
        gw_id: Gameweek ID

    Returns:
        Number of PlayerGameweekPoints records created
    """
    # Find fixtures in this gameweek
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()
    
    # Match fixture by team names in events
    home_team = None
    away_team = None
    
    for entry in events["goal_scorers"] + events["assists"]:
        team = normalize_team_name(entry.get("team", ""))
        if team and home_team is None:
            home_team = team
        elif team and team != home_team:
            away_team = team
    
    # Find matching fixture
    fixture = None
    for f in fixtures:
        home_norm = normalize_team_name(f.home_team_name)
        away_norm = normalize_team_name(f.away_team_name)
        if (home_team and home_norm == home_team) or (away_team and away_norm == away_team):
            fixture = f
            break
    
    if not fixture:
        print(f"  No matching fixture found for teams {home_team} vs {away_team}")
        return 0
    
    created = 0
    
    # Process goal scorers
    goal_scorers = {}  # player_id -> goals
    for entry in events["goal_scorers"]:
        player = match_player_to_db(entry["player"], entry["team"], db)
        if player:
            goal_scorers[player.id] = goal_scorers.get(player.id, 0) + entry.get("count", 1)
            print(f"  Goal scorer: {player.name} ({entry['team']})")
        else:
            print(f"  WARNING: Could not match player {entry['player']} ({entry['team']})")
    
    # Process assists
    assist_map = {}  # player_id -> assists
    for entry in events["assists"]:
        player = match_player_to_db(entry["player"], entry["team"], db)
        if player:
            assist_map[player.id] = assist_map.get(player.id, 0) + entry.get("count", 1)
            print(f"  Assist: {player.name} ({entry['team']})")
    
    # Get all players for both teams
    home_players = [p for p in db.query(Player).filter(
        Player.team_id == fixture.home_team_id,
        Player.is_active == True,
    ).all()]
    
    away_players = [p for p in db.query(Player).filter(
        Player.team_id == fixture.away_team_id,
        Player.is_active == True,
    ).all()]
    
    home_player_ids = {p.id for p in home_players}
    away_player_ids = {p.id for p in away_players}
    
    # Create PlayerGameweekPoints for goal scorers
    for player_id, goals in goal_scorers.items():
        existing = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player_id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()
        
        if not existing:
            assists = assist_map.get(player_id, 0)
            is_home = player_id in home_player_ids
            opponent = fixture.away_team_name if is_home else fixture.home_team_name
            
            pgp = PlayerGameweekPoints(
                player_id=player_id,
                gameweek_id=gw_id,
                opponent_team=opponent,
                was_home=is_home,
                minutes_played=90,
                did_play=True,
                goals_scored=goals,
                assists=assists,
                clean_sheet=False,
                goals_conceded=0,
                saves=0,
                base_points=goals * 4 + 2,  # goals + appearance
                total_points=goals * 4 + 2,
                bps_score=goals * 8 + 2,
            )
            db.add(pgp)
            created += 1
            print(f"  Created points for {db.query(Player).get(player_id).name}: {goals} goals, {assists} assists")
    
    # Create entries for assist providers without goals
    for player_id, assists in assist_map.items():
        if player_id in goal_scorers:
            continue  # Already scored
        existing = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player_id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()
        if not existing:
            is_home = player_id in home_player_ids
            opponent = fixture.away_team_name if is_home else fixture.home_team_name
            
            pgp = PlayerGameweekPoints(
                player_id=player_id,
                gameweek_id=gw_id,
                opponent_team=opponent,
                was_home=is_home,
                minutes_played=90,
                did_play=True,
                goals_scored=0,
                assists=assists,
                clean_sheet=False,
                goals_conceded=0,
                saves=0,
                base_points=assists * 3 + 2,  # assists + appearance
                total_points=assists * 3 + 2,
                bps_score=assists * 8 + 2,
            )
            db.add(pgp)
            created += 1
            print(f"  Created points for {db.query(Player).get(player_id).name}: {assists} assists")
    
    return created


def main():
    parser = argparse.ArgumentParser(description="Scrape FullTime match events")
    parser.add_argument("--season", default="2025-26", help="Season (default: 2025-26)")
    parser.add_argument("--output", default="data/fulltime_events.json", help="Output file")
    parser.add_argument("--fixture-id", type=int, help="Scrape single fixture by ID")
    args = parser.parse_args()

    print(f"Season: {args.season}")
    print(f"Output: {args.output}")

    if args.fixture_id:
        print(f"\nScraping fixture {args.fixture_id}...")
        print(f"URL: {FIXTURE_BASE}{args.fixture_id}")
        print("\nUse browser tools to extract events:")
        print("1. Navigate to fixture URL")
        print("2. Run extraction JS in browser console:")
        print("""
JSON.stringify((function() {
    const ev = {gs: [], as: [], app: 0, bu: [], bb: []};
    document.querySelectorAll('tr').forEach(row => {
        const tds = row.querySelectorAll('td');
        if (tds.length >= 4) {
            const team = tds[1]?.textContent?.trim();
            const player = tds[2]?.textContent?.trim();
            const eventType = tds[3]?.textContent?.trim();
            const count = tds[4]?.textContent?.trim();
            if (!team || !player || !eventType) return;
            const entry = {team, player, count: parseInt(count) || 1};
            if (eventType === 'Overall Goals') ev.gs.push(entry);
            else if (eventType === 'Assists') ev.as.push(entry);
            else if (eventType === 'Appearances') ev.app++;
            else if (eventType === 'Bench Unused') ev.bu.push(entry);
            else if (eventType === 'Bench Used') ev.bb.push(entry);
        }
    });
    return ev;
})())
""")
        print("3. Paste the JSON output here")
        json_input = input("Paste JSON: ")
        data = json.loads(json_input)
        events = {
            "goal_scorers": data.get("gs", []),
            "assists": data.get("as", []),
            "appearances": data.get("app", 0),
            "bench_used": data.get("bb", []),
            "bench_unused": data.get("bu", []),
        }
        print(f"\nExtracted {len(events['goal_scorers'])} goal scorers, {len(events['assists'])} assists")

        # Score the fixture
        db = SessionLocal()
        try:
            gw = db.query(Gameweek).filter(Gameweek.closed == False).first()
            if not gw:
                gw = db.query(Gameweek).order_by(Gameweek.number.desc()).first()
            if gw:
                created = score_fixture_from_events(db, args.fixture_id, events, gw.id)
                db.commit()
                print(f"Created {created} player points for GW{gw.number}")
            else:
                print("No gameweek found")
        finally:
            db.close()
    else:
        print("\nNo fixture ID provided. Use --fixture-id to scrape a specific fixture.")
        print("\nAvailable fixture IDs from results page:")
        print("- 28260990: Rushen United First vs St Marys First (walkover)")
        print("- 28260996: DHSOB First vs Peel First (walkover)")
        print("- 28260929: Foxdale First 3-4 St Johns United First")
        print("- 29897974: Onchan First vs Braddan First (Cup)")
        print("- 28260955: St Johns United First vs Onchan First")
        print("- 28260987: Braddan First vs Laxey First")
        print("- 28261015: Corinthians First vs Rushen United First")
        print("- 28260986: Foxdale First vs DHSOB First")
        print("- 28260979: Ramsey First vs St Marys First")


if __name__ == "__main__":
    main()
