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
    VALID_FORMATIONS, auto_sub_squad, check_chip_availability,
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
        ft_dict = ft.__dict__.copy()
        ft_dict.pop('_sa_instance_state', None)
        team_data = ft_dict
    
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "team": team_data,
    }


@router.get("/{user_id}/squad")
def get_squad(user_id: int, db: Session = Depends(get_db)):
    """Get squad players for a user's fantasy team."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    
    return [
        {
            "id": sp.id,
            "player_id": sp.player_id,
            "player": {
                "id": sp.player.id,
                "name": sp.player.name,
                "position": sp.player.position,
                "team_id": sp.player.team_id,
                "price": sp.player.price,
                "team": {"name": sp.player.team.name} if sp.player.team else None,
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
    ]


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
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
    return new_user


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
        budget=100.0,
        budget_remaining=100.0,
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
    """Set team formation and update starting players.

    FPL valid formations:
    3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-3-2, 5-4-1
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    # Validate formation
    formation_config = None
    for f in VALID_FORMATIONS:
        if f["name"] == formation:
            formation_config = f
            break

    if not formation_config:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid formation. Valid: {[f['name'] for f in VALID_FORMATIONS]}",
        )

    # Validate squad has enough players of each position
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    positions = {}
    for sp in squad:
        pos = sp.player.position
        positions[pos] = positions.get(pos, 0) + 1

    required_def = formation_config["def"]
    required_mid = formation_config["mid"]
    required_fwd = formation_config["fwd"]

    if positions.get("DEF", 0) < required_def:
        raise HTTPException(status_code=400, detail=f"Need {required_def} defenders")
    if positions.get("MID", 0) < required_mid:
        raise HTTPException(status_code=400, detail=f"Need {required_mid} midfielders")
    if positions.get("FWD", 0) < required_fwd:
        raise HTTPException(status_code=400, detail=f"Need {required_fwd} forwards")

    # Set starting XI based on formation
    # Reset all starting flags
    for sp in squad:
        sp.is_starting = False

    # Select starting XI
    starting_count = 0
    # GK: 1
    gks = [sp for sp in squad if sp.player.position == "GK"]
    if gks:
        gks[0].is_starting = True
        starting_count += 1

    # DEF
    defs = [sp for sp in squad if sp.player.position == "DEF"]
    for sp in defs[:required_def]:
        sp.is_starting = True
        starting_count += 1

    # MID
    mids = [sp for sp in squad if sp.player.position == "MID"]
    for sp in mids[:required_mid]:
        sp.is_starting = True
        starting_count += 1

    # FWD
    fwds = [sp for sp in squad if sp.player.position == "FWD"]
    for sp in fwds[:required_fwd]:
        sp.is_starting = True
        starting_count += 1

    db.commit()

    return {
        "status": "updated",
        "formation": formation,
        "starting_count": starting_count,
        "message": f"Formation set to {formation}. {15 - starting_count} players on bench.",
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
