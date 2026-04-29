#!/usr/bin/env python3
"""Rebuild player database from cached FullTime API data."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from app.database import SessionLocal
from app.models import (
    Player, Team, Gameweek, Fixture, User, FantasyTeam, SquadPlayer,
    PlayerGameweekPoints,
)
from sqlalchemy import func as sql_func
from app.scoring import calculate_player_points
from app.utils.passwords import hash_password

TEAM_NAME_MAP = {
    "Peel Combination": "Peel", "Peel First": "Peel",
    "Corinthians First": "Corinthians", "Corinthians": "Corinthians",
    "Laxey First": "Laxey", "Laxey": "Laxey",
    "St Marys First": "St Marys", "St Marys": "St Marys",
    "St Johns United First": "St Johns", "St Johns United": "St Johns", "St Johns": "St Johns",
    "Onchan First": "Onchan", "Onchan": "Onchan",
    "Ramsey First": "Ramsey", "Ramsey": "Ramsey",
    "Rushen United First": "Rushen United", "Rushen United": "Rushen United",
    "Union Mills First": "Union Mills", "Union Mills": "Union Mills",
    "Ayre United First": "Ayre United", "Ayre United": "Ayre United",
    "Braddan First": "Braddan", "Braddan": "Braddan",
    "Foxdale First": "Foxdale", "Foxdale": "Foxdale",
    "DHSOB First": "DHSOB", "DHSOB": "DHSOB",
}

def normalize_team(team_name):
    if not team_name:
        return None
    for key, value in TEAM_NAME_MAP.items():
        if key.lower() in team_name.lower():
            return value
    return None

def main():
    # Load cached stats
    with open("data/player_stats_cache.json") as f:
        cached = json.load(f)

    print(f"Loaded {len(cached)} cached player stats")

    # Filter to 5+ apps with valid teams
    players_with_stats = []
    for person_id, stats in cached.items():
        if stats.get("appearances", 0) >= 5:
            team = normalize_team(stats.get("team", ""))
            if team:
                players_with_stats.append({
                    "name": stats.get("name", ""),
                    "team": team,
                    "goals": stats.get("goals", 0),
                    "apps": stats.get("appearances", 0),
                })

    print(f"Players with 5+ apps and valid teams: {len(players_with_stats)}")

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
    db.query(User).delete()
    db.query(Player).delete()
    db.commit()

    # Get teams from database
    teams_in_db = {t.name: t for t in db.query(Team).all()}

    # Create players
    print(f"\nCreating {len(players_with_stats)} players...")
    created = 0
    for i, p in enumerate(players_with_stats):
        team = teams_in_db.get(p["team"])
        if not team:
            continue

        gpg = p["goals"] / max(p["apps"], 1)
        if gpg > 0.7:
            position = "FWD"
        elif gpg > 0.4:
            position = "MID"
        elif gpg > 0.15:
            position = "DEF"
        else:
            position = "GK"

        player = Player(
            name=p["name"],
            web_name=p["name"].lower().replace(" ", "_").replace("'", "").replace("-", "_"),
            team_id=team.id,
            position=position,
            goals=p["goals"],
            assists=0,
            apps=p["apps"],
            is_active=True,
            total_points_season=0,
            price=round(min(8.0, 4.0 + p["goals"] * 0.05 + p["apps"] * 0.02), 1),
        )
        db.add(player)
        created += 1

    db.commit()
    print(f"Created {created} players")

    # Create test user
    print("\nCreating test user and fantasy team...")
    user = User(
        username="test_manager",
        email="test@example.com",
        password_hash=hash_password("password123"),
    )
    db.add(user)
    db.flush()

    ft = FantasyTeam(user_id=user.id, name="Test FC", budget=100.0, season="2025-26")
    db.add(ft)
    db.flush()

    # Build squad
    budget = 100.0
    squad_players = []
    used_names = set()
    pos_counts = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    pos_limits = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}

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

    print(f"Selected {len(squad_players)} players for squad (budget: £{budget:.1f}m)")

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

# Re-run scoring for all gameweeks
    print("\nRe-running scoring for all gameweeks...")
    gameweeks = db.query(Gameweek).order_by(Gameweek.number).all()

    for gw in gameweeks:
        fixtures = [f for f in db.query(Fixture).filter_by(gameweek_id=gw.id).all()]
        for fixture in fixtures:
            home_team = teams_in_db.get(fixture.home_team_name)
            away_team = teams_in_db.get(fixture.away_team_name)
            
            # Try without "First" suffix
            if not home_team:
                home_team = teams_in_db.get(fixture.home_team_name.replace(" First", "").replace(" Combination", ""))
            if not away_team:
                away_team = teams_in_db.get(fixture.away_team_name.replace(" First", "").replace(" Combination", ""))
                
            if not home_team or not away_team:
                continue

            home_goals = fixture.home_score or 0
            away_goals = fixture.away_score or 0
            
            if home_goals == 0 and away_goals == 0:
                continue  # Skip fixtures without results

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

                    if player.position == "FWD" and goals_scored > 0:
                        fwd_count = sum(1 for p in team_players if p.position == "FWD")
                        goals = max(0, goals_scored // max(fwd_count, 1))
                    elif player.position == "MID" and goals_scored > 1:
                        goals = max(0, (goals_scored - 1) // max(3, len([p for p in team_players if p.position == "MID"])))

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
                        opponent_team=away_team.name if side == "home" else home_team.name,
                        was_home=(side == "home"),
                        did_play=True,
                        minutes_played=90,
                        goals_scored=goals,
                        assists=assists,
                        clean_sheet=clean_sheet,
                        total_points=points,
                    )
                    db.add(pgp)

        db.commit()
        gw.closed = True
        gw.scored = True
        db.commit()
        print(f"  GW{gw.number} scored")

    # Update player total points
    for player in db.query(Player).filter(Player.is_active == True).all():
        total = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id
        ).with_entities(sql_func.sum(PlayerGameweekPoints.total_points)).scalar() or 0
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
