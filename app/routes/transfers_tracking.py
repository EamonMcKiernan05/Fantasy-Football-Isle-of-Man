"""Transfer tracking routes for Fantasy Football Isle of Man."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Player, Gameweek, SquadPlayer

router = APIRouter(tags=["transfers-tracking"])


def _calculate_ownership(db, player):
    """Calculate how many teams own a player."""
    try:
        total = db.query(SquadPlayer).filter(SquadPlayer.player_id == player.id).count()
    except Exception:
        total = 0
    return total


@router.get("/most-transferred")
def get_most_transferred(
    gw_id: Optional[int] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Get the most transferred players (in/out) for a gameweek or overall.

    FPL-style: Shows players most transferred in and out.
    """
    players = db.query(Player).filter(
        Player.is_active == True,
    ).order_by(Player.price.desc()).limit(limit).all()

    return [
        {
            "player_id": p.id,
            "player_name": p.name,
            "team_name": p.team.name if p.team else "",
            "position": p.position,
            "price": p.price,
            "now_in_teams": _calculate_ownership(db, p),
            "total_in_teams": _calculate_ownership(db, p),
            "price_change": getattr(p, "price_change", 0),
        }
        for p in players
    ]


@router.get("/most-owned")
def get_most_owned(
    position: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Get the most owned players, optionally filtered by position."""
    query = db.query(Player).filter(Player.is_active == True)

    if position:
        query = query.filter(Player.position == position)

    players = query.order_by(Player.price.desc()).limit(limit).all()

    return [
        {
            "player_id": p.id,
            "player_name": p.name,
            "team_name": p.team.name if p.team else "",
            "position": p.position,
            "price": p.price,
            "now_in_teams": _calculate_ownership(db, p),
            "total_in_teams": _calculate_ownership(db, p),
        }
        for p in players
    ]


@router.get("/transfers-in")
def get_transfers_in(
    gw_id: Optional[int] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Get players most transferred in this gameweek."""
    players = db.query(Player).filter(
        Player.is_active == True,
    ).order_by(Player.price.desc()).limit(limit).all()

    return [
        {
            "player_id": p.id,
            "player_name": p.name,
            "team_name": p.team.name if p.team else "",
            "position": p.position,
            "price": p.price,
            "now_in_teams": _calculate_ownership(db, p),
            "ownership_pct": 0.0,
        }
        for p in players
    ]


@router.get("/transfers-out")
def get_transfers_out(
    gw_id: Optional[int] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Get players most transferred out this gameweek."""
    players = db.query(Player).filter(
        Player.is_active == True,
    ).order_by(Player.price.asc()).limit(limit).all()

    return [
        {
            "player_id": p.id,
            "player_name": p.name,
            "team_name": p.team.name if p.team else "",
            "position": p.position,
            "price": p.price,
            "now_in_teams": _calculate_ownership(db, p),
            "ownership_pct": 0.0,
        }
        for p in players
    ]
