"""Admin API routes for Fantasy Football Isle of Man.

Provides administrative endpoints for managing gameweeks, seeding data,
and performing bulk operations.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Form
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, date
from typing import Optional
import random
import json

from app.database import get_db
from app.models import (
    League, Division, Team, Player, Gameweek, Fixture,
    User, FantasyTeam, SquadPlayer, MiniLeague, MiniLeagueMember,
    Season, H2hLeague,
)
from app.utils.passwords import hash_password
from app.scheduler import sync_fixtures, process_gameweek_end

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/seed/sample-data")
def seed_sample_data(db: Session = Depends(get_db)):
    """Seed the database with sample IOM teams, players, and gameweeks.

    Creates sample data matching Isle of Man football structure.
    """
    seeded_leagues = 0
    seeded_teams = 0
    seeded_players = 0
    seeded_gws = 0
    seeded_fixtures = 0

    # Create sample IOM Senior teams
    iom_teams = [
        "Braddon", "Ballaugh", "Castletown", "Laxey", "Lynwood",
        "Lymm", "Michael United", "Onchan", "Peel Town", "Port Gawne",
        "Ramsey", "Sulby", "St Johns", "St Marys", "Andreas",
        "Brunswick", "Douglas", "Marown", "Noble's Park", "Spanish City",
    ]

    # Create league if not exists
    league = db.query(League).filter(League.name == "IOM Senior League").first()
    if not league:
        league = League(
            ft_id="9057188",
            name="IOM Senior League",
        )
        db.add(league)
        seeded_leagues = 1

    # Create division if not exists
    division = db.query(Division).filter(
        Division.name == "IOM Senior Premier Division"
    ).first()
    if not division:
        division = Division(
            ft_id="9057188-1",
            name="IOM Senior Premier Division",
            league_id=league.id,
        )
        db.add(division)
        db.flush()

    # Create/update teams
    for team_name in iom_teams:
        team = db.query(Team).filter(
            Team.name == team_name,
            Team.division_id == division.id,
        ).first()
        if not team:
            team = Team(
                name=team_name,
                short_name=team_name[:3].upper(),
                code=team_name[:3].upper(),
                division_id=division.id,
                current_position=seeded_teams + 1,
                strength_attack=random.randint(2, 5),
                strength_defense=random.randint(2, 5),
                strength_home=random.randint(2, 5),
                strength_away=random.randint(2, 5),
            )
            db.add(team)
            seeded_teams += 1

    db.flush()

    # Create sample players for each team
    positions = ["GK", "DEF", "MID", "FWD"]
    player_names = {
        "GK": ["Smith", "Jones", "Brown", "Wilson", "Taylor"],
        "DEF": ["Bloggs", "White", "Green", "Black", "Gray", "Clark", "Hall"],
        "MID": ["Moore", "Allen", "Young", "King", "Wright", "Scott", "Baker", "Adams"],
        "FWD": ["Hill", "Nelson", "Carter", "Mitchell", "Roberts"],
    }

    teams = db.query(Team).filter(Team.division_id == division.id).all()
    for team in teams:
        existing_count = db.query(Player).filter(
            Player.team_id == team.id
        ).count()
        if existing_count > 10:
            continue

        for pos, names in player_names.items():
            for name in names:
                existing = db.query(Player).filter(
                    Player.name == f"{name} ({team.name})",
                ).first()
                if existing:
                    continue
                player = Player(
                    name=f"{name} ({team.name})",
                    web_name=f"{name.lower()}_{team.short_name}",
                    team_id=team.id,
                    position=pos,
                    price=round(random.uniform(3.0, 8.0), 1),
                    price_start=round(random.uniform(3.0, 8.0), 1),
                    is_active=True,
                )
                db.add(player)
                seeded_players += 1

    db.flush()

    # Create 24 gameweeks (full season)
    season = db.query(Season).filter(Season.name == "2025-26").first()
    if not season:
        season = Season(name="2025-26", total_gameweeks=24, started=True)
        db.add(season)
        db.flush()

    # Season starts Saturday August 16, 2025, each GW is 1 week, deadline is Saturday 11am
    season_start = date(2025, 8, 16)  # Saturday

    for gw_num in range(1, 25):
        gw = db.query(Gameweek).filter(
            Gameweek.number == gw_num,
            Gameweek.season == "2025-26",
        ).first()
        if not gw:
            start = season_start + timedelta(weeks=gw_num - 1)
            # Deadline is Saturday at 11:00 AM
            deadline = datetime(start.year, start.month, start.day, 11, 0)
            gw = Gameweek(
                number=gw_num,
                season="2025-26",
                start_date=start,
                end_date=start + timedelta(days=6),
                deadline=deadline,
                closed=gw_num > 2,
                scored=gw_num > 2,
            )
            db.add(gw)
            seeded_gws += 1

            # Create fixtures for this GW
            db.flush()
            shuffled_teams = list(teams[:10])  # Use first 10 teams
            random.shuffle(shuffled_teams)
            for i in range(0, len(shuffled_teams) - 1, 2):
                home = shuffled_teams[i]
                away = shuffled_teams[i + 1]
                fixture = Fixture(
                    gameweek_id=gw.id,
                    date=deadline + timedelta(hours=random.randint(0, 48)),
                    home_team_name=home.name,
                    away_team_name=away.name,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    home_difficulty=away.strength_attack or 3,
                    away_difficulty=home.strength_defense or 3,
                    played=gw_num <= 2,
                    home_score=random.randint(0, 4) if gw_num <= 2 else None,
                    away_score=random.randint(0, 4) if gw_num <= 2 else None,
                )
                db.add(fixture)
                seeded_fixtures += 1

    db.commit()

    return {
        "status": "seeded",
        "leagues": seeded_leagues,
        "teams": seeded_teams,
        "players": seeded_players,
        "gameweeks": seeded_gws,
        "fixtures": seeded_fixtures,
    }


@router.post("/create-sample-users")
def create_sample_users(db: Session = Depends(get_db)):
    """Create sample users with fantasy teams for testing."""
    users_created = 0
    teams_created = 0

    sample_users = [
        ("test_manager", "test@example.com", "password123", "Test FC"),
        ("demo_user", "demo@example.com", "password123", "Demo United"),
    ]

    players = db.query(Player).filter(Player.is_active == True).order_by(
        Player.price.desc()
    ).limit(30).all()

    if len(players) < 15:
        return {"status": "not_enough_players", "available": len(players)}

    for username, email, password, team_name in sample_users:
        existing = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing:
            continue

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
        users_created += 1

        # Create fantasy team with £90m budget
        ft = FantasyTeam(
            user_id=user.id,
            name=team_name,
            season="2025-26",
            budget=90.0,
            budget_remaining=90.0,
            free_transfers=1,
            free_transfers_next_gw=1,
        )
        db.add(ft)
        db.flush()

        # Add players to squad (13 players within £90m budget, no position restrictions)
        shuffled = list(players)
        random.shuffle(shuffled)

        squad = []
        budget = 90.0

        for player in shuffled:
            if len(squad) >= 13:
                break
            if budget < player.price:
                continue
            # Club limit: max 3 players from same team
            same_team = sum(1 for (p, _) in squad if p.team_id == player.team_id)
            if same_team >= 3:
                continue

            budget -= player.price
            squad.append((player, budget))

        # Add players with position slots (10 starters + 3 subs)
        slot = 1
        captain_set = False
        vice_captain_set = False

        for player, _ in squad:
            is_starting = slot <= 10
            sp = SquadPlayer(
                fantasy_team_id=ft.id,
                player_id=player.id,
                position_slot=slot,
                is_starting=is_starting,
                is_captain=not captain_set and is_starting,
                is_vice_captain=not vice_captain_set and is_starting and slot != (1 if not captain_set else 2),
                purchase_price=player.price,
                selling_price=player.price,
                bench_priority=slot - 10 if not is_starting else 99,
            )
            if sp.is_captain:
                captain_set = True
            elif not vice_captain_set and sp.is_starting:
                sp.is_vice_captain = True
                vice_captain_set = True

            db.add(sp)
            slot += 1

        ft.budget_remaining = budget
        teams_created += 1

    db.commit()

    return {
        "status": "created",
        "users": users_created,
        "teams": teams_created,
    }


@router.post("/recalculate-ranks")
def recalculate_ranks(db: Session = Depends(get_db)):
    """Recalculate overall ranks for all fantasy teams."""
    teams = db.query(FantasyTeam).order_by(
        FantasyTeam.total_points.desc(),
        FantasyTeam.id.asc(),
    ).all()

    for rank, team in enumerate(teams, 1):
        team.overall_rank = rank

    db.commit()
    return {"status": "ranks_updated", "total_teams": len(teams)}


@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    """Get administrative statistics about the database."""
    return {
        "leagues": db.query(League).count(),
        "divisions": db.query(Division).count(),
        "teams": db.query(Team).count(),
        "players": db.query(Player).count(),
        "gameweeks": db.query(Gameweek).count(),
        "fixtures": db.query(Fixture).count(),
        "users": db.query(User).count(),
        "fantasy_teams": db.query(FantasyTeam).count(),
        "mini_leagues": db.query(MiniLeague).count(),
        "h2h_leagues": db.query(H2hLeague).count(),
    }


@router.post("/sync-fixtures")
def manual_sync_fixtures():
    """Manually trigger fixture sync from FullTime API and score new results.

    This fetches the latest results from all IOM league divisions,
    updates fixtures in the database, and scores any gameweeks with
    new results. Walkovers award 2 points to the winning team's players.

    Use this when results appear on the FullTime API but the daily
    3am sync has already run for the day.
    """
    result = {"status": "started"}
    try:
        sync_fixtures()
        result["status"] = "completed"
        result["message"] = "Fixtures synced and scores updated"
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    return result


@router.post("/process-gameweek-end")
def manual_process_gameweek_end():
    """Manually trigger gameweek end processing.

    Scores the current gameweek, processes transfer rollovers,
    updates player prices, and reverts Free Hit squads.

    Normally runs automatically on Sunday at 11pm.
    """
    result = {"status": "started"}
    try:
        process_gameweek_end()
        result["status"] = "completed"
        result["message"] = "Gameweek end processed"
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    return result


@router.post("/sync-and-score")
def manual_sync_and_score():
    """Sync fixtures from FullTime API AND process gameweek end.

    Runs both sync_fixtures and process_gameweek_end in sequence.
    Use this to fully update the game state after new results appear.
    """
    sync_result = {"status": "started"}
    gw_result = {"status": "pending"}

    try:
        sync_fixtures()
        sync_result["status"] = "completed"
        sync_result["message"] = "Fixtures synced"
    except Exception as e:
        sync_result["status"] = "error"
        sync_result["message"] = str(e)

    try:
        process_gameweek_end()
        gw_result["status"] = "completed"
        gw_result["message"] = "Gameweek processed"
    except Exception as e:
        gw_result["status"] = "error"
        gw_result["message"] = str(e)

    return {
        "sync_fixtures": sync_result,
        "process_gameweek": gw_result,
    }

