"""H2H (Head-to-Head) league routes - FPL-style matchmaking.

FPL H2H Rules:
- Win: 2 points
- Draw: 1 point each
- Loss: 0 points
- Bye: 1 point
- Knockout: winner advances, loser eliminated
- Group stage: round-robin within groups
"""
import random
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from typing import Optional

from app.database import get_db
from app.models import (
    MiniLeague, MiniLeagueMember, FantasyTeam, User,
    Gameweek, H2hMatch, H2hLeague,
)
from app.schemas import H2hLeagueCreate, H2hMatchResponse

router = APIRouter(prefix="/api/h2h", tags=["h2h"])


@router.post("/leagues/", response_model=dict)
def create_h2h_league(
    league: H2hLeagueCreate,
    user_id: int = Query(..., description="Admin user ID"),
    db: Session = Depends(get_db),
):
    """Create a new H2H league.

    H2H Format:
    - Round-robin group stage
    - Knockout phase after group stage
    - Max 16 members for 8v8 knockout
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=400, detail="Create a fantasy team first")

    # Check not already in an H2H league this season
    existing = db.query(H2hLeague).filter(
        H2hLeague.season == "2025-26",
    ).join(H2hMatch).join(MiniLeagueMember).filter(
        MiniLeagueMember.fantasy_team_id == ft.id,
    ).first()

    # Create H2H league
    h2h_league = H2hLeague(
        name=league.name,
        season="2025-26",
        format_type=league.format_type,
        admin_user_id=user_id,
        started=False,
    )
    db.add(h2h_league)
    db.flush()

    # Add admin as participant
    from app.models import H2hParticipant
    participant = H2hParticipant(
        h2h_league_id=h2h_league.id,
        fantasy_team_id=ft.id,
        h2h_points=0,
        wins=0,
        draws=0,
        losses=0,
        byes=0,
        goal_difference=0,
    )
    db.add(participant)
    db.commit()
    db.refresh(h2h_league)

    return {
        "id": h2h_league.id,
        "name": h2h_league.name,
        "format": h2h_league.format_type,
        "participants": 1,
        "status": "registration",
        "message": f"H2H league '{h2h_league.name}' created. Invite others to join.",
    }


@router.post("/leagues/{h2h_id}/join")
def join_h2h_league(
    h2h_id: int,
    user_id: int = Query(..., description="User joining the H2H league"),
    db: Session = Depends(get_db),
):
    """Join an H2H league."""
    h2h_league = db.query(H2hLeague).filter(H2hLeague.id == h2h_id).first()
    if not h2h_league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    if h2h_league.started:
        raise HTTPException(status_code=400, detail="League already started")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=400, detail="Create a fantasy team first")

    # Check not already a participant
    existing = db.query(H2hParticipant).filter(
        H2hParticipant.h2h_league_id == h2h_id,
        H2hParticipant.fantasy_team_id == ft.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already in this H2H league")

    from app.models import H2hParticipant
    participant = H2hParticipant(
        h2h_league_id=h2h_id,
        fantasy_team_id=ft.id,
        h2h_points=0,
    )
    db.add(participant)
    db.commit()

    return {
        "status": "joined",
        "league_name": h2h_league.name,
        "participants": db.query(H2hParticipant).filter(
            H2hParticipant.h2h_league_id == h2h_id
        ).count(),
    }


@router.post("/leagues/{h2h_id}/start")
def start_h2h_league(h2h_id: int, db: Session = Depends(get_db)):
    """Start the H2H league and generate fixtures.

    Generates round-robin matchups for group stage.
    """
    h2h_league = db.query(H2hLeague).filter(H2hLeague.id == h2h_id).first()
    if not h2h_league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    from app.models import H2hParticipant

    participants = db.query(H2hParticipant).filter(
        H2hParticipant.h2h_league_id == h2h_id
    ).all()

    if len(participants) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 participants")

    # Generate round-robin schedule
    rounds = _generate_round_robin(participants)

    for gw_num, matchups in enumerate(rounds, 1):
        for (p1, p2) in matchups:
            match = H2hMatch(
                h2h_league_id=h2h_league.id,
                gameweek_number=gw_num,
                participant_a_id=p1.id,
                participant_b_id=p2.id,
                status="pending",
            )
            db.add(match)

    h2h_league.started = True
    h2h_league.group_stage_rounds = len(rounds)
    db.commit()

    return {
        "status": "started",
        "total_rounds": len(rounds),
        "matches_created": sum(len(m) for m in rounds),
    }


@router.get("/leagues/{h2h_id}")
def get_h2h_league(h2h_id: int, db: Session = Depends(get_db)):
    """Get H2H league details with standings and fixtures."""
    h2h_league = db.query(H2hLeague).filter(H2hLeague.id == h2h_id).first()
    if not h2h_league:
        raise HTTPException(status_code=404, detail="H2H league not found")

    from app.models import H2hParticipant

    # Standings
    participants = db.query(H2hParticipant).filter(
        H2hParticipant.h2h_league_id == h2h_id
    ).all()

    standings = []
    for p in participants:
        ft = p.fantasy_team
        standings.append({
            "rank": None,  # Calculated below
            "participant_id": p.id,
            "user_id": ft.user_id if ft else None,
            "username": ft.user.username if ft and ft.user else "Unknown",
            "team_name": ft.name if ft else "Unknown",
            "h2h_points": p.h2h_points,
            "wins": p.wins,
            "draws": p.draws,
            "losses": p.losses,
            "byes": p.byes,
            "goal_difference": p.goal_difference,
            "total_points": ft.total_points if ft else 0,
        })

    # Sort by H2H points, then GD, then total points
    standings.sort(
        key=lambda x: (x["h2h_points"], x["goal_difference"], x["total_points"]),
        reverse=True,
    )
    for i, entry in enumerate(standings, 1):
        entry["rank"] = i

    # Fixtures
    matches = db.query(H2hMatch).filter(
        H2hMatch.h2h_league_id == h2h_id
    ).order_by(H2hMatch.gameweek_number).all()

    fixtures = []
    for m in matches:
        pa = m.participant_a
        pb = m.participant_b
        fixtures.append({
            "id": m.id,
            "gameweek": m.gameweek_number,
            "participant_a": {
                "id": pa.id if pa else None,
                "team": pa.fantasy_team.name if pa and pa.fantasy_team else "Unknown",
                "points": m.score_a,
            },
            "participant_b": {
                "id": pb.id if pb else None,
                "team": pb.fantasy_team.name if pb and pb.fantasy_team else "Unknown",
                "points": m.score_b,
            },
            "status": m.status,
            "result": m.result,
        })

    return {
        "id": h2h_league.id,
        "name": h2h_league.name,
        "season": h2h_league.season,
        "format": h2h_league.format_type,
        "started": h2h_league.started,
        "standings": standings,
        "fixtures": fixtures,
        "participant_count": len(participants),
    }


@router.post("/matches/{match_id}/score")
def score_h2h_match(match_id: int, db: Session = Depends(get_db)):
    """Score an H2H match based on gameweek points.

    FPL H2H scoring:
    - Win: 2 points
    - Draw: 1 point each
    - Loss: 0 points
    - Bye: 1 point
    """
    match = db.query(H2hMatch).filter(H2hMatch.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="H2H match not found")

    if match.status in ("finished", "bye"):
        raise HTTPException(status_code=400, detail="Match already scored")

    pa = match.participant_a
    pb = match.participant_b

    if not pa or not pb:
        raise HTTPException(status_code=400, detail="Participant not found")

    ft_a = pa.fantasy_team
    ft_b = pb.fantasy_team

    if not ft_a or not ft_b:
        raise HTTPException(status_code=400, detail="Fantasy team not found")

    # Get gameweek points
    gw = db.query(Gameweek).filter(
        Gameweek.number == match.gameweek_number,
        Gameweek.season == match.h2h_league.season,
    ).first()

    if not gw or not gw.scored:
        raise HTTPException(status_code=400, detail="Gameweek not yet scored")

    # Get each team's GW points from history
    from app.models import FantasyTeamHistory
    hist_a = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.fantasy_team_id == ft_a.id,
        FantasyTeamHistory.gameweek_id == gw.id,
    ).first()
    hist_b = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.fantasy_team_id == ft_b.id,
        FantasyTeamHistory.gameweek_id == gw.id,
    ).first()

    points_a = hist_a.points if hist_a else 0
    points_b = hist_b.points if hist_b else 0

    match.score_a = points_a
    match.score_b = points_b

    # Determine result
    if points_a > points_b:
        match.result = "win_a"
        match.status = "finished"
        pa.h2h_points += 2
        pa.wins += 1
        pb.losses += 1
    elif points_b > points_a:
        match.result = "win_b"
        match.status = "finished"
        pb.h2h_points += 2
        pb.wins += 1
        pa.losses += 1
    else:
        match.result = "draw"
        match.status = "finished"
        pa.h2h_points += 1
        pb.h2h_points += 1
        pa.draws += 1
        pb.draws += 1

    # Update goal difference
    if pa.h2h_points > 0 or pb.h2h_points > 0:
        pa.goal_difference += (points_a - points_b)
        pb.goal_difference += (points_b - points_a)

    db.commit()

    return {
        "status": "scored",
        "match_id": match.id,
        "gameweek": match.gameweek_number,
        "score_a": points_a,
        "score_b": points_b,
        "result": match.result,
    }


@router.post("/matches/bye/{match_id}")
def process_h2h_bye(match_id: int, db: Session = Depends(get_db)):
    """Process a bye (opponent dropped out).

    FPL H2H: bye = 1 point for the remaining player.
    """
    match = db.query(H2hMatch).filter(H2hMatch.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="H2H match not found")

    # Determine who gets the bye
    pa = match.participant_a
    pb = match.participant_b

    if pa and not pb:
        match.result = "bye_a"
        match.status = "bye"
        pa.h2h_points += 1
        pa.byes += 1
    elif pb and not pa:
        match.result = "bye_b"
        match.status = "bye"
        pb.h2h_points += 1
        pb.byes += 1
    else:
        raise HTTPException(status_code=400, detail="Both participants present")

    db.commit()

    return {"status": "bye_processed", "match_id": match.id}


@router.get("/my-h2h/{user_id}")
def get_user_h2h(user_id: int, db: Session = Depends(get_db)):
    """Get H2H leagues for a specific user."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        return {"leagues": []}

    from app.models import H2hParticipant, H2hLeague

    participations = db.query(H2hParticipant).filter(
        H2hParticipant.fantasy_team_id == ft.id
    ).all()

    leagues = []
    for p in participations:
        h2h = p.h2h_league
        leagues.append({
            "id": h2h.id,
            "name": h2h.name,
            "format": h2h.format_type,
            "started": h2h.started,
            "your_h2h_points": p.h2h_points,
            "your_wins": p.wins,
            "your_draws": p.draws,
            "your_losses": p.losses,
        })

    return {"leagues": leagues}


# --- Helpers ---

def _generate_round_robin(participants: list) -> list:
    """Generate round-robin matchups.

    Returns list of rounds, each round is list of (p1, p2) tuples.
    Uses the circle method for round-robin scheduling.
    """
    n = len(participants)
    # If odd number, add a phantom participant for byes
    if n % 2 == 1:
        participants = participants + [None]
        n += 1

    rounds = []
    participants_list = list(participants)

    for round_num in range(n - 1):
        round_matches = []
        # First and last stay fixed, rotate the rest
        first = participants_list[0]
        last = participants_list[-1]
        middle = participants_list[1:-1]

        # Rotate middle
        middle = middle[-1:] + middle[:-1]
        participants_list = [first] + middle + [last]

        for i in range(n // 2):
            p1 = participants_list[i]
            p2 = participants_list[n - 1 - i]
            if p1 is not None and p2 is not None:
                round_matches.append((p1, p2))
            elif p1 is None:
                # p2 gets a bye
                pass
            elif p2 is None:
                # p1 gets a bye
                pass

        rounds.append(round_matches)

    return rounds
