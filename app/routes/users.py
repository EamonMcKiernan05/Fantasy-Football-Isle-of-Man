"""User management and squad API routes - FPL rules compliant."""
import hashlib
import json
import random
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.database import get_db
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Team, Gameweek,
    Division, MiniLeague, MiniLeagueMember, Season,
)
from app.schemas import (
    UserCreate, UserResponse, FantasyTeamResponse, SquadPlayerResponse,
    PlayerResponse, CaptainRequest, ChipRequest, ChipStatus,
)
from app import scoring

router = APIRouter(prefix="/api/users", tags=["users"])

# FPL Squad composition
SQUAD_COMP = {
    "GK": {"start": 2, "bench": 1},
    "DEF": {"start": 5, "bench": 2},
    "MID": {"start": 5, "bench": 2},
    "FWD": {"start": 3, "bench": 1},
}

# Position slots: 1=GK, 2-6=DEF, 7-11=MID, 12-14=FWD, 15=GK(b), 16-17=DEF(b), 18-19=MID(b), 20=FWD(b)
POSITION_SLOT_MAP = {
    "GK": [1, 15],
    "DEF": [2, 3, 4, 5, 16, 17],
    "MID": [6, 7, 8, 9, 10, 18, 19],
    "FWD": [11, 12, 13, 14, 20],
}


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new fantasy manager."""
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    db_user = User(
        username=user.username,
        email=user.email,
        password_hash=hashlib.sha256(user.password.encode()).hexdigest(),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login")
def login(username: str, password: str, db: Session = Depends(get_db)):
    """Login with username and password."""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    user = db.query(User).filter(
        User.username == username,
        User.password_hash == password_hash,
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"id": user.id, "username": user.username, "email": user.email}


@router.get("/{user_id}/team", response_model=FantasyTeamResponse)
def get_fantasy_team(user_id: int, db: Session = Depends(get_db)):
    """Get a user's fantasy team with full squad details."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).order_by(SquadPlayer.position_slot).all()

    # Get current gameweek
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    chip_status = ChipStatus(
        wildcard_first_half_used=ft.wildcard_first_half,
        wildcard_second_half_used=ft.wildcard_second_half,
        free_hit_used=ft.free_hit_used,
        bench_boost_used=ft.bench_boost_used,
        triple_captain_used=ft.triple_captain_used,
        active_chip=ft.active_chip,
    )

    return FantasyTeamResponse(
        id=ft.id,
        name=ft.name,
        total_points=ft.total_points,
        overall_rank=ft.overall_rank,
        free_transfers=ft.free_transfers,
        free_transfers_next_gw=ft.free_transfers_next_gw,
        budget_remaining=ft.budget_remaining,
        chip_status=chip_status,
        current_gw_transfers=ft.current_gw_transfers,
        transfer_deadline_exceeded=ft.transfer_deadline_exceeded,
        squad=[
            SquadPlayerResponse(
                id=sp.id,
                player_id=sp.player_id,
                player=PlayerResponse(
                    id=sp.player.id,
                    name=sp.player.name,
                    team_id=sp.player.team_id,
                    position=sp.player.position,
                    price=sp.player.price,
                    apps=sp.player.apps,
                    goals=sp.player.goals,
                    assists=sp.player.assists,
                    clean_sheets=sp.player.clean_sheets,
                    total_points=sp.player.total_points_season,
                    selected_by_percent=sp.player.selected_by_percent,
                    form=sp.player.form,
                    is_injured=sp.player.is_injured,
                ),
                position_slot=sp.position_slot,
                is_captain=sp.is_captain,
                is_vice_captain=sp.is_vice_captain,
                is_starting=sp.is_starting,
                total_points=sp.total_points,
                gw_points=sp.gw_points,
                was_autosub=sp.was_autosub,
            )
            for sp in squad
            if sp.player  # Skip deleted players
        ],
    )


