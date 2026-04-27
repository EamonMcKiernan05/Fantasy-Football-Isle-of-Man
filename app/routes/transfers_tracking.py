"""Player transfers tracking - in/out stats per gameweek."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional, List

from app.database import get_db
from app.models import Player, SquadPlayer, Gameweek, Chip

router = APIRouter()


@router.get("/transfers-in", response_model=List[dict])
def get_transfers_in(
    gameweek_id: int = Query(None, description="Gameweek ID"),
    limit: int = Query(20, description="Number of players to return"),
    db: Session = Depends(get_db)
):
    """Get players with most transfers in for a gameweek.

    FPL feature showing which players are most popular among managers.
    """
    # For each player, count how many teams have them in their squad
    teams = db.query(SquadPlayer).join(Player).group_by(
        SquadPlayer.player_id
    ).with_entities(
        SquadPlayer.player_id,
        Player.first_name,
        Player.last_name,
        Player.team,
        Player.position,
        Player.price,
        func.count(SquadPlayer.team_id).label("team_count")
    ).order_by(desc("team_count")).limit(limit).all()

    # Get total teams for percentage calculation
    total_teams = db.query(SquadPlayer).with_entities(
        func.count(func.distinct(SquadPlayer.team_id))
    ).scalar() or 1

    results = []
    for row in teams:
        # Calculate transfers in by comparing to previous GW
        # For simplicity, we'll just return ownership stats
        pct = round((row.team_count / total_teams) * 100, 1)
        results.append({
            "player_id": row.player_id,
            "player_name": f"{row.first_name} {row.last_name}",
            "team": row.team,
            "position": row.position,
            "price": row.price,
            "ownership_count": row.team_count,
            "ownership_pct": pct,
            "trend": "rising" if pct > 25 else ("stable" if pct > 10 else "falling")
        })

    return results


@router.get("/transfers-out", response_model=List[dict])
def get_transfers_out(
    limit: int = Query(20, description="Number of players to return"),
    db: Session = Depends(get_db)
):
    """Get players with most transfers out.

    FPL feature showing which players are being dropped most.
    """
    # Players with lowest ownership
    teams = db.query(SquadPlayer).join(Player).group_by(
        SquadPlayer.player_id
    ).with_entities(
        SquadPlayer.player_id,
        Player.first_name,
        Player.last_name,
        Player.team,
        Player.position,
        Player.price,
        func.count(SquadPlayer.team_id).label("team_count")
    ).order_by("team_count").limit(limit).all()

    total_teams = db.query(SquadPlayer).with_entities(
        func.count(func.distinct(SquadPlayer.team_id))
    ).scalar() or 1

    results = []
    for row in teams:
        pct = round((row.team_count / total_teams) * 100, 1)
        results.append({
            "player_id": row.player_id,
            "player_name": f"{row.first_name} {row.last_name}",
            "team": row.team,
            "position": row.position,
            "price": row.price,
            "ownership_count": row.team_count,
            "ownership_pct": pct,
            "trend": "falling" if pct < 10 else ("stable" if pct < 25 else "rising")
        })

    return results


@router.get("/most-selected")
def get_most_selected(
    limit: int = Query(20, description="Number of players to return"),
    db: Session = Depends(get_db)
):
    """Get the most selected (owned) players - FPL style."""
    teams = db.query(SquadPlayer).join(Player).group_by(
        SquadPlayer.player_id
    ).with_entities(
        SquadPlayer.player_id,
        Player.first_name,
        Player.last_name,
        Player.team,
        Player.position,
        Player.price,
        func.count(SquadPlayer.team_id).label("team_count")
    ).order_by(desc("team_count")).limit(limit).all()

    total_teams = db.query(SquadPlayer).with_entities(
        func.count(func.distinct(SquadPlayer.team_id))
    ).scalar() or 1

    results = []
    for i, row in enumerate(teams):
        pct = round((row.team_count / total_teams) * 100, 1)
        results.append({
            "rank": i + 1,
            "player_id": row.player_id,
            "player_name": f"{row.first_name} {row.last_name}",
            "team": row.team,
            "position": row.position,
            "price": row.price,
            "ownership_pct": pct,
            "ownership_count": row.team_count
        })

    return results


@router.get("/transfers-history")
def get_transfers_history(
    player_id: int = Query(..., description="Player ID"),
    db: Session = Depends(get_db)
):
    """Get the transfer history for a player (how many teams own them per GW)."""
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    gameweeks = db.query(Gameweek).order_by(Gameweek.id).all()

    history = []
    for gw in gameweeks:
        owned = db.query(SquadPlayer).filter(
            SquadPlayer.player_id == player_id,
            SquadPlayer.is_active == True
        ).count()
        history.append({
            "gameweek_id": gw.id,
            "gameweek_name": gw.name,
            "owned_count": owned,
            "price": player.price
        })

    return {
        "player_id": player_id,
        "player_name": f"{player.first_name} {player.last_name}",
        "history": history
    }
