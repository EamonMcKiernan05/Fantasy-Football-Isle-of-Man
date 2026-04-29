"""H2H bracket visualization API.

Generates bracket data for knockout stages, showing matchups,
results, and advancement paths.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import (
    H2hLeague, H2hParticipant, H2hMatch, FantasyTeam, User, Gameweek,
)

router = APIRouter(prefix="/api/h2h-bracket", tags=["h2h-bracket"])


@router.get("/{league_id}")
def get_h2h_bracket(
    league_id: int,
    db: Session = Depends(get_db),
):
    """Get H2H bracket data for visualization.

    Returns bracket structure with:
    - Participants and their standings
    - Match history and results
    - Knockout progression
    """
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

    # Standings
    standings = []
    for rank, p in enumerate(
        sorted(participants, key=lambda x: (
            x.h2h_points, x.wins, x.goal_difference
        ), reverse=True),
        start=1
    ):
        standings.append({
            "rank": rank,
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

    # Matches
    matches = (
        db.query(H2hMatch)
        .filter(H2hMatch.h2h_league_id == league_id)
        .order_by(H2hMatch.gameweek_number.asc())
        .all()
    )

    match_data = []
    for m in matches:
        pa = m.participant_a
        pb = m.participant_b
        fa = db.query(FantasyTeam).filter(FantasyTeam.user_id == pa.fantasy_team_id).first()
        fb = db.query(FantasyTeam).filter(FantasyTeam.user_id == pb.fantasy_team_id).first()

        ua = db.query(User).filter(User.id == fa.user_id if fa else 0).first()
        ub = db.query(User).filter(User.id == fb.user_id if fb else 0).first()

        match_data.append({
            "match_id": m.id,
            "gameweek": m.gameweek_number,
            "participant_a": {
                "id": pa.id,
                "username": ua.username if ua else "Unknown",
                "team_name": fa.name if fa else "Unknown",
                "score": m.score_a,
            },
            "participant_b": {
                "id": pb.id,
                "username": ub.username if ub else "Unknown",
                "team_name": fb.name if fb else "Unknown",
                "score": m.score_b,
            },
            "status": m.status,
            "result": m.result,
        })

    # Knockout bracket (if applicable)
    bracket = None
    if league.knockout_stage:
        bracket = _build_knockout_bracket(matches, standings)

    return {
        "league_id": league.id,
        "league_name": league.name,
        "format": league.format_type,
        "standings": standings,
        "matches": match_data,
        "bracket": bracket,
        "total_participants": len(participants),
    }


def _build_knockout_bracket(matches, standings):
    """Build knockout bracket structure from matches."""
    rounds = {}
    for m in matches:
        gw = m["gameweek"]
        if gw not in rounds:
            rounds[gw] = []
        rounds[gw].append(m)

    bracket_rounds = []
    for round_num, round_matches in sorted(rounds.items()):
        bracket_rounds.append({
            "round": round_num,
            "matches": round_matches,
        })

    return bracket_rounds


@router.get("/{league_id}/standings")
def get_h2h_standings(
    league_id: int,
    db: Session = Depends(get_db),
):
    """Get detailed H2H standings table."""
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

    # Calculate standings
    standings = []
    for p in participants:
        fa = p.fantasy_team
        ua = fa.user

        standings.append({
            "participant_id": p.id,
            "rank": None,  # Will be set after sorting
            "username": ua.username,
            "team_name": fa.name,
            "h2h_points": p.h2h_points,
            "wins": p.wins,
            "draws": p.draws,
            "losses": p.losses,
            "byes": p.byes,
            "goal_difference": p.goal_difference,
            "form": _calculate_form(p.id, league_id, db),
        })

    # Sort and assign ranks
    standings.sort(key=lambda x: (
        x["h2h_points"], x["wins"], x["goal_difference"]
    ), reverse=True)

    for rank, s in enumerate(standings, 1):
        s["rank"] = rank

    return {
        "league_name": league.name,
        "standings": standings,
    }


def _calculate_form(participant_id: int, league_id: int, db: Session) -> list:
    """Calculate recent form (last 5 matches: W/D/L)."""
    matches = (
        db.query(H2hMatch)
        .filter(H2hMatch.h2h_league_id == league_id)
        .filter(
            (H2hMatch.participant_a_id == participant_id) |
            (H2hMatch.participant_b_id == participant_id)
        )
        .order_by(H2hMatch.gameweek_number.desc())
        .limit(5)
        .all()
    )

    form = []
    for m in matches:
        if m.status != "finished":
            continue

        is_a = m.participant_a_id == participant_id
        score_a = m.score_a or 0
        score_b = m.score_b or 0

        if is_a:
            if score_a > score_b:
                form.append("W")
            elif score_a < score_b:
                form.append("L")
            else:
                form.append("D")
        else:
            if score_b > score_a:
                form.append("W")
            elif score_b < score_a:
                form.append("L")
            else:
                form.append("D")

    return form
