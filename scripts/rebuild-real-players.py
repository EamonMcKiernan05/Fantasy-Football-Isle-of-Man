#!/usr/bin/env python3
"""Rebuild player database with real data from FullTime API.

Reads player names/personIDs from data/real_players.json, fetches stats from
the FullTime API, filters to 5+ appearances, and rebuilds the database.
"""
import os
import sys
import time
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.database import SessionLocal
from app.models import (
    Player, Team, Gameweek, Fixture, User, FantasyTeam, SquadPlayer,
    PlayerGameweekPoints, Season,
)
from app.scoring import calculate_player_points
from app.utils.passwords import hash_password

API_BASE = "http://localhost:5000/api"

TEAM_NAME_MAP = {
    "Peel Combination": "Peel", "Peel First": "Peel",
    "Corinthians First": "Corinthians",
    "Laxey First": "Laxey",
    "St Marys First": "St Marys",
    "St Johns United First": "St Johns", "St Johns United": "St Johns",
    "Onchan First": "Onchan",
    "Ramsey First": "Ramsey",
    "Rushen United First": "Rushen United", "Rushen United": "Rushen United",
    "Union Mills First": "Union Mills",
    "Ayre United First": "Ayre United", "Ayre United": "Ayre United",
    "Braddan First": "Braddan",
    "Foxdale First": "Foxdale",
    "DHSOB First": "DHSOB",
}

def normalize_team(team_name: str) -> str:
    if not team_name:
        return None
    for key, value in TEAM_NAME_MAP.items():
        if key.lower() in team_name.lower():
            return value
    return None

def fetch_player_stats(person_id: str) -> dict:
    url = f"{API_BASE}/player/{person_id}"
    try:
        resp = requests.get(url, timeout=15, verify=False)
        resp.raise_for_status()
        return resp.json()
    except:
        return {}

