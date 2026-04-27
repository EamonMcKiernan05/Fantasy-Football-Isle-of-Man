"""Mini-leagues API routes - FPL-style private leagues."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import (
    MiniLeague, MiniLeagueMember, FantasyTeam, User, Gameweek,
    FantasyTeamHistory,
)
from app.schemas import (
    MiniLeagueCreate, MiniLeagueJoin, MiniLeagueResponse,
    MiniLeagueMemberResponse, LeaderboardEntry,
)

router = APIRouter(prefix="/api/leagues", tags=["mini-leagues"])


def generate_league_code(length: int = 8) -> str:
    """Generate a unique league invite code."""
    return secrets.token_hex(length // 2).upper()


@router.post("/", response_model=MiniLeagueResponse)
def create_mini_league(
    league: MiniLeagueCreate,
    user_id: int = Query(..., description="Admin user ID"),
    db: Session = Depends(get_db),
):
    """Create a new mini-league.

    The creator becomes the admin and is automatically added.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=400, detail="Create a fantasy team first")

    # Generate unique code
    code = generate_league_code()
    while db.query(MiniLeague).filter(MiniLeague.code == code).first():
        code = generate_league_code()

    ml = MiniLeague(
        name=league.name,
        code=code,
        season="2025-26",
        is_h2h=league.is_h2h,
        admin_user_id=user_id,
    )
    db.add(ml)
    db.flush()

    # Add admin as member
    member = MiniLeagueMember(
        mini_league_id=ml.id,
        fantasy_team_id=ft.id,
    )
    db.add(member)
    db.commit()

    return _build_ml_response(ml, db)


@router.post("/join")
def join_mini_league(
    code: str,
    user_id: int = Query(..., description="User joining the league"),
    db: Session = Depends(get_db),
):
    """Join a mini-league using an invite code."""
    ml = db.query(MiniLeague).filter(MiniLeague.code == code.upper()).first()
    if not ml:
        raise HTTPException(status_code=404, detail="League not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=400, detail="Create a fantasy team first")

    # Check not already a member
    existing = db.query(MiniLeagueMember).filter(
        MiniLeagueMember.mini_league_id == ml.id,
        MiniLeagueMember.fantasy_team_id == ft.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member of this league")

    member = MiniLeagueMember(
        mini_league_id=ml.id,
        fantasy_team_id=ft.id,
    )
    db.add(member)
    db.commit()

    return {
        "status": "joined",
        "league": {"id": ml.id, "name": ml.name, "code": ml.code},
    }


@router.get("/{ml_id}", response_model=MiniLeagueResponse)
def get_mini_league(ml_id: int, db: Session = Depends(get_db)):
    """Get mini-league details with leaderboard."""
    ml = db.query(MiniLeague).filter(MiniLeague.id == ml_id).first()
    if not ml:
        raise HTTPException(status_code=404, detail="League not found")

    return _build_ml_response(ml, db)


@router.get("/by-code/{code}")
def get_mini_league_by_code(code: str, db: Session = Depends(get_db)):
    """Get mini-league by invite code."""
    ml = db.query(MiniLeague).filter(MiniLeague.code == code.upper()).first()
    if not ml:
        raise HTTPException(status_code=404, detail="League not found")

    return _build_ml_response(ml, db)


@router.get("/my-leagues/{user_id}")
def get_user_leagues(user_id: int, db: Session = Depends(get_db)):
    """Get all mini-leagues a user is part of."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    memberships = db.query(MiniLeagueMember).filter(
        MiniLeagueMember.fantasy_team_id == ft.id
    ).all()

    leagues = []
    for m in memberships:
        ml = m.mini_league
        leagues.append({
            "id": ml.id,
            "name": ml.name,
            "code": ml.code,
            "is_admin": ml.admin_user_id == user_id,
            "is_h2h": ml.is_h2h,
            "member_count": len(ml.members),
            "your_rank": m.rank,
        })

    return {"leagues": leagues}


@router.post("/{ml_id}/calculate-ranks")
def calculate_league_ranks(ml_id: int, db: Session = Depends(get_db)):
    """Calculate and update ranks for a mini-league."""
    ml = db.query(MiniLeague).filter(MiniLeague.id == ml_id).first()
    if not ml:
        raise HTTPException(status_code=404, detail="League not found")

    members = db.query(MiniLeagueMember).filter(
        MiniLeagueMember.mini_league_id == ml_id
    ).all()

    # Sort by fantasy team total points
    sorted_members = sorted(members, key=lambda m: m.fantasy_team.total_points, reverse=True)

    for rank, member in enumerate(sorted_members, 1):
        member.rank = rank

    db.commit()

    return _build_ml_response(ml, db)


@router.delete("/{ml_id}")
def delete_mini_league(ml_id: int, user_id: int, db: Session = Depends(get_db)):
    """Delete a mini-league (admin only)."""
    ml = db.query(MiniLeague).filter(MiniLeague.id == ml_id).first()
    if not ml:
        raise HTTPException(status_code=404, detail="League not found")

    if ml.admin_user_id != user_id:
        raise HTTPException(status_code=403, detail="Only the admin can delete this league")

    # Remove members
    for member in ml.members:
        db.delete(member)

    db.delete(ml)
    db.commit()

    return {"status": "deleted", "league_id": ml_id}


def _build_ml_response(ml: "MiniLeague", db: Session) -> dict:
    """Build a full mini-league response with leaderboard."""
    members = db.query(MiniLeagueMember).filter(
        MiniLeagueMember.mini_league_id == ml.id
    ).all()

    # Sort by rank or total points
    sorted_members = sorted(
        members,
        key=lambda m: (m.rank or 999999, m.fantasy_team.total_points),
        reverse=False,
    )
    # Fix: sort by rank asc, then by points desc for ties
    sorted_members = sorted(
        members,
        key=lambda m: (m.rank if m.rank else 999999, -m.fantasy_team.total_points),
    )

    entries = []
    for rank, member in enumerate(sorted_members, 1):
        ft = member.fantasy_team
        user = ft.user

        # Get current GW points
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        gw_points = None
        if current_gw:
            history = db.query(FantasyTeamHistory).filter(
                FantasyTeamHistory.fantasy_team_id == ft.id,
                FantasyTeamHistory.gameweek_id == current_gw.id,
            ).first()
            gw_points = history.points if history else None

        entries.append({
            "rank": rank,
            "user_id": user.id,
            "username": user.username,
            "team_name": ft.name,
            "total_points": ft.total_points,
            "gameweek_points": gw_points,
        })

    return {
        "id": ml.id,
        "name": ml.name,
        "code": ml.code,
        "season": ml.season,
        "is_h2h": ml.is_h2h,
        "admin_user_id": ml.admin_user_id,
        "members": entries,
        "total_members": len(entries),
        "created_at": ml.created_at.isoformat() if ml.created_at else None,
    }
