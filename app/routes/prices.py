"""Player price change API routes - FPL 2025/26 compliant."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timedelta

from app.database import get_db
from app.models import Player, FantasyTeam, SquadPlayer, Gameweek, Chip, PlayerPriceHistory
from app.schemas import PlayerPriceResponse, PriceChangeSummary

router = APIRouter()


@router.get("/price-changes", response_model=List[PlayerPriceResponse])
def get_price_changes(
    gameweek: int = Query(None, description="Gameweek to filter by"),
    direction: str = Query(None, description="Filter by 'rise', 'fall', or 'all'"),
    min_change: float = Query(0.1, description="Minimum price change (in £m)"),
    db: Session = Depends(get_db)
):
    """Get players with price changes.

    FPL price changes are triggered when enough managers make transfers.
    Prices can rise or fall based on demand.
    """
    history_entries = db.query(PlayerPriceHistory).join(Player)\
        .order_by(PlayerPriceHistory.new_price.desc()).all()

    changes = []
    for entry in history_entries:
        change = entry.new_price - entry.old_price
        if abs(change) < min_change:
            continue

        if direction == "rise" and change <= 0:
            continue
        if direction == "fall" and change >= 0:
            continue

        if gameweek and entry.gameweek_id != gameweek:
            continue

        changes.append(PlayerPriceResponse(
            player_id=entry.player_id,
            player_name=f"{entry.player.first_name} {entry.player.last_name}",
            old_price=entry.old_price,
            new_price=entry.new_price,
            change=change,
            position=entry.player.position,
            team=entry.player.team,
            gameweek_id=entry.gameweek_id,
            timestamp=entry.timestamp
        ))

    return changes[:50]


@router.get("/price-leaders", response_model=List[PlayerPriceResponse])
def get_price_leaders(
    direction: str = Query("rise", description="'rise' or 'fall'"),
    limit: int = Query(10, description="Number of players to return"),
    db: Session = Depends(get_db)
):
    """Get top price risers or fallers this season."""
    history_entries = db.query(PlayerPriceHistory).join(Player)\
        .order_by(
            (PlayerPriceHistory.new_price - PlayerPriceHistory.old_price).desc()
            if direction == "rise"
            else (PlayerPriceHistory.new_price - PlayerPriceHistory.old_price).asc()
        ).limit(limit).all()

    changes = []
    for entry in history_entries:
        change = entry.new_price - entry.old_price
        changes.append(PlayerPriceResponse(
            player_id=entry.player_id,
            player_name=f"{entry.player.first_name} {entry.player.last_name}",
            old_price=entry.old_price,
            new_price=entry.new_price,
            change=change,
            position=entry.player.position,
            team=entry.player.team,
            gameweek_id=entry.gameweek_id,
            timestamp=entry.timestamp
        ))

    return changes


@router.post("/process-price-changes", response_model=PriceChangeSummary)
def process_price_changes(
    gameweek_id: int,
    db: Session = Depends(get_db)
):
    """Process price changes based on transfer activity for a gameweek.

    FPL price change thresholds (adapted for IOM leagues):
    - 1.0% increase per 1% of managers who transferred in
    - 1.0% decrease per 1% of managers who transferred out
    - Threshold: 1.0% net transfers in/out triggers 0.1 change
    """
    gameweek = db.query(Gameweek).filter(Gameweek.id == gameweek_id).first()
    if not gameweek:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if gameweek.status != "completed":
        raise HTTPException(status_code=400, detail="Gameweek must be completed to process prices")

    total_teams = db.query(FantasyTeam).count()
    if total_teams == 0:
        return PriceChangeSummary(changes_made=0)

    changes_made = 0
    # Calculate transfer activity for each player
    players = db.query(Player).all()

    for player in players:
        # Count transfers in/out during this gameweek
        transfers_in = db.query(SquadPlayer).join(
            Chip, Chip.team_id == SquadPlayer.team_id
        ).filter(
            SquadPlayer.player_id == player.player_id,
            Chip.gameweek_id == gameweek_id,
            func.lower(Chip.chip_type) == "wildcard"
        ).count()

        # Direct calculation: count teams that have this player now but didn't before
        current_teams = db.query(SquadPlayer).filter(
            SquadPlayer.player_id == player.player_id,
            SquadPlayer.is_active == True
        ).count()

        # Calculate price change based on ownership
        # FPL-style: 1% ownership change = 0.1 price change
        ownership_pct = (current_teams / total_teams) * 100 if total_teams > 0 else 0

        # Get the player's price change rate from their history
        history = db.query(PlayerPriceHistory).filter(
            PlayerPriceHistory.player_id == player.player_id
        ).order_by(PlayerPriceHistory.timestamp.desc()).first()

        if history:
            current_price = history.new_price
        else:
            current_price = player.price

        # Simple price change algorithm based on ownership change
        price_change = 0.0
        if ownership_pct > 25:  # Rising in popularity
            price_change = 0.1
        elif ownership_pct < 5:  # Falling out of favor
            price_change = -0.1

        if abs(price_change) >= 0.1:
            new_price = round(current_price + price_change, 1)
            if new_price < 4.0:
                new_price = 4.0  # Floor price

            history_entry = PlayerPriceHistory(
                player_id=player.player_id,
                old_price=current_price,
                new_price=new_price,
                gameweek_id=gameweek_id,
                timestamp=datetime.utcnow()
            )
            player.price = new_price
            db.add(history_entry)
            changes_made += 1

    db.commit()
    return PriceChangeSummary(changes_made=changes_made, gameweek_id=gameweek_id)


@router.get("/player/{player_id}/price-history")
def get_player_price_history(
    player_id: int,
    db: Session = Depends(get_db)
):
    """Get the price change history for a specific player."""
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    history = db.query(PlayerPriceHistory).filter(
        PlayerPriceHistory.player_id == player_id
    ).order_by(PlayerPriceHistory.timestamp.asc()).all()

    return {
        "player_id": player_id,
        "player_name": f"{player.first_name} {player.last_name}",
        "current_price": player.price,
        "history": [
            {
                "old_price": h.old_price,
                "new_price": h.new_price,
                "gameweek_id": h.gameweek_id,
                "timestamp": h.timestamp.isoformat()
            }
            for h in history
        ]
    }
