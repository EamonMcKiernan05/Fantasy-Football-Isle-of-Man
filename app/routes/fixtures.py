"""Fixture management and difficulty API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import Optional

from app.database import get_db
from app.models import Fixture, Gameweek, Player, Team

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])


@router.get("/")
def list_fixtures(
    gameweek_id: Optional[int] = Query(None, description="Filter by gameweek ID"),
    season: str = Query("2025-26", description="Season to filter by"),
    db: Session = Depends(get_db),
):
    """List all fixtures, optionally filtered by gameweek."""
    query = db.query(Fixture).join(Gameweek).filter(Gameweek.season == season)

    if gameweek_id:
        query = query.filter(Fixture.gameweek_id == gameweek_id)

    fixtures = query.order_by(Fixture.date.asc()).all()

    return {
        "fixtures": [
            {
                "id": f.id,
                "gameweek_id": f.gameweek_id,
                "date": f.date.isoformat() if f.date else None,
                "home_team": f.home_team_name,
                "away_team": f.away_team_name,
                "home_score": f.home_score,
                "away_score": f.away_score,
                "played": f.played,
                "half_time_home": f.half_time_home,
                "half_time_away": f.half_time_away,
                "home_difficulty": f.home_difficulty,
                "away_difficulty": f.away_difficulty,
            }
            for f in fixtures
        ],
    }


@router.get("/fixtures-for-player/{player_id}")
def get_player_fixtures(
    player_id: int,
    next_n: int = Query(5, description="Number of upcoming fixtures to return"),
    db: Session = Depends(get_db),
):
    """Get upcoming and recent fixtures for a player's team.

    FPL-style fixture difficulty schedule showing upcoming matches.
    """
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    team_id = player.team_id

    # Get team's fixtures
    fixtures = (
        db.query(Fixture)
        .filter(
            (Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id),
        )
        .order_by(Fixture.date.asc())
        .all()
    )

    result = {
        "player_name": player.name,
        "team_id": team_id,
        "team_name": player.team.name if player.team else "Unknown",
        "upcoming": [],
        "recent": [],
    }

    now = datetime.utcnow()
    for f in fixtures:
        is_home = f.home_team_id == team_id
        opponent = f.away_team_name if is_home else f.home_team_name
        difficulty = f.away_difficulty if is_home else f.home_difficulty

        entry = {
            "fixture_id": f.id,
            "gameweek_id": f.gameweek_id,
            "date": f.date.isoformat() if f.date else None,
            "opponent": opponent,
            "is_home": is_home,
            "difficulty": difficulty,
            "played": f.played,
            "score": f"{f.home_score}-{f.away_score}" if f.played else None,
        }

        if f.played or (f.date and f.date < now):
            result["recent"].append(entry)
        else:
            result["upcoming"].append(entry)

    result["upcoming"] = result["upcoming"][:next_n]
    result["recent"] = result["recent"][-5:]

    return result


@router.post("/calculate-difficulties")
def calculate_fixture_difficulties(db: Session = Depends(get_db)):
    """Calculate fixture difficulty ratings based on team strength.

    FPL-style difficulty ratings (1=easiest, 5=hardest) based on team
    league position, goals for/against, and form.
    """
    teams = db.query(Team).filter(
        Team.current_position.isnot(None),
    ).order_by(Team.current_position.asc()).all()

    if not teams:
        return {"status": "no_teams", "message": "No teams with positions to calculate difficulty"}

    # Update team strength ratings based on league position
    for i, team in enumerate(teams):
        position = team.current_position
        total = len(teams)

        # Strength based on position (1 = strongest)
        if total > 0:
            rank_pct = (position - 1) / (total - 1) if total > 1 else 0
            # Difficulty: teams at top have high attack/home/away/defense strength
            # Teams at bottom have low strength (easier to play against)
            strength = round(5 - (rank_pct * 4), 0)  # Range: 1-5
            team.strength_attack = int(strength)
            team.strength_defense = int(strength)
            team.strength_home = int(min(5, strength + 0.5))
            team.strength_away = int(min(5, strength - 0.5))

    # Build team lookup
    team_map = {}
    for team in db.query(Team).all():
        team_map[team.id] = team

    # Calculate fixture difficulties
    fixtures = db.query(Fixture).all()
    updated = 0

    for fixture in fixtures:
        home = team_map.get(fixture.home_team_id)
        away = team_map.get(fixture.away_team_id)

        if home and away:
            # Home difficulty = away team's attack strength
            fixture.home_difficulty = away.strength_attack or 3
            # Away difficulty = home team's defense strength
            fixture.away_difficulty = home.strength_defense or 3

            # Adjust for home advantage
            if home.strength_home > away.strength_away:
                fixture.away_difficulty = min(5, fixture.away_difficulty + 1)
            elif home.strength_home < away.strength_away:
                fixture.away_difficulty = max(1, fixture.away_difficulty - 1)

            updated += 1

    db.commit()

    return {
        "status": "calculated",
        "teams_updated": len(teams),
        "fixtures_updated": updated,
    }


@router.get("/progress/{gameweek_id}")
def get_gameweek_progress(gameweek_id: int, db: Session = Depends(get_db)):
    """Get live scoring progress for a gameweek.

    Returns percentage of fixtures completed, used for progress bar display.
    """
    fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gameweek_id).all()

    total = len(fixtures)
    played = sum(1 for f in fixtures if f.played)

    progress = round((played / total) * 100, 1) if total > 0 else 0

    return {
        "gameweek_id": gameweek_id,
        "total_fixtures": total,
        "fixtures_played": played,
        "fixtures_remaining": total - played,
        "progress_percent": progress,
        "is_complete": played == total,
    }


@router.get("/player-team-players/{team_id}")
def get_team_players(team_id: int, db: Session = Depends(get_db)):
    """Get all players for a team with their fixture schedules."""
    players = (
        db.query(Player)
        .filter(Player.team_id == team_id, Player.is_active == True)
        .order_by(Player.position, Player.name)
        .all()
    )

    return {
        "team_id": team_id,
        "team_name": db.query(Team).filter(Team.id == team_id).first().name if team_id else None,
        "players": [
            {
                "id": p.id,
                "name": p.name,
                "position": p.position,
                "price": p.price,
                "selected_by_percent": p.selected_by_percent,
                "form": p.form,
                "total_points": p.total_points_season,
                "ict_index": p.ict_index,
                "is_injured": p.is_injured,
                "injury_status": p.injury_status,
            }
            for p in players
        ],
    }
