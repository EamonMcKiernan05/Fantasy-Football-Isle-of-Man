"""Transfer management API routes - FPL 2025/26 compliant."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional

from app.database import get_db
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Gameweek, Transfer,
    MiniLeague, MiniLeagueMember,
)
from app.schemas import TransferRequest, TransferResponse
from app.scoring import (
    calculate_transfer_hit,
    calculate_free_transfers,
    calculate_selling_price,
    MAX_TRANSFERS_PER_GW,
    MAX_ROLLOVER_TRANSFERS,
    FREE_TRANSFER_PER_GW,
    activate_chip,
    check_chip_availability,
    get_chip_status,
)

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


SQUAD_LIMIT = 15
POSITION_LIMITS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3


def _resolve_team(db: Session, fantasy_team_id=None, user_id=None):
    if fantasy_team_id:
        ft = db.query(FantasyTeam).filter(FantasyTeam.id == fantasy_team_id).first()
        if ft:
            return ft
    if user_id:
        return db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    return None


@router.post("/player")
def transfer_player(payload: dict, db: Session = Depends(get_db)):
    """Add a player, drop a player, or swap a player.

    Body fields (all optional except one of in/out):
        - fantasy_team_id or user_id
        - player_in_id (add to squad)
        - player_out_id (remove from squad)

    Behaviour:
        * If only player_in_id: pure add (must have an empty slot at that position)
        * If only player_out_id: pure drop
        * If both: paired swap (counts as one transfer for hit calc)

    This matches the FPL "build a squad / make a transfer" UX where you can
    drop a player and pick a replacement separately.
    """
    fantasy_team_id = payload.get("fantasy_team_id")
    user_id = payload.get("user_id")
    player_in_id = payload.get("player_in_id")
    player_out_id = payload.get("player_out_id")

    ft = _resolve_team(db, fantasy_team_id, user_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if not player_in_id and not player_out_id:
        raise HTTPException(status_code=400, detail="Must provide player_in_id or player_out_id")

    if ft.transfer_deadline_exceeded:
        raise HTTPException(status_code=400, detail="Transfer deadline exceeded for this gameweek")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    is_wildcard = ft.active_chip == "wildcard"
    is_free_hit = ft.active_chip == "free_hit"

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    squad_len = len(squad)

    # --- Drop only ---
    if player_out_id and not player_in_id:
        sp = next((s for s in squad if s.player_id == player_out_id), None)
        if not sp:
            raise HTTPException(status_code=404, detail="Player not in squad")
        sell_price = calculate_selling_price(sp.purchase_price, sp.player.price)
        ft.budget_remaining = round(ft.budget_remaining + sell_price, 1)
        db.delete(sp)
        db.commit()
        return {
            "status": "dropped",
            "player_out": {"id": sp.player_id, "name": sp.player.name, "sold_for": sell_price},
            "budget_remaining": round(ft.budget_remaining, 1),
        }

    # --- Add only (filling empty slot) ---
    if player_in_id and not player_out_id:
        if squad_len >= SQUAD_LIMIT:
            raise HTTPException(status_code=400, detail=f"Squad full ({SQUAD_LIMIT} players). Drop a player first.")
        player_in = db.query(Player).filter(Player.id == player_in_id).first()
        if not player_in:
            raise HTTPException(status_code=404, detail="Player not found")
        if any(s.player_id == player_in.id for s in squad):
            raise HTTPException(status_code=400, detail="Player already in squad")

        # Position limit check
        same_pos = sum(1 for s in squad if s.player.position == player_in.position)
        if same_pos >= POSITION_LIMITS[player_in.position]:
            raise HTTPException(status_code=400, detail=f"Already have {POSITION_LIMITS[player_in.position]} {player_in.position}")
        # Club limit
        same_team = sum(1 for s in squad if s.player.team_id == player_in.team_id)
        if same_team >= MAX_PER_CLUB:
            raise HTTPException(status_code=400, detail="Already have 3 players from this club")
        # Budget
        if ft.budget_remaining < player_in.price:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot afford. Need £{player_in.price:.1f}m, have £{ft.budget_remaining:.1f}m",
            )

        # Position slot - assign by current count
        slot_base = {"GK": 1, "DEF": 3, "MID": 8, "FWD": 13}
        position_slot = slot_base[player_in.position] + same_pos

        # Starting/bench: first 11 by squad order are starting (FPL default 4-4-2-ish);
        # for simplicity, mark as starting if there's room in a default 4-4-2.
        starting_caps = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
        starting_pos_count = sum(
            1 for s in squad if s.is_starting and s.player.position == player_in.position
        )
        is_starting = starting_pos_count < starting_caps[player_in.position]

        new_sp = SquadPlayer(
            fantasy_team_id=ft.id,
            player_id=player_in.id,
            position_slot=position_slot,
            is_starting=is_starting,
            purchase_price=player_in.price,
            selling_price=player_in.price,
            bench_priority=99 if is_starting else (squad_len - 10),
        )
        db.add(new_sp)
        ft.budget_remaining = round(ft.budget_remaining - player_in.price, 1)

        # If squad is now full, increment transfers (but not the first 15 picks)
        # First 15 picks are squad creation, no transfer hit.
        if squad_len + 1 == SQUAD_LIMIT:
            pass  # No transfer cost when filling initial squad

        db.commit()
        return {
            "status": "added",
            "player_in": {"id": player_in.id, "name": player_in.name, "price": player_in.price},
            "budget_remaining": round(ft.budget_remaining, 1),
            "squad_size": squad_len + 1,
        }

    # --- Swap (in + out) ---
    sp_out = next((s for s in squad if s.player_id == player_out_id), None)
    if not sp_out:
        raise HTTPException(status_code=404, detail="Player to drop not in squad")

    player_in = db.query(Player).filter(Player.id == player_in_id).first()
    if not player_in:
        raise HTTPException(status_code=404, detail="Player to add not found")
    if any(s.player_id == player_in.id for s in squad):
        raise HTTPException(status_code=400, detail="Player already in squad")
    if player_in.position != sp_out.player.position:
        raise HTTPException(
            status_code=400,
            detail=f"Position mismatch: must swap {sp_out.player.position} for {sp_out.player.position}",
        )

    # Club limit (excluding the outgoing player)
    same_team = sum(
        1 for s in squad
        if s.player.team_id == player_in.team_id and s.player_id != player_out_id
    )
    if same_team >= MAX_PER_CLUB:
        raise HTTPException(status_code=400, detail="Already have 3 players from this club")

    sell_price = calculate_selling_price(sp_out.purchase_price, sp_out.player.price)
    budget_after = round(ft.budget_remaining + sell_price - player_in.price, 1)
    if budget_after < 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot afford. Cost £{player_in.price:.1f}m, sell £{sell_price:.1f}m. "
                f"Budget would be £{budget_after:.1f}m"
            ),
        )

    # Transfer cost
    points_hit = 0
    if not is_wildcard and not is_free_hit:
        if ft.free_transfers > 0:
            ft.free_transfers -= 1
        else:
            points_hit = 4

    # Carry over slot/captaincy
    new_sp = SquadPlayer(
        fantasy_team_id=ft.id,
        player_id=player_in.id,
        position_slot=sp_out.position_slot,
        is_starting=sp_out.is_starting,
        is_captain=sp_out.is_captain,
        is_vice_captain=sp_out.is_vice_captain,
        bench_priority=sp_out.bench_priority,
        purchase_price=player_in.price,
        selling_price=player_in.price,
    )
    db.add(new_sp)
    db.delete(sp_out)

    ft.budget_remaining = budget_after
    ft.current_gw_transfers += 1

    transfer_record = Transfer(
        user_id=ft.user_id,
        player_in_id=player_in.id,
        player_out_id=player_out_id,
        points_scored_by_outgoing=sp_out.total_points,
        is_wildcard=is_wildcard,
        is_free_hit=is_free_hit,
        gameweek_id=current_gw.id if current_gw else None,
    )
    db.add(transfer_record)

    db.commit()
    return {
        "status": "swapped",
        "player_in": {"id": player_in.id, "name": player_in.name, "price": player_in.price},
        "player_out": {
            "id": sp_out.player_id,
            "name": sp_out.player.name,
            "sold_for": sell_price,
        },
        "points_hit": points_hit,
        "budget_remaining": round(ft.budget_remaining, 1),
        "free_transfers": ft.free_transfers,
        "is_wildcard": is_wildcard,
        "is_free_hit": is_free_hit,
    }


@router.post("/", response_model=dict)
def make_transfer(request: TransferRequest, db: Session = Depends(get_db)):
    """Make a transfer (player in + player out).

    FPL 2025/26 Rules:
    - 1 free transfer per gameweek, rollover max 4 (5 total)
    - Max 20 transfers per GW (excluding chips)
    - Extra transfers cost -4 points each
    - Wildcard: unlimited free transfers
    - Free Hit: temporary squad for 1 GW
    - Max 3 players from a single team
    - Half-increase selling price rule
    """
    # Get user and team
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == request.user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Check deadline
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    if ft.transfer_deadline_exceeded:
        raise HTTPException(status_code=400, detail="Transfer deadline exceeded for this gameweek")

    # Check max transfers per GW
    if ft.current_gw_transfers >= MAX_TRANSFERS_PER_GW and ft.active_chip != "wildcard" and ft.active_chip != "free_hit":
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_TRANSFERS_PER_GW} transfers per gameweek. Use Wildcard or Free Hit for unlimited."
        )

    # Get players
    player_in = db.query(Player).filter(Player.id == request.player_in_id).first()
    if not player_in:
        raise HTTPException(status_code=404, detail="Player to buy not found")

    player_out_sp = db.query(SquadPlayer).join(Player).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        Player.id == request.player_out_id,
    ).first()
    if not player_out_sp:
        raise HTTPException(status_code=404, detail="Player to sell not in your squad")

    player_out = player_out_sp.player

    # Validate squad composition
    # Check max 3 players per team
    team_players = db.query(SquadPlayer).join(Player).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        Player.team_id == player_in.team_id,
    ).count()
    if team_players >= 3 and player_out.team_id != player_in.team_id:
        raise HTTPException(
            status_code=400,
            detail="Already have 3 players from this team"
        )

    # Calculate budget impact with half-increase rule
    # Selling price for the player going out
    sell_price = calculate_selling_price(
        player_out_sp.purchase_price,
        player_out.price,
    )

    # Budget change: buy at new price, sell at half-increase price
    budget_change = sell_price - player_in.price

    if ft.budget_remaining + budget_change < 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot afford. Cost: £{player_in.price:.1f}m, "
                f"Sell: £{sell_price:.1f}m (bought for £{player_out_sp.purchase_price:.1f}m). "
                f"Net: -£{abs(budget_change):.1f}m, Budget: £{ft.budget_remaining:.1f}m"
            )
        )

    # Calculate transfer costs
    is_wildcard = ft.active_chip == "wildcard"
    is_free_hit = ft.active_chip == "free_hit"
    free_available = ft.free_transfers if is_wildcard or is_free_hit else ft.free_transfers

    # If wildcard or free hit, no transfer cost
    points_hit = 0
    if not is_wildcard and not is_free_hit:
        points_hit = calculate_transfer_hit(
            1,  # One transfer being made
            ft.free_transfers,
            is_wildcard=False,
        )

    # Update budget
    ft.budget_remaining += budget_change

    # Update transfer counts
    ft.current_gw_transfers += 1

    if not is_wildcard and not is_free_hit:
        ft.free_transfers -= 1
        if ft.free_transfers < 0:
            ft.free_transfers = 0

    # Update free transfers for next GW
    ft.free_transfers_next_gw = calculate_free_transfers(
        ft.free_transfers,
        ft.current_gw_transfers,
        is_wildcard=is_wildcard,
    )

    # Remove player out
    db.delete(player_out_sp)

    # Add player in
    new_sp = SquadPlayer(
        fantasy_team_id=ft.id,
        player_id=player_in.id,
        player=player_in,
        position_slot=0,
        is_starting=True,
        purchase_price=player_in.price,
        selling_price=player_in.price,
        is_captain=False,
        is_vice_captain=False,
    )
    db.add(new_sp)

    # Record transfer
    transfer_record = Transfer(
        user_id=request.user_id,
        player_in_id=player_in.id,
        player_out_id=player_out.id,
        points_scored_by_outgoing=player_out_sp.total_points,
        is_wildcard=is_wildcard,
        is_free_hit=is_free_hit,
        gameweek_id=current_gw.id if current_gw else None,
    )
    db.add(transfer_record)

    # Update player selection stats
    player_in.selected_by_percent = min(100, player_in.selected_by_percent + 0.1)
    player_in.transfers_in = (player_in.transfers_in or 0) + 1
    player_out.transfers_out = (player_out.transfers_out or 0) + 1

    # Reset captain/vice if captain was sold
    if player_out_sp.is_captain or player_out_sp.is_vice_captain:
        remaining = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).all()
        for sp in remaining:
            sp.is_captain = False
            sp.is_vice_captain = False
        if remaining:
            remaining[0].is_captain = True
        if len(remaining) > 1:
            remaining[1].is_vice_captain = True

    db.commit()

    return {
        "status": "success",
        "player_in": {
            "id": player_in.id,
            "name": player_in.name,
            "price": player_in.price,
        },
        "player_out": {
            "id": player_out.id,
            "name": player_out.name,
            "sold_for": sell_price,
        },
        "points_hit": points_hit,
        "budget_remaining": round(ft.budget_remaining, 1),
        "free_transfers": ft.free_transfers,
        "is_wildcard": is_wildcard,
        "is_free_hit": is_free_hit,
        "transfer_cost": f"{'Free (wildcard)' if is_wildcard else ('Free (free hit)' if is_free_hit else (f'Free ({ft.free_transfers+1} free available)' if points_hit == 0 else f'-{points_hit} pts'))}",
    }


@router.post("/wildcard", response_model=dict)
def play_wildcard(user_id: int, db: Session = Depends(get_db)):
    """Play wildcard chip - unlimited free transfers this gameweek.

    FPL 2025/26 rules:
    - 2 wildcards per season (GW 1-19, GW 20-38)
    - Can be cancelled before deadline
    - Resets transfer limit and point hits
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    if not current_gw:
        raise HTTPException(status_code=400, detail="No active gameweek")

    # Determine which wildcard half
    is_first_half = current_gw.number <= 19
    chip_name = "wildcard"

    available, message = check_chip_availability(ft, chip_name, current_gw.number)
    if not available:
        raise HTTPException(status_code=400, detail=message)

    success, message = activate_chip(ft, chip_name, current_gw.number)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Reset current GW transfers
    ft.current_gw_transfers = 0

    db.commit()
    return {
        "status": "activated",
        "message": message,
        "half": "first" if is_first_half else "second",
        "remaining_wildcards": (
            (0 if ft.wildcard_first_half else 1) +
            (0 if ft.wildcard_second_half else 1)
        ),
    }


