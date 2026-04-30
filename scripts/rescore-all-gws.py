#!/usr/bin/env python3
"""Rescore all gameweeks with real player data."""
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy import func
from app.database import SessionLocal
from app.models import (
    Gameweek, Fixture, Player, PlayerGameweekPoints,
    FantasyTeam, FantasyTeamHistory, SquadPlayer, Team,
)
from app.scoring import calculate_player_points

db = SessionLocal()

# Mark all scored GWs as unscored
scored_gws = db.query(Gameweek).filter_by(scored=True).order_by(Gameweek.number).all()
print(f"Found {len(scored_gws)} scored gameweeks")

# Delete existing data
for model in [PlayerGameweekPoints, FantasyTeamHistory]:
    count = db.query(model).count()
    if count:
        print(f"Deleting {count} existing {model.__name__} records...")
        db.query(model).delete()
db.commit()

total_pgps = 0

for gw in scored_gws:
    gw.scored = False
    db.flush()

    # Get played fixtures for this GW
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw.id,
        Fixture.home_score.isnot(None),
        Fixture.away_score.isnot(None)
    ).all()

    if not fixtures:
        gw.scored = True
        gw.closed = True
        print(f"  GW{gw.number}: No fixtures with scores")
        continue

    # Collect team performance data: team_id -> list of (goals_scored, goals_conceded, opponent_name, is_home)
    team_matches = {}
    for fixture in fixtures:
        home_team = db.query(Team).filter_by(id=fixture.home_team_id).first()
        away_team = db.query(Team).filter_by(id=fixture.away_team_id).first()
        if not home_team or not away_team:
            continue

        team_matches.setdefault(home_team.id, []).append({
            "goals_scored": fixture.home_score,
            "goals_conceded": fixture.away_score,
            "opponent": away_team.name,
            "is_home": True,
        })
        team_matches.setdefault(away_team.id, []).append({
            "goals_scored": fixture.away_score,
            "goals_conceded": fixture.home_score,
            "opponent": home_team.name,
            "is_home": False,
        })

    pgp_count = 0
    # For each team, create one PlayerGameweekPoints per player
    for team_id, matches in team_matches.items():
        team_players = db.query(Player).filter(
            Player.team_id == team_id,
            Player.is_active == True
        ).all()
        if not team_players:
            continue

        # Aggregate team stats for this GW
        total_goals = sum(m["goals_scored"] for m in matches)
        total_conceded = sum(m["goals_conceded"] for m in matches)
        clean_sheet = total_conceded == 0
        last_opponent = matches[-1]["opponent"]
        was_home = matches[-1]["is_home"]

        fwds = sorted([p for p in team_players if p.position == "FWD"], key=lambda p: p.goals, reverse=True)
        mids = sorted([p for p in team_players if p.position == "MID"], key=lambda p: p.goals, reverse=True)

        # Distribute goals across the GW
        goals_assigned = 0
        goal_scorers = {}  # player_id -> goals in this GW

        # 60% to forwards
        fwd_share = max(0, int(total_goals * 0.6))
        if fwds and fwd_share > 0:
            per_fwd = max(1, fwd_share // len(fwds))
            for f in fwds:
                if goals_assigned >= total_goals:
                    break
                g = min(per_fwd, total_goals - goals_assigned)
                if g > 0:
                    goal_scorers[f.id] = g
                    goals_assigned += g

        # 30% to midfielders
        mid_share = max(0, int(total_goals * 0.3))
        if mids and mid_share > 0 and goals_assigned < total_goals:
            per_mid = max(1, mid_share // min(len(mids), 2))
            for m in mids[:2]:
                if goals_assigned >= total_goals:
                    break
                g = min(per_mid, total_goals - goals_assigned)
                if g > 0:
                    goal_scorers[m.id] = g
                    goals_assigned += g

        # Remaining goals
        remaining = total_goals - goals_assigned
        if remaining > 0 and (fwds or mids):
            target = random.choice(fwds + mids)
            goal_scorers[target.id] = goal_scorers.get(target.id, 0) + remaining
            goals_assigned += remaining

        # Create one PGP per player
        for player in team_players:
            p_goals = goal_scorers.get(player.id, 0)
            p_assists = 0
            p_clean_sheet = clean_sheet and player.position in ("GK", "DEF")
            p_minutes = 90  # Assume full games for played fixtures
            p_goals_conceded = total_conceded if player.position == "GK" else 0
            p_saves = random.randint(0, 3) if player.position == "GK" and total_conceded > 0 else 0

            points = calculate_player_points(
                position=player.position,
                goals_scored=p_goals,
                assists=p_assists,
                clean_sheet=p_clean_sheet,
                minutes_played=p_minutes,
            )

            pgp = PlayerGameweekPoints(
                player_id=player.id,
                gameweek_id=gw.id,
                opponent_team=last_opponent,
                was_home=was_home,
                minutes_played=p_minutes,
                did_play=True,
                goals_scored=p_goals,
                assists=p_assists,
                clean_sheet=p_clean_sheet,
                goals_conceded=p_goals_conceded,
                saves=p_saves,
                total_points=points,
            )
            db.add(pgp)
            pgp_count += 1

    db.commit()
    gw.scored = True
    gw.closed = True
    total_pgps += pgp_count
    print(f"  GW{gw.number}: {len(fixtures)} fixtures, {pgp_count} player points")

# Update player season totals
print("\nUpdating player season totals...")
for player in db.query(Player).filter(Player.is_active == True).all():
    total = db.query(PlayerGameweekPoints).filter(
        PlayerGameweekPoints.player_id == player.id
    ).with_entities(func.sum(PlayerGameweekPoints.total_points)).scalar() or 0
    player.total_points_season = total
db.commit()

# Update fantasy team scores
print("Updating fantasy team scores...")
for ft in db.query(FantasyTeam).all():
    season_total = 0
    for gw in scored_gws:
        squad = db.query(SquadPlayer).filter_by(fantasy_team_id=ft.id).all()
        gw_score = 0
        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw.id
            ).first()
            if pgp:
                pts = pgp.total_points
                if sp.is_captain:
                    pts *= 2
                gw_score += pts

        history = FantasyTeamHistory(
            fantasy_team_id=ft.id,
            gameweek_id=gw.id,
            points=gw_score,
            total_points=season_total + gw_score,
        )
        db.add(history)
        season_total += gw_score
    ft.total_points = season_total
    db.commit()
    print(f"  Team {ft.id} ({ft.name}): {season_total} pts")

print(f"\nTotal: {total_pgps} PlayerGameweekPoints created")

# Show top scorers
print("\nTop 10 by points:")
top = db.query(Player).filter(Player.is_active == True).order_by(
    Player.total_points_season.desc()
).limit(10).all()
for p in top:
    team = p.team
    print(f"  {p.name:<30} {p.position:<4} {p.total_points_season:>4}pts  {p.goals}g/{p.apps}apps  {team.name if team else '?'}")

db.close()
