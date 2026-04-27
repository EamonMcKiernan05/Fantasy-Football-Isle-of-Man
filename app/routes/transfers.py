"""Transfer API routes - FPL rules compliant."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Transfer, Gameweek, Season,
)
from app.schemas import TransferRequest
from app import scoring

router = APIRouter(prefix="/api/transfers", tags=["transfers"])

# FPL transfer constants
MAX_ROLLOVER_TRANSFERS = 5
TRANSFER_HIT = 4  # -4 points per extra transfer


@router.post("/")
def make_transfer(
    user_id: int,
    transfer: TransferRequest,
    db: Session = Depends(get_db),
):
    """Make a transfer (swap one player for another).

    FPL Transfer Rules:
    - 1 free transfer per gameweek
    - Unused transfers rollover (max 5)
    - Extra transfers cost -4 points each
    - Wildcard: unlimited transfers, no point hit
    - Two wildcards per season (first half: GW 1-19, second half: GW 20-38)
    - Cannot transfer same player in and out
    - Incoming player must not already be in squad
    - Max 3 players per club
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Check players exist
    player_in = db.query(Player).filter(Player.id == transfer.player_in_id).first()
    player_out = db.query(Player).filter(Player.id == transfer.player_out_id).first()

    if not player_in:
        raise HTTPException(status_code=404, detail="Incoming player not found")
    if not player_out:
        raise HTTPException(status_code=404, detail="Outgoing player not found")

    # Cannot transfer same player
    if player_in.id == player_out.id:
        raise HTTPException(status_code=400, detail="Cannot transfer a player for themselves")

    # Check outgoing player is in squad
    squad_out = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        SquadPlayer.player_id == transfer.player_out_id,
    ).first()
    if not squad_out:
        raise HTTPException(status_code=400, detail="Outgoing player not in your squad")

    # Check incoming player is not already in squad
    existing = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        SquadPlayer.player_id == transfer.player_in_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Player already in your squad")

    # Max 3 players per club (FPL rule)
    if player_in.team_id == player_out.team_id:
        raise HTTPException(status_code=400, detail="Cannot transfer within same club")

    # Count players from incoming club in squad (excluding outgoing if same team)
    players_from_incoming_club = db.query(SquadPlayer).join(Player).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        Player.team_id == player_in.team_id,
    ).count()
    if players_from_incoming_club >= 3:
        raise HTTPException(
            status_code=400,
            detail=f"Already have 3 players from {player_in.team.name if player_in.team else 'that club'}. Max 3 per club.",
        )

    # Check budget
    price_diff = player_in.price - player_out.price
    if not transfer.use_wildcard and price_diff > ft.budget_remaining:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot afford transfer. Need {price_diff:.1f}m, have {ft.budget_remaining:.1f}m",
        )

    # Get current gameweek
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    # Get season config
    season = db.query(Season).filter(
        Season.name == ft.season
    ).first()

    if current_gw:
        # Check if deadline has passed
        if datetime.utcnow() > current_gw.deadline:
            raise HTTPException(status_code=400, detail="Transfer deadline has passed")

    # Process wildcard
    is_wildcard = False
    points_hit = 0

    if transfer.use_wildcard:
        is_wildcard = True
        # Determine which wildcard phase
        if current_gw:
            gw_num = current_gw.number
        else:
            gw_num = 1

        if season:
            if gw_num <= season.first_half_cutoff:
                if ft.wildcard_first_half:
                    raise HTTPException(
                        status_code=400,
                        detail="First half wildcard already used. Save your second wildcard for GW 20+.",
                    )
                ft.wildcard_first_half = True
            else:
                if ft.wildcard_second_half:
                    raise HTTPException(
                        status_code=400,
                        detail="Second half wildcard already used. No more wildcards this season.",
                    )
                ft.wildcard_second_half = True
        else:
            # Fallback: no season config, use standard split
            if gw_num <= 19:
                if ft.wildcard_first_half:
                    raise HTTPException(
                        status_code=400,
                        detail="First half wildcard already used.",
                    )
                ft.wildcard_first_half = True
            else:
                if ft.wildcard_second_half:
                    raise HTTPException(
                        status_code=400,
                        detail="Second half wildcard already used.",
                    )
                ft.wildcard_second_half = True

        # Wildcard: reset transfers, no point hit
        ft.free_transfers = 1
        ft.current_gw_transfers = 0

    elif ft.free_transfers > 0:
        ft.free_transfers -= 1
        ft.current_gw_transfers += 1
    else:
        # Extra transfer - point hit
        points_hit = TRANSFER_HIT
        ft.current_gw_transfers += 1
        ft.total_points -= points_hit

    # Update budget
    if not is_wildcard:
        ft.budget_remaining -= price_diff
        ft.budget_remaining = round(max(0, ft.budget_remaining), 1)

    # Remove outgoing player
    db.delete(squad_out)

    # Add incoming player in the same slot
    squad_in = SquadPlayer(
        fantasy_team_id=ft.id,
        player_id=player_in.id,
        position_slot=squad_out.position_slot,
        is_starting=squad_out.is_starting,
        is_captain=squad_out.is_captain,
        is_vice_captain=squad_out.is_vice_captain,
    )
    db.add(squad_in)

    # Record transfer
    transfer_record = Transfer(
        user_id=user_id,
        gameweek_id=current_gw.id if current_gw else None,
        player_in_id=player_in.id,
        player_out_id=player_out.id,
        points_scored_by_outgoing=squad_out.total_points,
        is_wildcard=is_wildcard,
    )
    db.add(transfer_record)

    db.commit()

    return {
        "status": "transfer_complete",
        "player_in": {
            "id": player_in.id,
            "name": player_in.name,
            "price": player_in.price,
            "team": player_in.team.name if player_in.team else "",
        },
        "player_out": {
            "id": player_out.id,
            "name": player_out.name,
            "price": player_out.price,
            "team": player_out.team.name if player_out.team else "",
        },
        "points_hit": points_hit,
        "budget_remaining": round(ft.budget_remaining, 1),
        "free_transfers": ft.free_transfers,
        "is_wildcard": is_wildcard,
    }


