"""Gameweek management API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import (
    Gameweek, Fixture, Player, SquadPlayer, FantasyTeam,
    FantasyTeamHistory, PlayerGameweekPoints, User, Season,
)
from app.schemas import GameweekResponse, FixtureResponse
from app.scoring import (
    calculate_player_points, calculate_gameweek_score,
    calculate_bps, award_bonus_points,
    calculate_selling_price,
    calculate_free_transfers,
    MAX_ROLLOVER_TRANSFERS,
    FREE_TRANSFER_PER_GW,
    VALID_FORMATIONS,
    auto_sub_squad,
)

router = APIRouter(prefix="/api/gameweeks", tags=["gameweeks"])


@router.get("/", response_model=list)
def list_gameweeks(
    season: str = "2025-26",
    db: Session = Depends(get_db),
):
    """List all gameweeks for a season."""
    gameweeks = db.query(Gameweek).filter(
        Gameweek.season == season,
    ).order_by(Gameweek.number.asc()).all()

    return [
        {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "start_date": gw.start_date.isoformat() if gw.start_date else None,
            "end_date": gw.end_date.isoformat() if gw.end_date else None,
            "deadline": gw.deadline.isoformat() if gw.deadline else None,
            "closed": gw.closed,
            "scored": gw.scored,
        }
        for gw in gameweeks
    ]


@router.get("/current")
def get_current_gameweek(db: Session = Depends(get_db)):
    """Get the current open gameweek."""
    gw = db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.number.desc()).first()

    if not gw:
        return {"gameweek": None, "message": "No active gameweek"}

    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw.id
    ).all()

    return {
        "gameweek": {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "start_date": gw.start_date.isoformat() if gw.start_date else None,
            "deadline": gw.deadline.isoformat() if gw.deadline else None,
            "closed": gw.closed,
            "scored": gw.scored,
            "fixtures": [
                {
                    "id": f.id,
                    "date": f.date.isoformat() if f.date else None,
                    "home_team": f.home_team_name,
                    "away_team": f.away_team_name,
                    "home_score": f.home_score,
                    "away_score": f.away_score,
                    "played": f.played,
                }
                for f in fixtures
            ],
        },
        "deadline_remaining": (gw.deadline - datetime.utcnow()).total_seconds() if gw.deadline else None,
    }


@router.get("/{gw_id}", response_model=GameweekResponse)
def get_gameweek(gw_id: int, db: Session = Depends(get_db)):
    """Get a specific gameweek with fixtures."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw_id).all()

    return {
        "id": gw.id,
        "number": gw.number,
        "season": gw.season,
        "start_date": gw.start_date,
        "end_date": gw.end_date,
        "deadline": gw.deadline,
        "closed": gw.closed,
        "scored": gw.scored,
        "fixtures": [
            {
                "id": f.id,
                "gameweek": gw.number,
                "date": f.date,
                "home_team": f.home_team_name,
                "away_team": f.away_team_name,
                "home_score": f.home_score,
                "away_score": f.away_score,
                "played": f.played,
                "home_difficulty": f.home_difficulty,
                "away_difficulty": f.away_difficulty,
            }
            for f in fixtures
        ],
    }


