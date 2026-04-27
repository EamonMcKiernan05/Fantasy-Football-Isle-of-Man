"""Leaderboard API routes - FPL style."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models import (
    FantasyTeam, User, FantasyTeamHistory, Gameweek, SquadPlayer, Player,
)

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("/")
def get_leaderboard(
    season: str = Query("2025-26", description="Season to filter by"),
    limit: int = Query(100, description="Number of entries to return"),
    offset: int = Query(0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """Get the overall leaderboard for all fantasy teams.

    FPL-style ranking:
    - Sorted by total points (desc), then by rank_sort_index (asc) for ties
    """
    total_count = db.query(FantasyTeam).filter(
        FantasyTeam.season == season
    ).count()

    teams = (
        db.query(FantasyTeam)
        .join(User)
        .filter(FantasyTeam.season == season)
        .order_by(FantasyTeam.total_points.desc(), FantasyTeam.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Get current gameweek points for each team
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.number.desc()).first()

    entries = []
    for rank, ft in enumerate(teams[offset:], start=offset + 1):
        gw_points = None
        if current_gw:
            history = db.query(FantasyTeamHistory).filter(
                FantasyTeamHistory.fantasy_team_id == ft.id,
                FantasyTeamHistory.gameweek_id == current_gw.id,
            ).first()
            if history:
                gw_points = history.points

        entries.append({
            "rank": rank,
            "user_id": ft.user_id,
            "username": ft.user.username,
            "team_name": ft.name,
            "total_points": ft.total_points,
            "gameweek_points": gw_points,
            "overall_rank": ft.overall_rank,
        })

    return {
        "season": season,
        "total_teams": total_count,
        "offset": offset,
        "limit": limit,
        "entries": entries,
    }


@router.get("/top-5")
def get_top_5(db: Session = Depends(get_db)):
    """Get the top 5 fantasy teams globally."""
    teams = (
        db.query(FantasyTeam)
        .join(User)
        .order_by(FantasyTeam.total_points.desc())
        .limit(5)
        .all()
    )

    entries = []
    for rank, ft in enumerate(teams, 1):
        entries.append({
            "rank": rank,
            "username": ft.user.username,
            "team_name": ft.name,
            "total_points": ft.total_points,
            "overall_rank": ft.overall_rank,
        })

    return {"top_5": entries}


@router.get("/gameweek/{gw_id}")
def get_gameweek_leaderboard(
    gw_id: int,
    limit: int = Query(50, description="Number of entries to return"),
    db: Session = Depends(get_db),
):
    """Get the leaderboard for a specific gameweek (top scorers)."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    history = (
        db.query(FantasyTeamHistory)
        .filter(FantasyTeamHistory.gameweek_id == gw_id)
        .join(FantasyTeam)
        .join(User)
        .order_by(FantasyTeamHistory.points.desc())
        .limit(limit)
        .all()
    )

    entries = []
    for rank, fth in enumerate(history, 1):
        entries.append({
            "rank": rank,
            "user_id": fth.fantasy_team.user_id,
            "username": fth.fantasy_team.user.username,
            "team_name": fth.fantasy_team.name,
            "points": fth.points,
            "chip_used": fth.chip_used,
            "transfers_cost": fth.transfers_cost,
        })

    return {
        "gameweek": gw.number,
        "season": gw.season,
        "entries": entries,
    }


@router.get("/{user_id}/rank")
def get_user_rank(user_id: int, db: Session = Depends(get_db)):
    """Get a user's current rank in the overall leaderboard.

    Returns detailed ranking info including percentile.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Calculate rank (number of teams with more points + 1)
    rank = (
        db.query(FantasyTeam)
        .filter(
            FantasyTeam.total_points > ft.total_points,
        )
        .count()
    ) + 1

    total = db.query(FantasyTeam).count()

    # Calculate percentile
    percentile = round((1 - (rank - 1) / max(total, 1)) * 100, 1) if total > 0 else 0

    # Get rank change from last GW
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    rank_change = None
    if current_gw:
        # Compare with previous GW rank
        prev_gw = db.query(Gameweek).filter(
            Gameweek.number < current_gw.number,
            Gameweek.season == current_gw.season,
        ).order_by(Gameweek.number.desc()).first()

        if prev_gw:
            prev_history = db.query(FantasyTeamHistory).filter(
                FantasyTeamHistory.fantasy_team_id == ft.id,
                FantasyTeamHistory.gameweek_id == prev_gw.id,
            ).first()
            if prev_history and prev_history.rank:
                rank_change = prev_history.rank - rank

    return {
        "user_id": user_id,
        "team_name": ft.name,
        "total_points": ft.total_points,
        "rank": rank,
        "total_teams": total,
        "percentile": percentile,
        "rank_change": rank_change,
    }


@router.get("/{user_id}/history")
def get_user_history(user_id: int, db: Session = Depends(get_db)):
    """Get a user's gameweek-by-gameweek history."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    history = (
        db.query(FantasyTeamHistory)
        .filter(FantasyTeamHistory.fantasy_team_id == ft.id)
        .join(Gameweek)
        .order_by(Gameweek.number.asc())
        .all()
    )

    entries = []
    for h in history:
        gw = h.gameweek
        entries.append({
            "gameweek": gw.number,
            "points": h.points,
            "total_points": h.total_points,
            "rank": h.rank,
            "chip_used": h.chip_used,
            "transfers_made": h.transfers_made,
            "transfers_cost": h.transfers_cost,
        })

    return {
        "team_name": ft.name,
        "history": entries,
    }


@router.post("/calculate-ranks")
def calculate_all_ranks(db: Session = Depends(get_db)):
    """Recalculate overall ranks for all teams.

    Called after scoring to update ranks.
    """
    teams = db.query(FantasyTeam).order_by(
        FantasyTeam.total_points.desc(),
        FantasyTeam.id.asc(),
    ).all()

    for rank, team in enumerate(teams, 1):
        team.overall_rank = rank

    db.commit()

    return {
        "status": "ranks_calculated",
        "total_teams": len(teams),
    }
