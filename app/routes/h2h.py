"""H2H league API endpoints (round-robin management)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List

from app.database import get_db
from app.models import (
    H2hLeague, H2hParticipant, H2hMatch, FantasyTeam, User, Gameweek,
)

router = APIRouter(prefix="/api/h2h", tags=["h2h"])


@router.get("/leagues")
def list_h2h_leagues(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List H2H leagues with pagination."""
    total = db.query(H2hLeague).count()
    leagues = (
        db.query(H2hLeague)
        .order_by(H2hLeague.name.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "leagues": [
            {
                "id": l.id,
                "name": l.name,
                "format_type": l.format_type,
                "participant_count": db.query(H2hParticipant).filter(
                    H2hParticipant.h2h_league_id == l.id
                ).count(),
                "is_public": True,
                "created_at": l.created_at,
            }
            for l in leagues
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/leagues/{league_id}")
def get_h2h_league(league_id: int, db: Session = Depends(get_db)):
    """Get H2H league details."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    participants = (
        db.query(H2hParticipant)
        .join(FantasyTeam)
        .join(User)
        .filter(H2hParticipant.h2h_league_id == league_id)
        .all()
    )

    participant_data = []
    for p in participants:
        participant_data.append({
            "participant_id": p.id,
            "user_id": p.fantasy_team.user_id,
            "username": p.fantasy_team.user.username,
            "team_name": p.fantasy_team.name,
            "h2h_points": p.h2h_points,
            "wins": p.wins,
            "draws": p.draws,
            "losses": p.losses,
            "byes": p.byes,
            "goal_difference": p.goal_difference,
        })

    # Sort by standings
    participant_data.sort(key=lambda x: (
        x["h2h_points"], x["wins"], x["goal_difference"]
    ), reverse=True)

    return {
        "league": {
            "id": league.id,
            "name": league.name,
            "format_type": league.format_type,
            "is_public": True,
            "code": league.invite_code,
            "created_at": league.created_at,
        },
        "participants": participant_data,
        "participant_count": len(participant_data),
    }


@router.post("/leagues")
def create_h2h_league(
    name: str,
    is_public: bool = True,
    format_type: str = "round_robin",
    user_id: int = None,
    db: Session = Depends(get_db),
):
    """Create a new H2H league."""
    import secrets
    code = secrets.token_hex(4).upper()

    league = H2hLeague(
        name=name,
        season="2025-26",
        format_type=format_type,
        admin_user_id=user_id or 1,
        invite_code=code,
        created_at=datetime.utcnow(),
    )
    db.add(league)
    db.commit()
    db.refresh(league)

    return {
        "league_id": league.id,
        "name": league.name,
        "code": league.invite_code,
        "format_type": league.format_type,
    }


@router.post("/leagues/{league_id}/join")
def join_h2h_league(
    league_id: int,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Join H2H league with code."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    return {
        "status": "joined",
        "league_id": league.id,
        "name": league.name,
    }


@router.get("/leagues/{league_id}/matches")
def get_h2h_matches(
    league_id: int,
    gameweek: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get H2H matches for a league."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    query = db.query(H2hMatch).filter(H2hMatch.h2h_league_id == league_id)
    if gameweek:
        query = query.filter(H2hMatch.gameweek_number == gameweek)

    matches = query.order_by(H2hMatch.gameweek_number.asc()).all()

    result = []
    for m in matches:
        pa = db.query(H2hParticipant).filter(H2hParticipant.id == m.participant_a_id).first()
        pb = db.query(H2hParticipant).filter(H2hParticipant.id == m.participant_b_id).first()

        fa = db.query(FantasyTeam).filter(FantasyTeam.id == pa.fantasy_team_id).first() if pa else None
        fb = db.query(FantasyTeam).filter(FantasyTeam.id == pb.fantasy_team_id).first() if pb else None

        result.append({
            "match_id": m.id,
            "gameweek": m.gameweek_number,
            "participant_a": {
                "name": fa.name if fa else "Unknown",
                "score": m.score_a,
            },
            "participant_b": {
                "name": fb.name if fb else "Unknown",
                "score": m.score_b,
            },
            "status": m.status,
            "result": m.result,
        })

    return {"matches": result}


@router.get("/leagues/{league_id}/fixtures")
def get_h2h_fixtures(
    league_id: int,
    db: Session = Depends(get_db),
):
    """Get all fixtures for H2H league."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    matches = (
        db.query(H2hMatch)
        .filter(H2hMatch.h2h_league_id == league_id)
        .order_by(H2hMatch.gameweek_number.asc(), H2hMatch.id.asc())
        .all()
    )

    # Group by gameweek
    by_gw = {}
    for m in matches:
        gw = m.gameweek_number
        if gw not in by_gw:
            by_gw[gw] = []
        by_gw[gw].append({
            "match_id": m.id,
            "participant_a_id": m.participant_a_id,
            "participant_b_id": m.participant_b_id,
            "score_a": m.score_a,
            "score_b": m.score_b,
            "status": m.status,
        })

    return {"fixtures_by_gameweek": by_gw}


@router.post("/leagues/{league_id}/generate-fixtures")
def generate_h2h_fixtures(
    league_id: int,
    db: Session = Depends(get_db),
):
    """Generate round-robin fixtures for H2H league."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    participants = (
        db.query(H2hParticipant)
        .filter(H2hParticipant.h2h_league_id == league_id)
        .all()
    )

    if len(participants) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 participants to generate fixtures"
        )

    # Round-robin algorithm
    n = len(participants)
    is_odd = n % 2 == 1
    if is_odd:
        participants.append(None)  # Bye placeholder
        n += 1

    rounds = []
    team_ids = [p.id for p in participants]
    if is_odd:
        team_ids[-1] = None

    fixed = team_ids[0]
    rotating = team_ids[1:]

    for r in range(n - 1):
        round_matches = []
        rotating = [rotating[-1]] + rotating[:-1]
        round_team_ids = [fixed] + rotating

        for i in range(0, n, 2):
            a = round_team_ids[i]
            b = round_team_ids[i + 1]
            if a and b:
                round_matches.append((a, b))

        rounds.append(round_matches)

    # Create matches
    created = 0
    for gw, round_matches in enumerate(rounds, 1):
        for pa_id, pb_id in round_matches:
            existing = (
                db.query(H2hMatch)
                .filter(
                    H2hMatch.h2h_league_id == league_id,
                    H2hMatch.gameweek_number == gw,
                    (
                        (H2hMatch.participant_a_id == pa_id) &
                        (H2hMatch.participant_b_id == pb_id)
                    ),
                )
                .first()
            )
            if not existing:
                match = H2hMatch(
                    h2h_league_id=league_id,
                    gameweek_number=gw,
                    participant_a_id=pa_id,
                    participant_b_id=pb_id,
                    status="pending",
                )
                db.add(match)
                created += 1

    db.commit()

    return {
        "status": "fixtures_generated",
        "matches_created": created,
        "total_rounds": len(rounds),
    }


@router.get("/leagues/{league_id}/my-matches")
def get_my_h2h_matches(
    league_id: int,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get current user's H2H matches."""
    league = db.query(H2hLeague).filter(H2hLeague.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    # Find user's participant
    ft = (
        db.query(FantasyTeam)
        .filter(FantasyTeam.user_id == user_id)
        .first()
    )
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    participant = (
        db.query(H2hParticipant)
        .filter(
            H2hParticipant.h2h_league_id == league_id,
            H2hParticipant.fantasy_team_id == ft.id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Not in this H2H league")

    matches = (
        db.query(H2hMatch)
        .filter(H2hMatch.h2h_league_id == league_id)
        .filter(
            (H2hMatch.participant_a_id == participant.id) |
            (H2hMatch.participant_b_id == participant.id)
        )
        .order_by(H2hMatch.gameweek_number.asc())
        .all()
    )

    result = []
    for m in matches:
        is_a = m.participant_a_id == participant.id
        opponent_id = m.participant_b_id if is_a else m.participant_a_id
        opponent = (
            db.query(H2hParticipant)
            .filter(H2hParticipant.id == opponent_id)
            .first()
        )
        opponent_team = None
        opponent_user = None
        if opponent:
            opponent_team = db.query(FantasyTeam).filter(
                FantasyTeam.id == opponent.fantasy_team_id
            ).first()
            if opponent_team:
                opponent_user = db.query(User).filter(
                    User.id == opponent_team.user_id
                ).first()

        result.append({
            "match_id": m.id,
            "gameweek": m.gameweek_number,
            "status": m.status,
            "opponent": {
                "username": opponent_user.username if opponent_user else "Unknown",
                "team_name": opponent_team.name if opponent_team else "Unknown",
            },
            "my_score": m.score_a if is_a else m.score_b,
            "opponent_score": m.score_b if is_a else m.score_a,
            "result": m.result,
        })

    return {"my_matches": result}
