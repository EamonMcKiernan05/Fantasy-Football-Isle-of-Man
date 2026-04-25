"""User management API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import User, FantasyTeam, SquadPlayer, Team
from app.schemas import (
    UserCreate, UserResponse, FantasyTeamResponse, SquadPlayerResponse,
    CaptainRequest,
)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new fantasy manager."""
    # Check if user exists
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user (simple hash for demo)
    import hashlib
    db_user = User(
        username=user.username,
        email=user.email,
        password_hash=hashlib.sha256(user.password.encode()).hexdigest(),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user


@router.get("/{user_id}/team", response_model=FantasyTeamResponse)
def get_fantasy_team(user_id: int, db: Session = Depends(get_db)):
    """Get a user's fantasy team."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()
    
    return {
        "id": ft.id,
        "name": ft.name,
        "total_points": ft.total_points,
        "rank": ft.rank,
        "squad": [
            {
                "id": sp.id,
                "team_id": sp.team_id,
                "team": {
                    "id": sp.team.id,
                    "name": sp.team.name,
                    "short_name": sp.team.short_name,
                },
                "position": sp.position,
                "is_captain": sp.is_captain,
                "is_vice_captain": sp.is_vice_captain,
                "is_active": sp.is_active,
                "total_points": sp.total_points,
            }
            for sp in squad
        ],
    }


@router.post("/{user_id}/team/create")
def create_fantasy_team(
    user_id: int,
    team_name: str = "My Team",
    db: Session = Depends(get_db),
):
    """Create a fantasy team with random teams from all divisions."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first():
        raise HTTPException(status_code=400, detail="Fantasy team already exists")
    
    # Get all teams
    all_teams = db.query(Team).order_by(Team.name).all()
    if len(all_teams) < 15:
        raise HTTPException(status_code=400, detail="Not enough teams available")
    
    import random
    selected = random.sample(all_teams, 15)
    
    # Create fantasy team
    ft = FantasyTeam(
        user_id=user_id,
        name=team_name,
        season="2025-26",
    )
    db.add(ft)
    db.flush()
    
    # Create squad (GK/DEF/MID/FWD distribution)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    for i, team in enumerate(selected):
        sp = SquadPlayer(
            fantasy_team_id=ft.id,
            team_id=team.id,
            position=positions[i],
            is_captain=(i == 0),  # First team is captain by default
            is_vice_captain=(i == 1),
        )
        db.add(sp)
    
    db.commit()
    
    return {"status": "created", "team_id": ft.id}


@router.put("/{user_id}/team/captain")
def set_captain(
    user_id: int,
    captain: CaptainRequest,
    db: Session = Depends(get_db),
):
    """Set captain and vice-captain for the fantasy team."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    
    # Reset all
    for sp in squad:
        sp.is_captain = False
        sp.is_vice_captain = False
    
    # Set captain
    captain_sp = next(
        (sp for sp in squad if sp.team_id == captain.captain_id),
        None
    )
    if not captain_sp:
        raise HTTPException(status_code=400, detail="Captain team not in squad")
    captain_sp.is_captain = True
    
    # Set vice-captain
    if captain.vice_captain_id:
        vc_sp = next(
            (sp for sp in squad if sp.team_id == captain.vice_captain_id),
            None
        )
        if not vc_sp:
            raise HTTPException(status_code=400, detail="Vice-captain team not in squad")
        vc_sp.is_vice_captain = True
    
    db.commit()
    return {"status": "updated"}


@router.put("/{user_id}/team/transfer")
def make_transfer(
    user_id: int,
    transfer: dict,
    db: Session = Depends(get_db),
):
    """Make a team transfer (in/out)."""
    team_in_id = transfer.get("team_in_id")
    team_out_id = transfer.get("team_out_id")
    
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    # Get current squad
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    
    # Remove team out
    if team_out_id:
        outgoing = next(
            (sp for sp in squad if sp.team_id == team_out_id),
            None
        )
        if not outgoing:
            raise HTTPException(status_code=400, detail="Team to remove not in squad")
        db.delete(outgoing)
    
    # Add team in
    if team_in_id:
        # Check not already in squad
        if any(sp.team_id == team_in_id for sp in squad):
            raise HTTPException(status_code=400, detail="Team already in squad")
        
        new_team = db.query(Team).filter(Team.id == team_in_id).first()
        if not new_team:
            raise HTTPException(status_code=404, detail="New team not found")
        
        # Determine position based on available slots
        positions = ["GK", "DEF", "MID", "FWD"]
        counts = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for sp in squad:
            counts[sp.position] += 1
        
        limits = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
        position = next(
            (p for p in positions if counts[p] < limits[p]),
            "MID"
        )
        
        new_sp = SquadPlayer(
            fantasy_team_id=ft.id,
            team_id=team_in_id,
            position=position,
        )
        db.add(new_sp)
    
    db.commit()
    return {"status": "transferred"}
