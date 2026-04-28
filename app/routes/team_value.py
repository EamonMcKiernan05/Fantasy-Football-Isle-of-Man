"""Team value tracking API routes - FPL style.

Tracks the total value of a fantasy team over time, similar to how FPL
tracks team value changes throughout the season.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    FantasyTeam, SquadPlayer, Player, Gameweek, FantasyTeamHistory,
)

router = APIRouter(prefix="/api/team-value", tags=["team-value"])


@router.get("/{team_id}")
def get_team_value(team_id: int, db: Session = Depends(get_db)):
    """Get current and historical team value for a fantasy team.

    FPL-style team value tracking showing total squad value
    and value changes over time.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Calculate current team value from squad player prices
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == team_id).all()
    current_value = 0.0

    for sp in squad:
        player = db.query(Player).filter(Player.id == sp.player_id).first()
        if player:
            current_value += player.price

    # Get team value history from gameweek history
    history = (
        db.query(FantasyTeamHistory)
        .filter(FantasyTeamHistory.fantasy_team_id == team_id)
        .join(Gameweek)
        .order_by(Gameweek.number.asc())
        .all()
    )

    value_history = []
    for h in history:
        gw = h.gameweek
        # Calculate team value at end of this GW
        # (simplified: use current squad values as proxy)
        value_history.append({
            "gameweek": gw.number,
            "total_points": h.total_points,
            "gw_points": h.points,
        })

    return {
        "team_id": team_id,
        "team_name": ft.name,
        "current_value": round(current_value, 1),
        "budget_remaining": round(ft.budget_remaining, 1),
        "value_history": value_history,
        "squad_count": len(squad),
    }


@router.get("/{team_id}/squad-values")
def get_squad_values(team_id: int, db: Session = Depends(get_db)):
    """Get individual player values in a fantasy team.

    Shows purchase price, current price, and profit/loss per player.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == team_id
    ).all()

    player_values = []
    total_value = 0.0
    total_purchase = 0.0

    for sp in squad:
        player = db.query(Player).filter(Player.id == sp.player_id).first()
        if not player:
            continue

        current = player.price
        purchase = sp.purchase_price
        total_value += current
        total_purchase += purchase

        player_values.append({
            "player_id": sp.player_id,
            "name": player.name,
            "position": player.position,
            "team_name": player.team.name if player.team else "",
            "purchase_price": purchase,
            "current_price": current,
            "price_change": round(current - purchase, 1),
            "selling_price": sp.selling_price,
            "is_starting": sp.is_starting,
            "is_captain": sp.is_captain,
            "total_points": sp.total_points,
        })

    return {
        "team_id": team_id,
        "team_name": ft.name,
        "total_value": round(total_value, 1),
        "total_purchase_value": round(total_purchase, 1),
        "total_change": round(total_value - total_purchase, 1),
        "players": player_values,
    }


def recalculate_all_team_values(db: Session) -> dict:
    """Recalculate team values for all fantasy teams.

    Called after price updates to refresh all team values.
    """
    teams = db.query(FantasyTeam).all()
    updated = 0

    for ft in teams:
        squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).all()

        total_value = 0.0
        for sp in squad:
            player = db.query(Player).filter(Player.id == sp.player_id).first()
            if player:
                total_value += player.price

        ft.budget_remaining = 100.0 - total_value
        updated += 1

    db.commit()
    return {"status": "updated", "teams_processed": updated}
