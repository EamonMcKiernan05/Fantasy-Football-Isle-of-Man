"""User and Fantasy Team API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query, Form, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, Annotated

from app.database import get_db
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Gameweek,
    FantasyTeamHistory, Team,
)
from app.schemas import (
    UserCreate, UserResponse, FantasyTeamResponse, SquadPlayerResponse,
    ChipStatus, CaptainRequest, ChipRequest, PlayerHistoryEntry,
)
from app.scoring import (
    get_chip_status, activate_chip, cancel_chip, calculate_selling_price,
    auto_sub_squad, check_chip_availability,
)
from app.utils.passwords import hash_password, verify_password
from app.utils.squad import create_default_squad

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me")
def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Get current user and their fantasy team (used by frontend).
    
    The token format is: bearer-{user_id}-{username}
    """
    # Parse token from Authorization header
    token = authorization.replace("Bearer ", "") if authorization else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Token format: bearer-{user_id}-{username}
    parts = token.split("-", 2)
    if len(parts) < 3 or parts[0] != "bearer":
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user_id = int(parts[1])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()

    team_data = None
    if ft:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()
        team_data = {
            "id": ft.id,
            "user_id": ft.user_id,
            "name": ft.name,
            "season": ft.season,
            "budget": ft.budget,
            "budget_remaining": ft.budget_remaining,
            "total_points": ft.total_points,
            "overall_rank": ft.overall_rank,
            "league_rank": ft.league_rank,
            "free_transfers": ft.free_transfers,
            "free_transfers_next_gw": ft.free_transfers_next_gw,
            "current_gw_transfers": ft.current_gw_transfers,
            "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
            "active_chip": ft.active_chip,
            "supported_club_id": ft.supported_club_id,
            "supported_club_name": ft.supported_club.name if ft.supported_club else None,
            "chip_status": get_chip_status(ft, current_gw.number if current_gw else 1),
        }

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "team": team_data,
    }


def _serialize_squad_player(sp):
    return {
        "id": sp.id,
        "player_id": sp.player_id,
        "player": {
            "id": sp.player.id,
            "name": sp.player.name,
            "position": sp.player.position,
            "team_id": sp.player.team_id,
            "price": sp.player.price,
            "team": {"id": sp.player.team.id, "name": sp.player.team.name} if sp.player.team else None,
            "is_injured": sp.player.is_injured,
            "injury_status": sp.player.injury_status,
            "form": sp.player.form,
            "selected_by_percent": sp.player.selected_by_percent,
            "total_points_season": sp.player.total_points_season,
        },
        "position": sp.player.position,
        "position_slot": sp.position_slot,
        "is_captain": sp.is_captain,
        "is_vice_captain": sp.is_vice_captain,
        "is_starting": sp.is_starting,
        "total_points": sp.total_points,
        "gw_points": sp.gw_points,
        "was_autosub": sp.was_autosub,
        "bench_priority": sp.bench_priority,
        "purchase_price": sp.purchase_price,
        "selling_price": sp.selling_price,
    }


