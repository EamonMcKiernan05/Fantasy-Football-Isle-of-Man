"""Leaderboard API routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.database import get_db
from app.models import FantasyTeam, User, FantasyTeamHistory, Gameweek
from app.schemas import LeaderboardResponse, LeaderboardEntry

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("/", response_model=LeaderboardResponse)
def get_leaderboard(db: Session = Depends(get_db)):
    """Get the overall leaderboard."""
    teams = (
        db.query(FantasyTeam)
        .join(User)
        .order_by(FantasyTeam.total_points.desc())
        .all()
    )
    
    entries = []
    for rank, ft in enumerate(teams, 1):
        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=ft.user_id,
            username=ft.user.username,
            team_name=ft.name,
            total_points=ft.total_points,
        ))
    
    return LeaderboardResponse(
        season="2025-26",
        entries=entries,
    )


@router.get("/gameweek/{gw_id}", response_model=LeaderboardResponse)
def get_gameweek_leaderboard(gw_id: int, db: Session = Depends(get_db)):
    """Get the leaderboard for a specific gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        return LeaderboardResponse(season=gw.season if gw else "2025-26")
    
    history = (
        db.query(FantasyTeamHistory)
        .filter(FantasyTeamHistory.gameweek_id == gw_id)
        .join(FantasyTeam)
        .join(User)
        .order_by(FantasyTeamHistory.points.desc())
        .all()
    )
    
    entries = []
    for rank, fth in enumerate(history, 1):
        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=fth.fantasy_team.user_id,
            username=fth.fantasy_team.user.username,
            team_name=fth.fantasy_team.name,
            total_points=fth.points,
        ))
    
    return LeaderboardResponse(season="2025-26", entries=entries)