@router.get("/history/{user_id}")
def get_transfer_history(user_id: int, db: Session = Depends(get_db)):
    """Get transfer history for a user."""
    transfers = db.query(Transfer).filter(
        Transfer.user_id == user_id,
    ).order_by(Transfer.created_at.desc()).all()

    return [
        {
            "id": t.id,
            "gameweek": t.gameweek_id,
            "player_in": {
                "id": t.player_in.id,
                "name": t.player_in.name,
                "team": t.player_in.team.name if t.player_in and t.player_in.team else "",
            } if t.player_in else None,
            "player_out": {
                "id": t.player_out.id,
                "name": t.player_out.name,
                "team": t.player_out.team.name if t.player_out and t.player_out.team else "",
            } if t.player_out else None,
            "points_scored_by_outgoing": t.points_scored_by_outgoing,
            "is_wildcard": t.is_wildcard,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in transfers
    ]


@router.get("/status/{user_id}")
def get_transfer_status(user_id: int, db: Session = Depends(get_db)):
    """Get transfer status for a user (current GW transfers, free transfers, etc.)."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    return {
        "free_transfers": ft.free_transfers,
        "free_transfers_next_gw": ft.free_transfers_next_gw,
        "current_gw_transfers": ft.current_gw_transfers,
        "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
        "budget_remaining": round(ft.budget_remaining, 1),
        "wildcard_first_half_available": not ft.wildcard_first_half,
        "wildcard_second_half_available": not ft.wildcard_second_half,
        "current_gameweek": current_gw.number if current_gw else None,
        "deadline": current_gw.deadline.isoformat() if current_gw and current_gw.deadline else None,
        "deadline_passed": datetime.utcnow() > current_gw.deadline if current_gw else False,
    }


@router.post("/process_gw_transfers")
def process_gameweek_transfers(db: Session = Depends(get_db)):
    """Process transfer rollovers when a new gameweek starts.

    Called when gameweek changes:
    - Carry over unused free transfers (max 5 rollover)
    - Reset current_gw_transfers to 1
    """
    teams = db.query(FantasyTeam).all()
    processed = 0

    for ft in teams:
        # Calculate rollover
        unused = max(0, ft.free_transfers)
        rollover = min(unused + ft.rollover_transfers, MAX_ROLLOVER_TRANSFERS)

        ft.rollover_transfers = rollover
        ft.free_transfers = min(1 + rollover, 1 + MAX_ROLLOVER_TRANSFERS)
        ft.free_transfers_next_gw = ft.free_transfers
        ft.current_gw_transfers = 0
        ft.transfer_deadline_exceeded = False
        processed += 1

    db.commit()
    return {"status": "processed", "teams_updated": processed}