@router.post("/{user_id}/team/create")
def create_fantasy_team(
    user_id: int,
    team_name: str = "My Team",
    db: Session = Depends(get_db),
):
    """Create a fantasy team with individual players.

    FPL Squad Rules:
    - 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD (starting) + 1 GK, 2 DEF, 2 MID, 1 FWD (bench)
    - Budget: 100.0m
    - Max 3 players per club
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first():
        raise HTTPException(status_code=400, detail="Fantasy team already exists")

    # Get active players by position, sorted by goals (quality proxy)
    gk = db.query(Player).filter(
        Player.position == "GK", Player.is_active == True, Player.is_injured == False
    ).order_by(Player.goals.desc(), Player.assists.desc()).limit(20).all()

    defs = db.query(Player).filter(
        Player.position == "DEF", Player.is_active == True, Player.is_injured == False
    ).order_by(Player.goals.desc(), Player.assists.desc()).limit(30).all()

    mids = db.query(Player).filter(
        Player.position == "MID", Player.is_active == True, Player.is_injured == False
    ).order_by(Player.goals.desc(), Player.assists.desc()).limit(30).all()

    fwds = db.query(Player).filter(
        Player.position == "FWD", Player.is_active == True, Player.is_injured == False
    ).order_by(Player.goals.desc(), Player.assists.desc()).limit(20).all()

    if len(gk) < 3 or len(defs) < 7 or len(mids) < 7 or len(fwds) < 4:
        raise HTTPException(
            status_code=400,
            detail="Not enough active players available. Sync players first.",
        )

    # Build squad with budget constraint and max 3 per club
    budget = 100.0
    selected = []
    team_counts = {}  # team_id -> count

    def can_add(player: Player) -> bool:
        """Check if player can be added (budget + max 3 per club)."""
        if player.price > budget + 2:  # Allow some flexibility
            return False
        team_count = team_counts.get(player.team_id, 0)
        return team_count < 3

    def add_player(player: Player):
        nonlocal budget
        selected.append(player)
        budget -= player.price
        team_counts[player.team_id] = team_counts.get(player.team_id, 0) + 1

    # Select GK (2 start + 1 bench = 3)
    for p in gk[:3]:
        if can_add(p):
            add_player(p)
    # Fill remaining GK if needed
    while len([p for p in selected if p.position == "GK"]) < 3 and len(gk) > len(selected):
        for p in gk:
            if p not in selected and can_add(p):
                add_player(p)
                break

    # Select DEF (5 start + 2 bench = 7)
    def_count = len([p for p in selected if p.position == "DEF"])
    for p in defs:
        if def_count >= 7:
            break
        if can_add(p):
            add_player(p)
            def_count += 1

    # Select MID (5 start + 2 bench = 7)
    mid_count = len([p for p in selected if p.position == "MID"])
    for p in mids:
        if mid_count >= 7:
            break
        if can_add(p):
            add_player(p)
            mid_count += 1

    # Select FWD (3 start + 1 bench = 4)
    fwd_count = len([p for p in selected if p.position == "FWD"])
    for p in fwds:
        if fwd_count >= 4:
            break
        if can_add(p):
            add_player(p)
            fwd_count += 1

    if len(selected) < 15:
        raise HTTPException(
            status_code=400,
            detail=f"Could only select {len(selected)} players (need 15). Not enough eligible players.",
        )

    # Create fantasy team
    season_name = "2025-26"
    ft = FantasyTeam(
        user_id=user_id,
        name=team_name,
        season=season_name,
        budget_remaining=round(max(0, budget), 1),
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.flush()

    # Create squad entries with proper position slots
    # Sort by position to assign correct slots
    selected_gk = [p for p in selected if p.position == "GK"][:3]
    selected_def = [p for p in selected if p.position == "DEF"][:7]
    selected_mid = [p for p in selected if p.position == "MID"][:7]
    selected_fwd = [p for p in selected if p.position == "FWD"][:4]

    all_players = selected_gk + selected_def + selected_mid + selected_fwd
    slots = [
        1,  # GK start
        2, 3, 4, 5,  # DEF start
        6, 7, 8, 9, 10,  # MID start
        11, 12, 13,  # FWD start
        15,  # GK bench
        16, 17,  # DEF bench
        18, 19,  # MID bench
        20,  # FWD bench
    ]

    captain_set = False
    vice_set = False

    for i, player in enumerate(all_players[:15]):
        slot = slots[i] if i < len(slots) else i + 1
        is_starting = i < 11

        sp = SquadPlayer(
            fantasy_team_id=ft.id,
            player_id=player.id,
            position_slot=slot,
            is_starting=is_starting,
            is_captain=(not captain_set),
            is_vice_captain=(not vice_set and captain_set),
        )
        if sp.is_captain:
            captain_set = True
        elif sp.is_vice_captain:
            vice_set = True
        db.add(sp)

    db.commit()
    return {
        "status": "created",
        "team_id": ft.id,
        "team_name": ft.name,
        "players_selected": len(all_players[:15]),
        "budget_remaining": round(max(0, budget), 1),
    }


@router.put("/{user_id}/team/captain")
def set_captain(
    user_id: int,
    captain: CaptainRequest,
    db: Session = Depends(get_db),
):
    """Set captain and vice-captain (by SquadPlayer ID).

    FPL Rules:
    - Captain gets 2x points
    - Vice-captain takes over if captain doesn't play
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    # Reset all captain/vice-captain
    for sp in squad:
        sp.is_captain = False
        sp.is_vice_captain = False

    # Set captain
    captain_sp = next((sp for sp in squad if sp.id == captain.captain_id), None)
    if not captain_sp:
        raise HTTPException(status_code=400, detail="Captain not in squad")
    captain_sp.is_captain = True

    # Set vice-captain
    if captain.vice_captain_id:
        if captain.vice_captain_id == captain.captain_id:
            raise HTTPException(status_code=400, detail="Captain and vice-captain must be different")
        vc_sp = next((sp for sp in squad if sp.id == captain.vice_captain_id), None)
        if not vc_sp:
            raise HTTPException(status_code=400, detail="Vice-captain not in squad")
        vc_sp.is_vice_captain = True

    db.commit()
    return {
        "status": "captain_set",
        "captain_id": captain.captain_id,
        "vice_captain_id": captain.vice_captain_id,
    }


