#!/usr/bin/env python3
"""Run scoring for all past gameweeks.

Estimates player stats based on team fixture results since individual
player stats are not available from the FullTime API.

Usage:
    python scripts/run-scoring.py
"""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from app.database import SessionLocal
from app.models import Gameweek, Fixture, Player, PlayerGameweekPoints
from app import scoring

db = SessionLocal()

gameweeks = db.query(Gameweek).filter(
    Gameweek.closed == True,
    Gameweek.scored == True
).order_by(Gameweek.number).all()

print(f"Found {len(gameweeks)} scored gameweeks")

total_scored = 0

for gw in gameweeks:
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw.id,
        Fixture.played == True
    ).all()

    if not fixtures:
        continue

    print(f"\nGW {gw.number}: {len(fixtures)} fixtures")

    for fixture in fixtures:
        # Get players for both teams
        for team_id, goals_scored, goals_conceded in [
            (fixture.home_team_id, fixture.home_score or 0, fixture.away_score or 0),
            (fixture.away_team_id, fixture.away_score or 0, fixture.home_score or 0),
        ]:
            team_players = db.query(Player).filter(
                Player.team_id == team_id,
                Player.is_active == True
            ).all()

            for player in team_players:
                # Estimate individual stats based on team performance
                # Use player's overall stats to estimate per-gameweek contribution
                apps = player.apps or 1
                player_goals = max(0, int((player.goals or 0) * (goals_scored / 5)))
                player_assists = max(0, int((player.assists or 0) * (goals_scored / 5)))

                # Clean sheet if no goals conceded
                clean_sheet = (goals_conceded == 0)

                # GK-specific stats
                saves = 0
                if player.position == "GK":
                    saves = max(2, goals_conceded + random.randint(1, 4))

                # Calculate points
                points = scoring.calculate_player_points(
                    position=player.position,
                    goals_scored=player_goals,
                    assists=player_assists,
                    clean_sheet=clean_sheet and player.position in ("GK", "DEF", "MID"),
                    goals_conceded=goals_conceded if player.position in ("GK", "DEF") else 0,
                    saves=saves,
                    minutes_played=90 if random.random() < 0.8 else 45,
                    bonus_points=random.choice([0, 0, 0, 1, 2, 3]),
                )

                # Create/update PlayerGameweekPoints
                pgp = db.query(PlayerGameweekPoints).filter(
                    PlayerGameweekPoints.player_id == player.id,
                    PlayerGameweekPoints.gameweek_id == gw.id
                ).first()

                if not pgp:
                    pgp = PlayerGameweekPoints(
                        player_id=player.id,
                        gameweek_id=gw.id,
                        total_points=points,
                        base_points=points,
                        goals_scored=player_goals,
                        assists=player_assists,
                        clean_sheet=clean_sheet and player.position in ("GK", "DEF", "MID"),
                        goals_conceded=goals_conceded if player.position in ("GK", "DEF") else 0,
                        saves=saves,
                        minutes_played=90 if random.random() < 0.8 else 45,
                        did_play=True,
                    )
                    db.add(pgp)
                else:
                    pgp.total_points = points
                    pgp.base_points = points

                total_scored += 1

    db.flush()

db.commit()
print(f"\nDone! Scored {total_scored} player-gameweeks")
