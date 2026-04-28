"""Gameweek history and deadline API routes.

Provides FPL-style gameweek history, deadline countdown,
and detailed gameweek breakdowns.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import (
    FantasyTeam, Gameweek, FantasyTeamHistory, SquadPlayer, Player,
    GameweekStats, Transfer,
)

router = APIRouter(prefix="/api/gameweek-history", tags=["gameweek-history"])


@router.get("/current-gw-info")
def get_current_gw_info(db: Session = Depends(get_db)):
    """Get current gameweek information including deadline.

    Returns current GW number, deadline, status, and countdown info.
    """
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    if not current_gw:
        # Check if season hasn't started
        all_gws = db.query(Gameweek).order_by(Gameweek.number.asc()).all()
        if all_gws:
            return {
                "status": "season_not_started",
                "next_gameweek": all_gws[0].number,
                "next_deadline": all_gws[0].deadline.isoformat() if all_gws[0].deadline else None,
            }
        return {"status": "no_gameweeks", "message": "No gameweeks configured"}

    now = datetime.utcnow()
    deadline = current_gw.deadline
    time_remaining = deadline - now if deadline else None

    return {
        "gameweek_number": current_gw.number,
        "gameweek_id": current_gw.id,
        "season": current_gw.season,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_unix": int(deadline.timestamp()) if deadline else None,
        "is_closed": current_gw.closed,
        "is_scored": current_gw.scored,
        "bonus_calculated": current_gw.bonus_calculated,
        "time_remaining_seconds": int(time_remaining.total_seconds()) if time_remaining else None,
        "time_remaining_formatted": _format_countdown(time_remaining) if time_remaining else "N/A",
    }


@router.get("/{team_id}/{gameweek_id}")
def get_gameweek_breakdown(
    team_id: int,
    gameweek_id: int,
    db: Session = Depends(get_db),
):
    """Get detailed gameweek breakdown for a fantasy team.

    FPL-style per-player points breakdown including:
    - Points from each player in starting XI
    - Bench points
    - Captain multiplier
    - Transfer hits
    - Chip used
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    history = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.fantasy_team_id == team_id,
        FantasyTeamHistory.gameweek_id == gameweek_id,
    ).first()

    if not history:
        raise HTTPException(status_code=404, detail="No history for this gameweek")

    # Get squad players and their points
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == team_id
    ).all()

    player_breakdown = []
    total_starting = 0
    total_bench = 0

    for sp in squad:
        # Get player gameweek points
        gwp = db.query(GameweekStats).filter(
            GameweekStats.player_id == sp.player_id,
            GameweekStats.gameweek_id == gameweek_id,
        ).first()

        player = db.query(Player).filter(Player.id == sp.player_id).first()
        points = gwp.points if gwp else 0
        did_play = gwp is not None and gwp.minutes_played > 0 if gwp else False

        breakdown = {
            "player_id": sp.player_id,
            "name": player.name if player else "Unknown",
            "position": player.position if player else "?",
            "team_name": player.team.name if player and player.team else "",
            "is_starting": sp.is_starting,
            "is_captain": sp.is_captain,
            "is_vice_captain": sp.is_vice_captain,
            "was_autosub": sp.was_autosub,
            "points": points,
            "did_play": did_play,
            "minutes": gwp.minutes_played if gwp else 0,
            "goals": gwp.goals if gwp else 0,
            "assists": gwp.assists if gwp else 0,
            "clean_sheets": gwp.clean_sheets if gwp else 0,
            "saves": gwp.saves if gwp else 0,
            "bonus": gwp.bps if gwp else 0,
        }

        if sp.is_starting:
            total_starting += points
        else:
            total_bench += points

        player_breakdown.append(breakdown)

    # Calculate captain multiplier
    captain_player = next((p for p in player_breakdown if p["is_captain"]), None)
    captain_bonus = 0
    if captain_player and captain_player["did_play"]:
        chip = history.chip_used
        multiplier = 3 if chip == "triple_captain" else 2
        captain_bonus = captain_player["points"] * (multiplier - 1)

    return {
        "gameweek": gw.number,
        "season": gw.season,
        "team_name": ft.name,
        "total_points": history.points,
        "starting_points": total_starting,
        "bench_points": total_bench,
        "captain_bonus": captain_bonus,
        "transfers_cost": history.transfers_cost,
        "chip_used": history.chip_used,
        "rank": history.rank,
        "player_breakdown": player_breakdown,
    }


@router.get("/deadline/{gameweek_id}")
def get_deadline_info(gameweek_id: int, db: Session = Depends(get_db)):
    """Get deadline countdown information for a gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    now = datetime.utcnow()
    deadline = gw.deadline
    time_remaining = deadline - now if deadline else None

    return {
        "gameweek_id": gw.id,
        "gameweek_number": gw.number,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_unix": int(deadline.timestamp()) if deadline else None,
        "is_closed": gw.closed,
        "time_remaining_seconds": int(time_remaining.total_seconds()) if time_remaining else 0,
        "time_remaining_formatted": _format_countdown(time_remaining),
    }


@router.get("/transfer-history/{team_id}")
def get_transfer_history(
    team_id: int,
    gameweek_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get transfer history for a fantasy team.

    FPL-style transfer history showing players in/out per gameweek.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    user_id = ft.user_id

    query = db.query(Transfer).filter(
        Transfer.user_id == user_id
    ).order_by(Transfer.created_at.desc())

    if gameweek_id:
        query = query.filter(Transfer.gameweek_id == gameweek_id)

    transfers = query.all()

    history = []
    for t in transfers:
        player_in = db.query(Player).filter(Player.id == t.player_in_id).first()
        player_out = db.query(Player).filter(Player.id == t.player_out_id).first()
        gw = db.query(Gameweek).filter(Gameweek.id == t.gameweek_id).first()

        history.append({
            "player_in": {
                "id": t.player_in_id,
                "name": player_in.name if player_in else "Unknown",
                "position": player_in.position if player_in else "?",
                "team": player_in.team.name if player_in and player_in.team else "",
                "price": player_in.price if player_in else 0,
            } if player_in else None,
            "player_out": {
                "id": t.player_out_id,
                "name": player_out.name if player_out else "Unknown",
                "position": player_out.position if player_out else "?",
                "team": player_out.team.name if player_out and player_out.team else "",
                "price": player_out.price if player_out else 0,
                "points_scored": t.points_scored_by_outgoing,
            } if player_out else None,
            "gameweek": gw.number if gw else None,
            "is_wildcard": t.is_wildcard,
            "is_free_hit": t.is_free_hit,
            "timestamp": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "team_name": ft.name,
        "transfers": history,
    }


def _format_countdown(td: timedelta) -> str:
    """Format a timedelta as a countdown string."""
    if td is None or td.total_seconds() < 0:
        return "Expired"

    total_seconds = int(td.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")

    return " ".join(parts)
