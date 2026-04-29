"""Player comparison API - FPL style.

Side-by-side player comparison with stats, fixtures, and form.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Player, Team, Gameweek, Fixture, GameweekStats

router = APIRouter(prefix="/api/compare", tags=["player-compare"])


@router.get("/players/{player_ids}")
def compare_players(
    player_ids: str,
    gameweek_id: Optional[int] = Query(None, description="Specific GW to compare"),
    db: Session = Depends(get_db),
):
    """Compare multiple players side by side.

    player_ids: Comma-separated list of player IDs (e.g., "1,2,3")

    Returns detailed comparison with:
    - Season stats
    - Form (last 5 GWs)
    - Fixture difficulty
    - Price and ownership
    - ICT index
    """
    ids = [int(pid.strip()) for pid in player_ids.split(",") if pid.strip()]

    if len(ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 player IDs required for comparison"
        )

    if len(ids) > 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum 5 players can be compared at once"
        )

    players = db.query(Player).filter(Player.id.in_(ids)).all()

    if len(players) < 2:
        raise HTTPException(
            status_code=404,
            detail="Not enough valid players found"
        )

    result = []
    for player in players:
        # Get last 5 GW stats for form
        recent_stats = (
            db.query(GameweekStats)
            .filter(GameweekStats.player_id == player.id)
            .order_by(GameweekStats.gameweek_id.desc())
            .limit(5)
            .all()
        )

        # Get upcoming fixtures
        upcoming = _get_upcoming_fixtures(db, player.team_id, limit=5)

        # Calculate form
        form_points = [s.points for s in recent_stats if s.points is not None]
        form_avg = round(sum(form_points) / len(form_points), 1) if form_points else 0.0

        result.append({
            "id": player.id,
            "name": player.name,
            "web_name": player.web_name,
            "team": player.team.name if player.team else "",
            "team_code": player.team.code if player.team else "",
            "position": player.position,
            "price": player.price,
            "price_change": player.price_change,
            "selected_by_percent": player.selected_by_percent,
            "total_points": player.total_points_season,
            "goals": player.goals,
            "assists": player.assists,
            "clean_sheets": player.clean_sheets,
            "bonus": player.bonus,
            "form": form_avg,
            "ict_index": player.ict_index,
            "influence": player.influence,
            "creativity": player.creativity,
            "threat": player.threat,
            "is_injured": player.is_injured,
            "injury_status": player.injury_status,
            "fixtures": upcoming,
            "recent_form": form_points,
        })

    return {
        "players": result,
        "comparison_count": len(result),
    }


@router.get("/best-value")
def get_best_value_players(
    position: Optional[str] = Query(None, description="Filter by position"),
    limit: int = Query(10, description="Number of players to return"),
    min_price: float = Query(4.0, description="Minimum price"),
    max_price: float = Query(8.0, description="Maximum price"),
    db: Session = Depends(get_db),
):
    """Find best value players (points per million spent).

    FPL-style value analysis showing which players give the best
    return on investment.
    """
    query = db.query(Player).filter(
        Player.is_active == True,
        Player.price >= min_price,
        Player.price <= max_price,
        Player.total_points_season > 0,
    )

    if position:
        query = query.filter(Player.position == position)

    players = query.order_by(
        Player.total_points_season.desc()
    ).limit(limit).all()

    result = []
    for p in players:
        value = round((p.total_points_season or 0) / (p.price or 1), 2)
        result.append({
            "id": p.id,
            "name": p.name,
            "team": p.team.name if p.team else "",
            "position": p.position,
            "price": p.price,
            "total_points": p.total_points_season,
            "value_per_million": value,
            "form": p.form,
            "selected_by_percent": p.selected_by_percent,
        })

    # Sort by value
    result.sort(key=lambda x: x["value_per_million"], reverse=True)

    return {
        "players": result,
        "criteria": {
            "position": position,
            "min_price": min_price,
            "max_price": max_price,
        },
    }


def _get_upcoming_fixtures(db: Session, team_id: int, limit: int = 5) -> list:
    """Get upcoming fixtures for a team with difficulty."""
    from datetime import datetime

    now = datetime.utcnow()
    fixtures = (
        db.query(Fixture)
        .filter(
            ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
            Fixture.played == False,
        )
        .order_by(Fixture.date.asc())
        .limit(limit)
        .all()
    )

    result = []
    for f in fixtures:
        is_home = f.home_team_id == team_id
        opponent = f.away_team_name if is_home else f.home_team_name
        difficulty = f.away_difficulty if is_home else f.home_difficulty

        result.append({
            "opponent": opponent,
            "is_home": is_home,
            "difficulty": difficulty,
            "date": f.date.isoformat() if f.date else None,
            "gameweek_id": f.gameweek_id,
        })

    return result
