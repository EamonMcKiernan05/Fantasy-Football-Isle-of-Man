#!/usr/bin/env python3
"""Scrape FullTime website for player stats and match events.

Extracts player season stats from the stat leaders page and per-match events
from individual fixture pages on the FullTime website.

Data sources:
- Stat leaders: https://fulltime.thefa.com/statLeaders.html?itemsPerPage=100&selectedDivision=175685803&selectedOrgStatRecordingTypeID_ForSort=8359803&teamID=&selectedStatisticDisplayMode=3&selectedSeason=804198730&selectedFixtureGroupAgeGroup=0
- Results: https://fulltime.thefa.com/results.html?selectedLeague=9057188&selectedSeason=804198730&selectedDivision=175685803
- Individual fixtures: https://fulltime.thefa.com/displayFixture.html?id=<fixture_id>

Player stats extracted from stat leaders:
- td[0]: appearances
- td[2]: goals
- td[7]: assists
- td[8]: yellows
- td[9]: reds

Match events extracted from fixture pages:
- Goal scorers (td[3] = "Overall Goals")
- Assists (td[3] = "Assists")
- Appearances (td[3] = "Appearances")
- Bench Used (td[3] = "Bench Used")
- Bench Unused (td[3] = "Bench Unused")

Usage:
    python scripts/scrape_fulltime_stats.py [--output data/fulltime_players.json]
    python scripts/scrape_fulltime_stats.py --fixture-id 28260929 [--gw 24]
"""

import json
import os
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Player, Team, Fixture, Gameweek, PlayerGameweekPoints

# Configuration
STATS_URL = "https://fulltime.thefa.com/statLeaders.html?itemsPerPage=100&selectedDivision=175685803&selectedOrgStatRecordingTypeID_ForSort=8359803&teamID=&selectedStatisticDisplayMode=3&selectedSeason=804198730&selectedFixtureGroupAgeGroup=0"
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

# Scoring constants
GOAL_POINTS = 4
ASSIST_POINTS = 3
CLEAN_SHEET_POINTS = 3
MINUTES_60_PLUS = 2
MINUTES_UNDER_60 = 1
YELLOW_CARD_POINTS = -1
RED_CARD_POINTS = -3


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
    return name.strip().title()


def match_player_to_db(player_name: str, team_name: str, db: Session) -> Optional[Player]:
    """Match a scraped player name to our game DB."""
    normalized_name = normalize_player_name(player_name)
    normalized_team = normalize_team_name(team_name)
    
    team = db.query(Team).filter(Team.name == normalized_team).first()
    if not team:
        return None
    
    players = db.query(Player).filter(
        Player.team_id == team.id,
        Player.is_active == True,
    ).all()
    
    for p in players:
        if normalize_player_name(p.name) == normalized_name:
            return p
    
    # Fuzzy match
    normalized_lower = normalized_name.lower()
    for p in players:
        if normalized_lower in p.name.lower() or p.name.lower() in normalized_lower:
            return p
    
    return None