def _resolve_team(db: Session, team_or_user_id: int) -> FantasyTeam:
    """Resolve a fantasy team by team id, falling back to user id.

    The frontend mixes these so we accept either.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_or_user_id).first()
    if ft:
        return ft
    return db.query(FantasyTeam).filter(FantasyTeam.user_id == team_or_user_id).first()


@router.get("/{user_id}/squad")
def get_squad(user_id: int, db: Session = Depends(get_db)):
    """Get squad players for a user's fantasy team.

    Accepts either user_id or fantasy_team_id (frontend mixes these).
    """
    ft = _resolve_team(db, user_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    return [_serialize_squad_player(sp) for sp in squad]


@router.get("/{team_id}/chips")
def get_team_chips(team_id: int, db: Session = Depends(get_db)):
    """Return chip status as a list (frontend renders chip cards)."""
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    types = ["wildcard", "free_hit", "bench_boost", "triple_captain"]
    out = []
    for t in types:
        used = getattr(ft, f"{t}_used", False)
        out.append({
            "type": t,
            "used": used,
            "active": ft.active_chip == t,
            "available": not used,
        })
    return out


@router.post("/{team_id}/chips/activate/{chip_type}")
def activate_chip_route(team_id: int, chip_type: str, db: Session = Depends(get_db)):
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()
    gw_num = current_gw.number if current_gw else 1

    available, message = check_chip_availability(ft, chip_type, gw_num)
    if not available:
        raise HTTPException(status_code=400, detail=message)

    success, message = activate_chip(ft, chip_type, gw_num)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    db.commit()
    return {"status": "activated", "message": message, "chip": chip_type}


@router.post("/{team_id}/chips/cancel/{chip_type}")
def cancel_chip_route(team_id: int, chip_type: str, db: Session = Depends(get_db)):
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if chip_type == "free_hit":
        raise HTTPException(status_code=400, detail="Free Hit cannot be cancelled once confirmed")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()
    gw_num = current_gw.number if current_gw else 1

    success, message = cancel_chip(ft, chip_type, gw_num)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    db.commit()
    return {"status": "cancelled", "message": message, "chip": chip_type}


@router.post("/{team_id}/captain/{squad_id}")
def set_captain_by_squad(team_id: int, squad_id: int, db: Session = Depends(get_db)):
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    target = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not target:
        raise HTTPException(status_code=400, detail="Player not in your squad")
    if not target.is_starting:
        raise HTTPException(status_code=400, detail="Captain must be in starting XI")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        if sp.id != squad_id and sp.is_captain:
            sp.is_captain = False
        if sp.id == squad_id and sp.is_vice_captain:
            sp.is_vice_captain = False
    target.is_captain = True
    db.commit()
    return {"status": "ok", "captain_id": squad_id}


@router.post("/{team_id}/vice-captain/{squad_id}")
def set_vice_captain_by_squad(team_id: int, squad_id: int, db: Session = Depends(get_db)):
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    target = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not target:
        raise HTTPException(status_code=400, detail="Player not in your squad")
    if not target.is_starting:
        raise HTTPException(status_code=400, detail="Vice-captain must be in starting XI")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        if sp.id != squad_id and sp.is_vice_captain:
            sp.is_vice_captain = False
        if sp.id == squad_id and sp.is_captain:
            sp.is_captain = False
    target.is_vice_captain = True
    db.commit()
    return {"status": "ok", "vice_captain_id": squad_id}


@router.post("/{team_id}/squad/{squad_id}/bench")
def bench_squad_player(team_id: int, squad_id: int, db: Session = Depends(get_db)):
    """Move a player to the bench, swapping with the highest-priority bench player."""
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    sp = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not sp:
        raise HTTPException(status_code=400, detail="Player not in squad")
    if not sp.is_starting:
        return {"status": "noop", "message": "Already on bench"}

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()

    # Pick the highest-priority bench player (any position)
    bench = sorted(
        [b for b in squad if not b.is_starting],
        key=lambda b: b.bench_priority or 99,
    )

    if not bench:
        raise HTTPException(status_code=400, detail="No bench players available")

    candidate = bench[0]

    sp.is_starting = False
    candidate.is_starting = True
    if sp.is_captain:
        sp.is_captain = False
        candidate.is_captain = True
    if sp.is_vice_captain:
        sp.is_vice_captain = False
        candidate.is_vice_captain = True
    db.commit()
    return {"status": "ok", "benched": squad_id, "promoted": candidate.id}


@router.post("/{team_id}/squad/{squad_id}/start")
def start_squad_player(team_id: int, squad_id: int, db: Session = Depends(get_db)):
    """Promote a benched player to start, swapping with the lowest-scoring starter."""
    ft = _resolve_team(db, team_id)
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    sp = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not sp:
        raise HTTPException(status_code=400, detail="Player not in squad")
    if sp.is_starting:
        return {"status": "noop", "message": "Already starting"}

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    starters = [s for s in squad if s.is_starting]

    if not starters:
        raise HTTPException(status_code=400, detail="No starters to swap with")

    # Drop the lowest-scoring starter (any position)
    candidate = min(starters, key=lambda s: s.gw_points or 0)

    sp.is_starting = True
    candidate.is_starting = False
    if candidate.is_captain:
        candidate.is_captain = False
        sp.is_captain = True
    if candidate.is_vice_captain:
        candidate.is_vice_captain = False
        sp.is_vice_captain = True
    db.commit()
    return {"status": "ok", "promoted": squad_id, "benched": candidate.id}


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user, create their fantasy team, and return an auth token.

    Creates an empty fantasy team (no squad players) which the user populates
    via the Transfers page (or via auto-pick).
    """
    existing = db.query(User).filter(
        or_(User.username == user.username, User.email == user.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email taken")

    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    team_name = (user.team_name or f"{user.username}'s Team").strip()
    ft = FantasyTeam(
        user_id=new_user.id,
        name=team_name,
        season="2025-26",
        budget=60.0,
        budget_remaining=60.0,
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)

    return {
        "access_token": f"bearer-{new_user.id}-{new_user.username}",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
        },
        "team": {
            "id": ft.id,
            "user_id": ft.user_id,
            "name": ft.name,
            "budget_remaining": ft.budget_remaining,
            "season": ft.season,
        },
    }


@router.post("/login")
def login(username: Annotated[str, Form()], password: Annotated[str, Form()], db: Session = Depends(get_db)):
    """Login a user."""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "access_token": f"bearer-{user.id}-{user.username}",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
    }


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Get user details."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# --- Fantasy Team routes ---