@router.post("/create", response_model=dict)
def create_gameweek(
    number: int,
    season: str = "2025-26",
    days_until_deadline: int = 3,
    db: Session = Depends(get_db),
):
    """Create a new gameweek."""
    existing = db.query(Gameweek).filter(
        Gameweek.number == number,
        Gameweek.season == season,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Gameweek {number} already exists")

    deadline = datetime.utcnow() + timedelta(days=days_until_deadline)
    gw = Gameweek(
        number=number,
        season=season,
        start_date=datetime.utcnow().date(),
        deadline=deadline,
    )
    db.add(gw)
    db.commit()
    db.refresh(gw)

    return {"id": gw.id, "number": number, "deadline": gw.deadline.isoformat()}


@router.post("/{gw_id}/simulate-results")
def simulate_results(gw_id: int, db: Session = Depends(get_db)):
    """Simulate fixture results (random scores for testing).

    Generates realistic scorelines based on team strengths.
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    import random

    fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw_id).all()
    scored = 0

    for fixture in fixtures:
        if fixture.played:
            continue

        # Simulate scores based on difficulty
        home_strength = fixture.home_difficulty / 5.0
        away_strength = fixture.away_difficulty / 5.0

        # Generate realistic scores (weighted by difficulty)
        home_goals = max(0, int(random.gauss(1.3 * home_strength, 0.8)))
        away_goals = max(0, int(random.gauss(1.3 * away_strength, 0.8)))

        fixture.home_score = home_goals
        fixture.away_score = away_goals
        fixture.played = True
        scored += 1

    db.commit()

    return {
        "gameweek": gw.number,
        "fixtures_scored": scored,
        "total_fixtures": len(fixtures),
    }


@router.post("/{gw_id}/close")
def close_gameweek(gw_id: int, db: Session = Depends(get_db)):
    """Close a gameweek (mark deadline as passed)."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if gw.closed:
        raise HTTPException(status_code=400, detail="Gameweek already closed")

    gw.closed = True
    db.commit()

    return {"gameweek": gw.number, "status": "closed"}


@router.post("/{gw_id}/score")
def score_gameweek(gw_id: int, db: Session = Depends(get_db)):
    """Score a gameweek - calculate points for all fantasy teams.

    FPL 2025/26 scoring:
    - Auto-subs for non-playing starters
    - Captain multiplier (2x, or 3x with triple captain)
    - Bench boost (all 15 score)
    - BPS bonus points
    - Transfer hits
    - Chip effects applied
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if not gw.closed:
        raise HTTPException(status_code=400, detail="Gameweek not yet closed")

    if gw.scored:
        return {"gameweek": gw.number, "status": "already_scored"}

    # Process all fantasy teams
    teams = db.query(FantasyTeam).all()
    results = []

    for ft in teams:
        result = _score_single_team(ft, gw, db)
        results.append(result)

    # Process H2H matches for this GW
    _process_h2h_matches(gw, db)

    # Process free hit reverts
    _process_free_hit_reverts(gw, db)

    # Update rollover transfers
    _update_rollover_transfers(gw, db)

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()

    return {
        "gameweek": gw.number,
        "status": "scored",
        "teams_scored": len(results),
        "results": results[:10],  # Return first 10 for preview
    }


def _score_single_team(ft, gw, db):
    """Score a single fantasy team for a gameweek."""
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    if not squad:
        return {"team_id": ft.id, "points": 0, "error": "No squad"}

    # Get active chip
    chip = ft.active_chip

    # Apply auto-subs
    # In real system, we'd check who didn't play (minutes=0)
    # For now, all players "played" unless marked
    non_playing = []
    for sp in squad:
        # Check if player is injured
        if sp.player.is_injured:
            non_playing.append(sp.player_id)

    # Get formation for auto-sub
    formation = {"def": 4, "mid": 3, "fwd": 3}  # Default 4-3-3
    if non_playing:
        squad_data = [
            {
                "id": sp.id,
                "player_id": sp.player_id,
                "is_starting": sp.is_starting,
                "player": {"position": sp.player.position},
            }
            for sp in squad
        ]
        auto_sub_squad(squad_data, non_playing, formation)
        # Apply changes back
        for sp, sp_data in zip(squad, squad_data):
            sp.is_starting = sp_data["is_starting"]

    # Calculate points for each player
    squad_points = []
    for sp in squad:
        # Get or calculate player's GW points
        pgw = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == sp.player_id,
            PlayerGameweekPoints.gameweek_id == gw.id,
        ).first()

        if pgw:
            base_pts = pgw.total_points
            did_play = pgw.did_play
        else:
            base_pts = 0
            did_play = False

        # Update squad player GW points
        sp.gw_points = base_pts
        sp.total_points += base_pts

        squad_points.append({
            "id": sp.id,
            "base_points": base_pts,
            "is_starting": sp.is_starting,
            "is_captain": sp.is_captain,
            "is_vice_captain": sp.is_vice_captain,
            "did_play": did_play,
            "player_position": sp.player.position,
        })

    # Find captain/vice
    captain_id = next((sp["id"] for sp in squad_points if sp["is_captain"]), None)
    vice_id = next((sp["id"] for sp in squad_points if sp["is_vice_captain"]), None)

    if not captain_id:
        captain_id = squad_points[0]["id"] if squad_points else None
    if not vice_id:
        vice_id = squad_points[1]["id"] if len(squad_points) > 1 else None

    # Calculate transfer hit
    transfers_cost = 0
    if ft.current_gw_transfers > 0 and ft.active_chip not in ("wildcard", "free_hit"):
        free_available = ft.free_transfers + ft.current_gw_transfers
        if ft.current_gw_transfers > free_available:
            extra = ft.current_gw_transfers - free_available
            transfers_cost = extra * 4

    # Calculate total
    total = 0
    for sp in squad_points:
        base = sp["base_points"]

        # Check if player contributes
        if chip == "bench_boost":
            contributes = sp["did_play"]
        else:
            contributes = sp["is_starting"] and sp["did_play"]

        if not contributes:
            continue

        # Captain multiplier
        if sp["id"] == captain_id:
            multiplier = 3 if chip == "triple_captain" else 2
            total += base * multiplier
        else:
            total += base

    # Apply transfer hit
    total -= transfers_cost

    # Update team totals
    ft.total_points += total
    ft.current_gw_transfers = 0

    # Record history
    history = FantasyTeamHistory(
        fantasy_team_id=ft.id,
        gameweek_id=gw.id,
        points=total,
        total_points=ft.total_points,
        transfers_made=0,
        transfers_cost=transfers_cost,
        chip_used=chip,
    )
    db.add(history)

    return {
        "team_id": ft.id,
        "team_name": ft.name,
        "points": total,
        "total_points": ft.total_points,
        "transfers_cost": transfers_cost,
        "chip_used": chip,
    }


def _process_h2h_matches(gw, db):
    """Process H2H matches for this gameweek."""
    from app.models import H2hMatch, H2hParticipant

    matches = db.query(H2hMatch).filter(
        H2hMatch.gameweek_number == gw.number,
        H2hMatch.status == "pending",
    ).all()

    for match in matches:
        pa = db.query(H2hParticipant).filter(H2hParticipant.id == match.participant_a_id).first()
        pb = db.query(H2hParticipant).filter(H2hParticipant.id == match.participant_b_id).first()

        if not pa or not pb:
            continue

        # Get GW points from history
        hist_a = db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.fantasy_team_id == pa.fantasy_team_id,
            FantasyTeamHistory.gameweek_id == gw.id,
        ).first()
        hist_b = db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.fantasy_team_id == pb.fantasy_team_id,
            FantasyTeamHistory.gameweek_id == gw.id,
        ).first()

        pts_a = hist_a.points if hist_a else 0
        pts_b = hist_b.points if hist_b else 0

        match.score_a = pts_a
        match.score_b = pts_b
        match.status = "finished"

        if pts_a > pts_b:
            match.result = "win_a"
            pa.h2h_points += 2
            pa.wins += 1
            pb.losses += 1
        elif pts_b > pts_a:
            match.result = "win_b"
            pb.h2h_points += 2
            pb.wins += 1
            pa.losses += 1
        else:
            match.result = "draw"
            pa.h2h_points += 1
            pb.h2h_points += 1
            pa.draws += 1
            pb.draws += 1

        pa.goal_difference += (pts_a - pts_b)
        pb.goal_difference += (pts_b - pts_a)

    db.commit()


def _process_free_hit_reverts(gw, db):
    """Revert squads that used Free Hit in the previous gameweek."""
    from app.models import SquadPlayer
    import json

    teams = db.query(FantasyTeam).filter(
        FantasyTeam.free_hit_revert_gw == gw.number,
        FantasyTeam.free_hit_backup.isnot(None),
    ).all()

    for ft in teams:
        try:
            backup_data = json.loads(ft.free_hit_backup)
        except (json.JSONDecodeError, TypeError):
            continue

        # Clear current squad
        current_squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).all()
        for sp in current_squad:
            db.delete(sp)

        # Rebuild from backup
        for bp in backup_data:
            player = db.query(Player).filter(Player.id == bp["player_id"]).first()
            if not player:
                continue

            sp = SquadPlayer(
                fantasy_team_id=ft.id,
                player_id=bp["player_id"],
                position_slot=bp["position_slot"],
                is_captain=bp["is_captain"],
                is_vice_captain=bp["is_vice_captain"],
                is_starting=bp["is_starting"],
                purchase_price=bp["purchase_price"],
                bench_priority=bp.get("bench_priority", 99),
                selling_price=player.price,
            )
            db.add(sp)

        ft.free_hit_backup = None
        ft.free_hit_revert_gw = None
        ft.active_chip = None

    db.commit()


def _update_rollover_transfers(gw, db):
    """Update rollover transfers after gameweek ends."""
    teams = db.query(FantasyTeam).all()

    for ft in teams:
        # Calculate rollover
        new_free = calculate_free_transfers(
            ft.free_transfers,
            ft.current_gw_transfers,
            is_wildcard=(ft.active_chip == "wildcard"),
        )
        ft.free_transfers_next_gw = new_free
        ft.free_transfers = new_free

        # Reset transfer count for next GW
        ft.current_gw_transfers = 0

        # Clear chip if not free hit (free hit cleared on revert)
        if ft.active_chip and ft.active_chip != "free_hit":
            ft.active_chip = None

        # Reset deadline exceeded
        ft.transfer_deadline_exceeded = False

    db.commit()


@router.post("/{gw_id}/bonus")
def calculate_bonus(gw_id: int, db: Session = Depends(get_db)):
    """Calculate and award BPS bonus points for a gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if not gw.closed:
        raise HTTPException(status_code=400, detail="Gameweek not yet closed")

    # Get all players with GW points
    player_points = db.query(PlayerGameweekPoints).filter(
        PlayerGameweekPoints.gameweek_id == gw_id,
    ).all()

    # Group by fixture and award top 3 per fixture
    fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw_id).all()
    fixture_ids = {f.id for f in fixtures}

    total_bonused = 0
    for fixture in fixtures:
        fixture_players = [
            pp for pp in player_points
            if pp.opponent_team in (fixture.home_team_name, fixture.away_team_name)
        ]

        if len(fixture_players) < 3:
            continue

        # Calculate BPS
        for pp in fixture_players:
            player = db.query(Player).filter(Player.id == pp.player_id).first()
            if not player:
                continue

            pp.bps_score = calculate_bps(
                position=player.position,
                goals_scored=pp.goals_scored,
                assists=pp.assists,
                clean_sheet=pp.clean_sheet,
                goals_conceded=pp.goals_conceded,
                saves=pp.saves,
                yellow_card=pp.yellow_card,
                red_card=pp.red_card,
                own_goal=pp.own_goal,
                penalties_saved=pp.penalties_saved,
                penalties_missed=pp.penalties_missed,
                minutes_played=pp.minutes_played,
                was_penalty_goal=pp.was_penalty_goal,
                bonus_points=pp.bonus_points,
            )

        # Award bonus
        bps_list = [{"player_id": pp.player_id, "bps": pp.bps_score} for pp in fixture_players]
        bonus_map = award_bonus_points(bps_list)

        for player_id, bonus in bonus_map.items():
            pp = next(p for p in fixture_players if p.player_id == player_id)
            pp.bonus_points = bonus
            pp.total_points = pp.base_points + bonus
            total_bonused += 1

    db.commit()

    return {
        "gameweek": gw.number,
        "status": "bonus_calculated",
        "players_bonused": total_bonused,
        "fixtures_processed": len(fixtures),
    }


@router.post("/simulate-and-score")
def simulate_and_score(
    gw_id: int,
    db: Session = Depends(get_db),
):
    """Convenience endpoint: simulate results, close, calculate bonus, then score.

    Runs the complete gameweek processing pipeline.
    """
    # 1. Simulate results
    simulate_results(gw_id, db)

    # 2. Close gameweek
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    gw.closed = True
    db.commit()

    # 3. Calculate bonus
    calculate_bonus(gw_id, db)

    # 4. Score
    return score_gameweek(gw_id, db)