def main():
    # Load player data
    with open("data/real_players.json") as f:
        player_data = json.load(f)["players"]
    
    # Deduplicate by personID
    seen_ids = set()
    unique_players = []
    for p in player_data:
        if p["personID"] not in seen_ids:
            seen_ids.add(p["personID"])
            unique_players.append(p)
    
    print(f"Loaded {len(unique_players)} unique players from file")
    print(f"Fetching stats from FullTime API...\n")
    
    # Fetch stats for all players
    players_with_stats = []
    for i, p in enumerate(unique_players):
        stats = fetch_player_stats(p["personID"])
        if stats and stats.get("appearances", 0) >= 5:
            name = stats.get("name", p["name"])
            team = normalize_team(stats.get("team", ""))
            if team:
                players_with_stats.append({
                    "name": name,
                    "team": team,
                    "goals": stats.get("goals", 0),
                    "apps": stats.get("appearances", 0),
                    "yellows": stats.get("yellows", 0),
                    "reds": stats.get("reds", 0),
                })
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(unique_players)} players processed...")
        time.sleep(0.2)  # Rate limiting
    
    print(f"\nPlayers with 5+ apps and valid teams: {len(players_with_stats)}")
    
    # Group by team
    teams = {}
    for p in players_with_stats:
        teams.setdefault(p["team"], []).append(p)
    
    print(f"Teams: {', '.join(f'{t}({len(teams[t])})' for t in sorted(teams))}")
    
    # Clear existing data
    db = SessionLocal()
    print("\nClearing existing data...")
    db.query(SquadPlayer).delete()
    db.query(PlayerGameweekPoints).delete()
    db.query(FantasyTeam).delete()
    db.query(Player).delete()
    db.commit()
    
    # Create players
    print(f"\nCreating {len(players_with_stats)} players...")
    
    # Get teams from database
    teams_in_db = {t.name: t for t in db.query(Team).all()}
    
    for i, p in enumerate(players_with_stats):
        # Find team ID
        team = teams_in_db.get(p["team"])
        if not team:
            continue  # Skip if team not found
        
        player = Player(
            name=p["name"],
            web_name=p["name"].lower().replace(" ", "_").replace("'", ""),
            team_id=team.id,
            position="MID",  # Will be estimated later
            goals=p["goals"],
            assists=0,  # Not available from API
            apps=p["apps"],
            is_active=True,
            total_points_season=0,
            price=round(min(12.0, 5.0 + p["goals"] * 0.1 + p["apps"] * 0.05), 1),
        )
        db.add(player)
        if (i + 1) % 50 == 0:
            db.flush()
            print(f"  {i+1}/{len(players_with_stats)} created...")
    db.flush()
    
    # Set positions based on goals per game ratio
    for player in db.query(Player).all():
        gpg = player.goals / max(player.apps, 1)
        if gpg > 0.7:
            player.position = "FWD"
        elif gpg > 0.4:
            player.position = "MID"
        elif gpg > 0.15:
            player.position = "DEF"
        else:
            player.position = "MID"  # Uncertain - user will set manually
    
    db.commit()
    print(f"Created {db.query(Player).count()} players")
    
    # Create test user and fantasy team
    print("\nCreating test user and fantasy team...")
    user = User(
        username="test_manager",
        email="test@example.com",
        password_hash=hash_password("password123"),
    )
    db.add(user)
    db.flush()
    
    ft = FantasyTeam(user_id=user.id, name="Test FC", budget=100.0)
    db.add(ft)
    db.flush()
    
    # Build squad - pick top players from each team
    budget = 100.0
    squad_players = []
    used_names = set()
    pos_counts = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    pos_limits = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    
    # Sort by total value (goals + apps)
    all_players = sorted(
        db.query(Player).filter(Player.is_active == True).all(),
        key=lambda p: p.goals + p.apps,
        reverse=True
    )
    
    for player in all_players:
        if len(squad_players) >= 15:
            break
        if player.name in used_names:
            continue
        if budget < player.price:
            continue
        if pos_counts.get(player.position, 0) >= pos_limits.get(player.position, 99):
            continue
        
        squad_players.append(player)
        used_names.add(player.name)
        pos_counts[player.position] = pos_counts.get(player.position, 0) + 1
        budget -= player.price
    
    print(f"Selected {len(squad_players)} players for squad (budget remaining: £{budget:.1f}m)")
    
    # Create squad entries
    for i, player in enumerate(squad_players):
        sp = SquadPlayer(
            fantasy_team_id=ft.id,
            player_id=player.id,
            position_slot=i + 1,
            is_starting=i < 11,
            is_captain=i == 0,
            is_vice_captain=i == 1,
            bench_priority=0 if i < 11 else i - 10,
        )
        db.add(sp)
    
    db.commit()
    print("Squad created!")
    
    # Re-run scoring
    print("\nRe-running scoring for all gameweeks...")
    gameweeks = db.query(Gameweek).filter(Gameweek.is_current == False).order_by(Gameweek.number).all()
    
    for gw in gameweeks:
        fixtures = [f for f in db.query(Fixture).filter_by(gameweek_id=gw.id).all()]
        
        for fixture in fixtures:
            home_team = teams_in_db.get(fixture.home_team_name)
            away_team = teams_in_db.get(fixture.away_team_name)
            if not home_team or not away_team:
                continue
            
            home_goals = fixture.home_goals
            away_goals = fixture.away_goals
            
            for side, team, goals_scored, goals_conceded in [
                ("home", home_team, home_goals, away_goals),
                ("away", away_team, away_goals, home_goals),
            ]:
                team_players = db.query(Player).filter(
                    Player.team_id == team.id,
                    Player.is_active == True
                ).all()
                
                for player in team_players:
                    goals = 0
                    assists = 0
                    clean_sheet = 0
                    
                    # Estimate goals - distribute based on position and team goals
                    if player.position == "FWD" and goals_scored > 0:
                        fwd_count = sum(1 for p in team_players if p.position == "FWD")
                        goals = max(0, goals_scored // max(fwd_count, 1))
                    elif player.position == "MID" and goals_scored > 1:
                        goals = max(0, (goals_scored - 1) // max(3, len([p for p in team_players if p.position == "MID"])))
                    
                    # Clean sheet
                    if goals_conceded == 0 and player.position in ("GK", "DEF"):
                        clean_sheet = 1
                    
                    points = calculate_player_points(
                        position=player.position,
                        goals_scored=goals,
                        assists=assists,
                        clean_sheet=clean_sheet,
                        minutes_played=90,
                    )
                    
                    pgp = PlayerGameweekPoints(
                        player_id=player.id,
                        gameweek_id=gw.id,
                        fixture_id=fixture.id,
                        goals_scored=goals,
                        assists=assists,
                        clean_sheet=clean_sheet,
                        total_points=points,
                        was_captain=False,
                    )
                    db.add(pgp)
        
        db.commit()
        gw.is_current = False
        gw.scored = True
        db.commit()
        print(f"  GW{gw.number} scored")
    
    # Update player total points
    for player in db.query(Player).filter(Player.is_active == True).all():
        total = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id
        ).with_entities(db.func.sum(PlayerGameweekPoints.total_points)).scalar() or 0
        player.total_points_season = total
    
    db.commit()
    print(f"\n=== Done! ===")
    print(f"Total players: {db.query(Player).count()}")
    print(f"Squad players: {len(squad_players)}")
    
    # Show top scorers
    top = db.query(Player).filter(Player.is_active == True).order_by(Player.goals.desc()).limit(10).all()
    print(f"\nTop scorers:")
    for p in top:
        print(f"  {p.name} ({p.position}, {p.team.name}): {p.goals} goals, {p.apps} apps, {p.total_points_season} pts")

if __name__ == "__main__":
    main()