@router.post("/free-hit", response_model=dict)
def play_free_hit(user_id: int, db: Session = Depends(get_db)):
    """Play Free Hit chip - temporary squad for 1 gameweek.

    FPL 2025/26 rules:
    - 2 per season (GW 1-19, GW 20-38)
    - Squad reverts to previous state next GW
    - Cannot be used in consecutive gameweeks
    - Cannot be cancelled once confirmed
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    if not current_gw:
        raise HTTPException(status_code=400, detail="No active gameweek")

    chip_name = "free_hit"
    available, message = check_chip_availability(ft, chip_name, current_gw.number)
    if not available:
        raise HTTPException(status_code=400, detail=message)

    success, message = activate_chip(ft, chip_name, current_gw.number)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Save current squad for revert
    import json
    squad_data = []
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        squad_data.append({
            "player_id": sp.player_id,
            "position_slot": sp.position_slot,
            "is_captain": sp.is_captain,
            "is_vice_captain": sp.is_vice_captain,
            "is_starting": sp.is_starting,
            "purchase_price": sp.purchase_price,
            "bench_priority": sp.bench_priority,
        })
    ft.free_hit_backup = json.dumps(squad_data)
    ft.free_hit_revert_gw = current_gw.number + 1

    db.commit()
    return {
        "status": "activated",
        "message": message,
        "revert_gw": ft.free_hit_revert_gw,
        "warning": "Free Hit cannot be cancelled. Squad reverts after GW.",
    }


@router.post("/cancel-chip", response_model=dict)
def cancel_chip_route(user_id: int, chip: str, db: Session = Depends(get_db)):
    """Cancel a chip before the deadline.

    Note: Free Hit cannot be cancelled once confirmed.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if chip == "free_hit":
        raise HTTPException(status_code=400, detail="Free Hit cannot be cancelled once confirmed")

    if ft.active_chip != chip:
        raise HTTPException(status_code=400, detail=f"No active {chip} chip to cancel")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    from app.scoring import cancel_chip as cancel_chip_fn
    success, message = cancel_chip_fn(ft, chip, current_gw.number if current_gw else 1)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    db.commit()
    return {"status": "cancelled", "message": message}