@router.post("/{user_id}/team/chip")
def activate_chip(
    user_id: int,
    chip_req: ChipRequest,
    db: Session = Depends(get_db),
):
    """Activate a chip.

    FPL Chips:
    - Wildcard: unlimited permanent transfers (2 per season: GW 1-19, GW 20-38)
    - Free Hit: temporary squad for 1 GW, reverts next GW
    - Bench Boost: all 15 players' points count for 1 GW
    - Triple Captain: captain gets 3x instead of 2x for 1 GW
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    chip = chip_req.chip.lower().replace(" ", "_")
    valid_chips = ["wildcard", "free_hit", "bench_boost", "triple_captain"]
    if chip not in valid_chips:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chip. Choose from: {', '.join(valid_chips)}",
        )

    # Check if already used
    if chip == "wildcard":
        # Wildcard is handled in transfers.py
        raise HTTPException(
            status_code=400,
            detail="Activate wildcard through the transfer endpoint (use_wildcard=true)",
        )
    elif chip == "free_hit":
        if ft.free_hit_used:
            raise HTTPException(status_code=400, detail="Free Hit already used this season")

        # Backup current squad for Free Hit reversion
        squad_backup = []
        squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).all()
        for sp in squad:
            squad_backup.append({
                "squad_id": sp.id,
                "player_id": sp.player_id,
                "position_slot": sp.position_slot,
                "is_captain": sp.is_captain,
                "is_vice_captain": sp.is_vice_captain,
                "is_starting": sp.is_starting,
            })
        ft.free_hit_backup = json.dumps(squad_backup)
        ft.free_hit_used = True
        ft.active_chip = chip

    elif chip == "bench_boost":
        if ft.bench_boost_used:
            raise HTTPException(status_code=400, detail="Bench Boost already used this season")
        ft.bench_boost_used = True
        ft.active_chip = chip

    elif chip == "triple_captain":
        if ft.triple_captain_used:
            raise HTTPException(status_code=400, detail="Triple Captain already used this season")
        ft.triple_captain_used = True
        ft.active_chip = chip

    db.commit()
    return {
        "status": "chip_activated",
        "chip": chip,
        "message": f"{chip.replace('_', ' ').title()} activated for this gameweek.",
    }


@router.post("/{user_id}/team/revert_free_hit")
def revert_free_hit(user_id: int, db: Session = Depends(get_db)):
    """Revert Free Hit squad back to original.

    Called automatically when Free Hit gameweek closes.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    if not ft.free_hit_backup:
        raise HTTPException(status_code=400, detail="No Free Hit backup to revert")

    backup = json.loads(ft.free_hit_backup)

    # Clear current squad
    current_squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()
    for sp in current_squad:
        db.delete(sp)

    # Restore from backup
    for entry in backup:
        sp = SquadPlayer(
            fantasy_team_id=ft.id,
            player_id=entry["player_id"],
            position_slot=entry["position_slot"],
            is_captain=entry["is_captain"],
            is_vice_captain=entry["is_vice_captain"],
            is_starting=entry["is_starting"],
        )
        db.add(sp)

    ft.active_chip = None
    ft.free_hit_backup = None

    db.commit()
    return {"status": "free_hit_reverted", "message": "Squad reverted to pre-Free Hit state."}


@router.get("/{user_id}/rank")
def get_user_rank(user_id: int, db: Session = Depends(get_db)):
    """Get a user's current rank on the overall leaderboard."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    rank = (
        db.query(FantasyTeam)
        .filter(FantasyTeam.total_points > ft.total_points)
        .count()
    ) + 1

    total = db.query(FantasyTeam).count()

    return {
        "user_id": user_id,
        "team_name": ft.name,
        "total_points": ft.total_points,
        "rank": rank,
        "total_teams": total,
        "percentile": round((1 - rank / max(total, 1)) * 100, 1),
    }