@router.get("/{user_id}/team", response_model=dict)
def get_fantasy_team(user_id: int, db: Session = Depends(get_db)):
    """Get the user's fantasy team with full squad."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="No fantasy team found")

    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    # Get current gameweek number for chip status
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    return {
        "id": ft.id,
        "name": ft.name,
        "total_points": ft.total_points,
        "overall_rank": ft.overall_rank,
        "league_rank": ft.league_rank,
        "free_transfers": ft.free_transfers,
        "free_transfers_next_gw": ft.free_transfers_next_gw,
        "budget_remaining": ft.budget_remaining,
        "current_gw_transfers": ft.current_gw_transfers,
        "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
        "season": ft.season,
        "supported_club_id": ft.supported_club_id,
        "supported_club_name": ft.supported_club.name if ft.supported_club else None,
        "chip_status": get_chip_status(ft, current_gw.number if current_gw else 1),
        "squad": [
            {
                "id": sp.id,
                "player_id": sp.player_id,
                "player": {
                    "id": sp.player.id,
                    "name": sp.player.name,
                    "position": sp.player.position,
                    "team_id": sp.player.team_id,
                    "price": sp.player.price,
                },
                "position_slot": sp.position_slot,
                "is_captain": sp.is_captain,
                "is_vice_captain": sp.is_vice_captain,
                "is_starting": sp.is_starting,
                "total_points": sp.total_points,
                "gw_points": sp.gw_points,
                "was_autosub": sp.was_autosub,
                "bench_priority": sp.bench_priority,
                "purchase_price": sp.purchase_price,
            }
            for sp in squad
        ],
    }


@router.post("/{user_id}/team/create", response_model=dict)
def create_fantasy_team(
    user_id: int,
    team_name: str = "My Team",
    db: Session = Depends(get_db),
):
    """Create a new fantasy team for a user.

    Creates an empty squad that the user will populate.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if team already exists
    existing = db.query(FantasyTeam).filter(
        FantasyTeam.user_id == user_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Team already exists")

    ft = FantasyTeam(
        user_id=user_id,
        name=team_name,
        season="2025-26",
        budget=60.0,
        budget_remaining=60.0,
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)

    return {
        "id": ft.id,
        "name": ft.name,
        "budget_remaining": ft.budget_remaining,
        "message": f"Team '{ft.name}' created. Now select 15 players.",
    }


@router.get("/{user_id}/team/chip")
def get_chip_status_route(user_id: int, db: Session = Depends(get_db)):
    """Get detailed chip status for a user."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    return get_chip_status(ft, current_gw.number if current_gw else 1)


@router.post("/{user_id}/team/chip")
def set_chip(user_id: int, request: ChipRequest, db: Session = Depends(get_db)):
    """Activate or cancel a chip for the current gameweek.

    FPL 2025/26 rules:
    - All chips available 2x per season (1 per half: GW 1-19, GW 20-38)
    - Only one chip per gameweek
    - Free Hit cannot be cancelled once confirmed
    - Other chips can be cancelled before deadline
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if request.cancel:
        # Cancel the active chip
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        success, message = cancel_chip(
            ft, request.chip,
            current_gw.number if current_gw else 1,
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)

        db.commit()
        return {"status": "cancelled", "message": message}

    # Activate chip
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    # Check availability
    available, message = check_chip_availability(
        ft, request.chip,
        current_gw.number if current_gw else 1,
    )
    if not available:
        raise HTTPException(status_code=400, detail=message)

    # Activate
    success, message = activate_chip(
        ft, request.chip,
        current_gw.number if current_gw else 1,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)

    db.commit()
    return {"status": "activated", "message": message}


@router.put("/{user_id}/team/captain")
def set_captain(user_id: int, request: CaptainRequest, db: Session = Depends(get_db)):
    """Set captain and vice-captain.

    FPL rules:
    - Captain's points are doubled
    - If captain plays no minutes, vice-captain becomes captain
    - Both must be in the starting XI
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Validate captain is in squad
    captain_sp = db.query(SquadPlayer).filter(
        SquadPlayer.id == request.captain_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not captain_sp:
        raise HTTPException(status_code=400, detail="Captain not found in squad")

    # Validate vice-captain is in squad
    if request.vice_captain_id:
        vice_sp = db.query(SquadPlayer).filter(
            SquadPlayer.id == request.vice_captain_id,
            SquadPlayer.fantasy_team_id == ft.id,
        ).first()
        if not vice_sp:
            raise HTTPException(status_code=400, detail="Vice-captain not found in squad")

        if request.vice_captain_id == request.captain_id:
            raise HTTPException(status_code=400, detail="Captain and vice-captain cannot be the same player")

    # Clear all captain/vice-captain flags
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        sp.is_captain = False
        sp.is_vice_captain = False

    # Set captain
    captain_sp.is_captain = True

    # Set vice-captain
    if request.vice_captain_id:
        vice_sp = db.query(SquadPlayer).filter(SquadPlayer.id == request.vice_captain_id).first()
        if vice_sp:
            vice_sp.is_vice_captain = True

    # Auto-select vice-captain from starting XI if not set
    if not request.vice_captain_id:
        vice_candidate = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id,
            SquadPlayer.is_starting == True,
            SquadPlayer.id != request.captain_id,
        ).first()
        if vice_candidate:
            vice_candidate.is_vice_captain = True

    db.commit()

    return {
        "status": "updated",
        "captain_id": request.captain_id,
        "captain_name": captain_sp.player.name,
        "vice_captain_id": request.vice_captain_id,
    }


@router.put("/{user_id}/team/formation")
def set_formation(user_id: int, formation: str, db: Session = Depends(get_db)):
    """Set starting 10 (no formation validation - any player in any position).

    Accepts any formation string but just sets first 10 squad players as starters.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Reset all starting flags
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        sp.is_starting = False

    # Sort by bench_priority, set first 10 as starters
    sorted_squad = sorted(squad, key=lambda sp: sp.bench_priority or 99)
    for sp in sorted_squad[:10]:
        sp.is_starting = True

    db.commit()

    return {
        "status": "updated",
        "formation": formation,
        "starting_count": 10,
        "message": "Starting 10 set.",
    }


@router.put("/{user_id}/team/bench-priority")
def set_bench_priority(user_id: int, bench_order: list, db: Session = Depends(get_db)):
    """Set bench priority order for auto-substitutions.

    FPL rules:
    - Lower bench_priority = higher priority (1 is first sub)
    - GK subs only replace GK
    - DEF/MID flex can sub for each other
    - FWD subs only replace FWD
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    squad_map = {sp.id: sp for sp in squad}

    for priority, sp_id in enumerate(bench_order, 1):
        if sp_id in squad_map:
            squad_map[sp_id].bench_priority = priority

    db.commit()
    return {"status": "updated", "message": "Bench priority updated"}


@router.get("/{user_id}/team/history")
def get_team_history(user_id: int, db: Session = Depends(get_db)):
    """Get gameweek-by-gameweek history for a user's team."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    history = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.fantasy_team_id == ft.id
    ).order_by(FantasyTeamHistory.gameweek_id.asc()).all()

    entries = []
    for h in history:
        entries.append({
            "gameweek": h.gameweek.number if h.gameweek else 0,
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
        "total_gameweeks": len(entries),
    }


@router.put("/{user_id}/team/update")
def update_team_details(
    user_id: int,
    team_name: str = None,
    supported_club_id: int = None,
    db: Session = Depends(get_db),
):
    """Update fantasy team details.

    FPL-style entry-update: change team name and supported club.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if team_name:
        ft.name = team_name

    if supported_club_id is not None:
        club = db.query(Team).filter(Team.id == supported_club_id).first()
        if not club:
            raise HTTPException(status_code=404, detail="Club not found")
        ft.supported_club_id = supported_club_id

    db.commit()
    db.refresh(ft)

    return {
        "id": ft.id,
        "name": ft.name,
        "supported_club_id": ft.supported_club_id,
        "supported_club_name": ft.supported_club.name if ft.supported_club else None,
        "message": "Team details updated",
    }


@router.get("/{user_id}/team/supported-club-leaderboard")
def get_club_leaderboard(user_id: int, db: Session = Depends(get_db)):
    """Get leaderboard for managers who support the same club."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft or not ft.supported_club_id:
        raise HTTPException(status_code=400, detail="No supported club set")

    club_teams = (
        db.query(FantasyTeam)
        .filter(FantasyTeam.supported_club_id == ft.supported_club_id)
        .order_by(FantasyTeam.total_points.desc())
        .all()
    )

    leaderboard = []
    for rank, team in enumerate(club_teams, 1):
        leaderboard.append({
            "rank": rank,
            "team_id": team.id,
            "team_name": team.name,
            "username": team.user.username,
            "total_points": team.total_points,
        })

    my_entry = next((e for e in leaderboard if e["team_id"] == ft.id), None)

    return {
        "club_name": ft.supported_club.name if ft.supported_club else "Unknown",
        "my_rank": my_entry["rank"] if my_entry else None,
        "total_members": len(club_teams),
        "leaderboard": leaderboard[:20],
    }