@router.get("/status/{user_id}")
def get_transfer_status(user_id: int, db: Session = Depends(get_db)):
    """Get transfer status including free transfers, budget, and chip availability."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    squad = db.query(SquadPlayer).join(Player).filter(
        SquadPlayer.fantasy_team_id == ft.id,
    ).all()

    # Team composition
    team_counts = {}
    for sp in squad:
        team_id = sp.player.team_id
        team_name = sp.player.team.name if sp.player.team else "Unknown"
        key = f"{team_id}_{team_name}"
        team_counts[key] = team_counts.get(key, 0) + 1

    chip_status = get_chip_status(ft, current_gw.number if current_gw else 1)

    return {
        "free_transfers": ft.free_transfers,
        "free_transfers_next_gw": ft.free_transfers_next_gw,
        "current_gw_transfers": ft.current_gw_transfers,
        "max_transfers_per_gw": MAX_TRANSFERS_PER_GW,
        "rollover_transfers": ft.rollover_transfers,
        "budget_remaining": ft.budget_remaining,
        "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
        "squad_size": len(squad),
        "team_composition": {
            "GK": sum(1 for sp in squad if sp.player.position == "GK"),
            "DEF": sum(1 for sp in squad if sp.player.position == "DEF"),
            "MID": sum(1 for sp in squad if sp.player.position == "MID"),
            "FWD": sum(1 for sp in squad if sp.player.position == "FWD"),
        },
        "active_chip": ft.active_chip,
        "chip_status": chip_status,
        "wildcard_first_half_available": not ft.wildcard_first_half,
        "wildcard_second_half_available": not ft.wildcard_second_half,
        "free_hit_first_half_available": not ft.free_hit_first_half,
        "free_hit_second_half_available": not ft.free_hit_second_half,
        "bench_boost_first_half_available": not ft.bench_boost_first_half,
        "bench_boost_second_half_available": not ft.bench_boost_second_half,
        "triple_captain_first_half_available": not ft.triple_captain_first_half,
        "triple_captain_second_half_available": not ft.triple_captain_second_half,
    }


@router.get("/history/{user_id}")
def get_transfer_history(user_id: int, db: Session = Depends(get_db)):
    """Get transfer history for a user."""
    transfers = db.query(Transfer).filter(
        Transfer.user_id == user_id
    ).order_by(Transfer.id.desc()).limit(50).all()

    history = []
    for t in transfers:
        history.append({
            "id": t.id,
            "gameweek_id": t.gameweek_id,
            "player_in": {"id": t.player_in.id, "name": t.player_in.name} if t.player_in else None,
            "player_out": {"id": t.player_out.id, "name": t.player_out.name} if t.player_out else None,
            "points_by_outgoing": t.points_scored_by_outgoing,
            "is_wildcard": t.is_wildcard,
            "is_free_hit": t.is_free_hit,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"transfers": history, "total": len(history)}