def scrape_stat_leaders(browser_output: str) -> List[dict]:
    """Parse browser output from stat leaders page.

    Args:
        browser_output: JSON string from browser console extraction

    Returns:
        List of player stat dicts
    """
    data = json.loads(browser_output)
    players = []
    
    for entry in data:
        players.append({
            "fa_id": entry.get("fa_id", ""),
            "name": entry.get("name", ""),
            "team": normalize_team_name(entry.get("team", "")),
            "appearances": int(entry.get("appearances", 0) or 0),
            "goals": int(entry.get("goals", 0) or 0),
            "assists": int(entry.get("assists", 0) or 0),
            "yellows": int(entry.get("yellows", 0) or 0),
            "reds": int(entry.get("reds", 0) or 0),
        })
    
    return players


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
    goal_scorers = {}
    for entry in events["goal_scorers"]:
        player = match_player_to_db(entry["player"], entry["team"], db)
        if player:
            goal_scorers[player.id] = goal_scorers.get(player.id, 0) + entry.get("count", 1)
            print(f"  Goal: {player.name} ({entry['team']})")
        else:
            print(f"  WARNING: Could not match {entry['player']} ({entry['team']})")
    
    # Process assists
    assist_map = {}
    for entry in events["assists"]:
        player = match_player_to_db(entry["player"], entry["team"], db)
        if player:
            assist_map[player.id] = assist_map.get(player.id, 0) + entry.get("count", 1)
            print(f"  Assist: {player.name} ({entry['team']})")
    
    # Get team players
    home_players = [p for p in db.query(Player).filter(
        Player.team_id == fixture.home_team_id, Player.is_active == True).all()]
    away_players = [p for p in db.query(Player).filter(
        Player.team_id == fixture.away_team_id, Player.is_active == True).all()]
    
    home_ids = {p.id for p in home_players}
    
    # Create PlayerGameweekPoints for goal scorers
    for player_id, goals in goal_scorers.items():
        existing = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player_id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()
        
        if not existing:
            assists = assist_map.get(player_id, 0)
            is_home = player_id in home_ids
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
                base_points=goals * GOAL_POINTS + MINUTES_60_PLUS,
                total_points=goals * GOAL_POINTS + MINUTES_60_PLUS,
                bps_score=goals * 8 + 2,
            )
            db.add(pgp)
            created += 1
    
    # Create entries for assist providers without goals
    for player_id, assists in assist_map.items():
        if player_id in goal_scorers:
            continue
        existing = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player_id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()
        if not existing:
            is_home = player_id in home_ids
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
                base_points=assists * ASSIST_POINTS + MINUTES_60_PLUS,
                total_points=assists * ASSIST_POINTS + MINUTES_60_PLUS,
                bps_score=assists * 8 + 2,
            )
            db.add(pgp)
            created += 1
    
    return created


def main():
    parser = argparse.ArgumentParser(description="Scrape FullTime player stats and match events")
    parser.add_argument("--output", default="data/fulltime_players.json", help="Output file for player stats")
    parser.add_argument("--fixture-id", type=int, help="Scrape single fixture by ID")
    parser.add_argument("--gw", type=int, help="Gameweek ID to score into")
    args = parser.parse_args()

    if args.fixture_id:
        print(f"Scraping fixture {args.fixture_id}...")
        print(f"URL: {FIXTURE_BASE}{args.fixture_id}")
        print("\nRun this JS in browser console:")
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

        db = SessionLocal()
        try:
            gw_id = args.gw
            if not gw_id:
                gw = db.query(Gameweek).filter(Gameweek.closed == False).first()
                if not gw:
                    gw = db.query(Gameweek).order_by(Gameweek.number.desc()).first()
                if gw:
                    gw_id = gw.id
                else:
                    print("No gameweek found")
                    return
            created = score_fixture_from_events(db, args.fixture_id, events, gw_id)
            db.commit()
            print(f"Created {created} player points for GW{gw_id}")
        finally:
            db.close()
    else:
        print(f"Scraping player stats from stat leaders page...")
        print(f"URL: {STATS_URL}")
        print("\nRun this JS in browser console:")
        print("""
JSON.stringify((function() {
    const players = [];
    document.querySelectorAll('table tbody tr').forEach(row => {
        const nameLink = row.querySelector('th a');
        if (nameLink) {
            const personId = new URL(nameLink.href).searchParams.get('personID');
            const name = nameLink.textContent.trim();
            const teamDiv = row.querySelector('th:nth-child(3) div div:last-child');
            const team = teamDiv ? teamDiv.textContent.trim() : '';
            const cells = row.querySelectorAll('td');
            players.push({
                fa_id: personId,
                name: name,
                team: team,
                appearances: cells[0]?.textContent?.trim(),
                goals: cells[2]?.textContent?.trim(),
                assists: cells[7]?.textContent?.trim(),
                yellows: cells[8]?.textContent?.trim(),
                reds: cells[9]?.textContent?.trim(),
            });
        }
    });
    return players;
})())
""")
        json_input = input("Paste JSON: ")
        players = scrape_stat_leaders(json_input)
        print(f"\nExtracted {len(players)} players")
        
        # Save to file
        with open(args.output, 'w') as f:
            json.dump(players, f, indent=2)
        print(f"Saved to {args.output}")
        
        # Show stats
        goalscorers = [p for p in players if p['goals'] > 0]
        print(f"\nTop scorers:")
        for p in sorted(goalscorers, key=lambda x: x['goals'], reverse=True)[:10]:
            print(f"  {p['name']:25s} {p['team']:15s} G:{p['goals']:2d} Apps:{p['appearances']}")


if __name__ == "__main__":
    main()
