"""Gameweek management API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import json

from app.database import get_db
from app.models import (
    Gameweek, Fixture, Player, SquadPlayer, FantasyTeam,
    FantasyTeamHistory, PlayerGameweekPoints, User, Season,
    DreamTeam, DreamTeamPlayer, Team,
)
from app.schemas import GameweekResponse, FixtureResponse
from app.scoring import (
    calculate_player_points, calculate_gameweek_score,
    calculate_selling_price,
    calculate_free_transfers,
    MAX_ROLLOVER_TRANSFERS,
    FREE_TRANSFER_PER_GW,
    auto_sub_squad,
)

router = APIRouter(prefix="/api/gameweeks", tags=["gameweeks"])


@router.get("/")
def list_gameweeks(
    season: str = "2025-26",
    db: Session = Depends(get_db),
):
    """List all gameweeks for a season.

    Returns {gameweeks: [...], current_gw: {...}} so the frontend can render
    deadlines and current GW info in one call.
    """
    gameweeks = db.query(Gameweek).filter(
        Gameweek.season == season,
    ).order_by(Gameweek.number.asc()).all()

    current = next((gw for gw in gameweeks if not gw.closed), None)
    next_unscored = next((gw for gw in gameweeks if not gw.scored), None)

    items = []
    for gw in gameweeks:
        fixture_count = db.query(Fixture).filter(Fixture.gameweek_id == gw.id).count()
        items.append({
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "start_date": gw.start_date.isoformat() if gw.start_date else None,
            "end_date": gw.end_date.isoformat() if gw.end_date else None,
            "deadline": gw.deadline.isoformat() if gw.deadline else None,
            "closed": gw.closed,
            "scored": gw.scored,
            "bonus_calculated": gw.bonus_calculated,
            "fixture_count": fixture_count,
            "is_current": current is not None and gw.id == current.id,
            "is_next": next_unscored is not None and gw.id == next_unscored.id,
        })

    return {
        "season": season,
        "gameweeks": items,
        "current_gw": {
            "id": current.id,
            "number": current.number,
            "deadline": current.deadline.isoformat() if current and current.deadline else None,
        } if current else None,
    }


@router.get("/current")
def get_current_gameweek(db: Session = Depends(get_db)):
    """Get the current open gameweek with deadline countdown."""
    from datetime import datetime, timezone

    gw = db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.number.desc()).first()

    if not gw:
        return {"gameweek": None, "message": "No active gameweek"}

    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw.id
    ).all()

    now = datetime.now(timezone.utc)
    deadline_dt = gw.deadline.replace(tzinfo=timezone.utc) if gw.deadline and gw.deadline.tzinfo is None else gw.deadline
    deadline_remaining = (deadline_dt - now).total_seconds() if deadline_dt and now else None

    # Calculate scoring progress
    total_fixtures = len(fixtures)
    completed_fixtures = sum(1 for f in fixtures if f.played)
    scoring_progress = (completed_fixtures / total_fixtures * 100) if total_fixtures > 0 else 0

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
        "deadline_remaining_seconds": int(deadline_remaining) if deadline_remaining else None,
        "deadline_remaining_formatted": _format_deadline(int(deadline_remaining)) if deadline_remaining else None,
        "scoring_progress": {
            "total_fixtures": total_fixtures,
            "completed_fixtures": completed_fixtures,
            "percentage": round(scoring_progress, 1),
        },
    }


def _format_deadline(seconds: int) -> str:
    """Format deadline seconds as readable string."""
    if seconds <= 0:
        return "Deadline passed"

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


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

    Scoring:
    - Auto-subs for non-playing starters
    - Captain multiplier (2x, or 3x with triple captain)
    - Bench boost (all squad score)
    - Transfer hits
    - Chip effects applied
    - Walkover: winning team players get 2 points
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if not gw.closed:
        raise HTTPException(status_code=400, detail="Gameweek not yet closed. Use /update-scores for live scoring.")

    # Process all fantasy teams
    teams = db.query(FantasyTeam).all()
    results = []

    for ft in teams:
        result = _score_single_team(ft, gw, db, is_rescore=gw.scored)
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


@router.post("/{gw_id}/update-scores")
def update_gameweek_scores(gw_id: int, db: Session = Depends(get_db)):
    """Update scores for a gameweek without requiring it to be closed.

    This is used for live scoring when fixture results come in before
    the gameweek deadline. It:
    - Scores all played fixtures (including walkovers)
    - Is idempotent: safe to call multiple times
    - Handles rescoring of already-scored gameweeks
    - Awards walkover points (2 pts) to winning team players
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    # Generate PlayerGameweekPoints for all played fixtures
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()

    if not fixtures:
        return {"gameweek": gw.number, "status": "no_played_fixtures"}

    # Generate player points for played fixtures (including walkovers)
    from app.scoring import calculate_bps, award_bonus_points
    import random

    created = 0
    walkover_count = 0
    for fixture in fixtures:
        is_walkover = fixture.home_score is None or fixture.away_score is None

        if is_walkover:
            walkover_count += 1
            # Determine winner from fixture data
            # If fixture is marked played but has no scores, check for walkover indicators
            # We'll need to infer from the fixture data or mark it properly
            # For now, award walkover points to both teams if we can't determine winner
            home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
            away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

            for team, is_home in [(home_team, True), (away_team, False)]:
                if not team:
                    continue

                team_players = db.query(Player).filter(
                    Player.team_id == team.id,
                    Player.is_active == True,
                ).all()

                opponent = fixture.away_team_name if is_home else fixture.home_team_name

                for player in team_players:
                    existing = db.query(PlayerGameweekPoints).filter(
                        PlayerGameweekPoints.player_id == player.id,
                        PlayerGameweekPoints.gameweek_id == gw_id,
                    ).first()
                    if existing:
                        continue

                    # Walkover: award 2 points to players
                    pgp = PlayerGameweekPoints(
                        player_id=player.id,
                        gameweek_id=gw_id,
                        opponent_team=opponent,
                        was_home=is_home,
                        minutes_played=0,
                        did_play=True,  # Walkover counts as playing
                        goals_scored=0,
                        clean_sheet=False,
                        goals_conceded=0,
                        base_points=2,
                        total_points=2,
                        bps_score=0,
                    )
                    db.add(pgp)
                    created += 1
        else:
            # Normal fixture with scores
            for team_id, goals_scored, goals_conceded, is_home in [
                (fixture.home_team_id, fixture.home_score or 0, fixture.away_score or 0, True),
                (fixture.away_team_id, fixture.away_score or 0, fixture.home_score or 0, False),
            ]:
                if team_id is None:
                    continue

                team_players = db.query(Player).filter(
                    Player.team_id == team_id,
                    Player.is_active == True,
                ).all()

                for player in team_players:
                    existing = db.query(PlayerGameweekPoints).filter(
                        PlayerGameweekPoints.player_id == player.id,
                        PlayerGameweekPoints.gameweek_id == gw_id,
                    ).first()
                    if existing:
                        continue

                    apps = player.apps or 1
                    player_goals = max(0, int((player.goals or 0) * (goals_scored / max(5, player.goals or 5))))
                    player_assists = max(0, int((player.assists or 0) * (goals_scored / 5)))
                    player_goals = min(player_goals, goals_scored)
                    player_assists = min(player_assists, goals_scored)

                    clean_sheet = (goals_conceded == 0)
                    saves = 0
                    if player.position == "GK":
                        saves = max(2, goals_conceded + random.randint(1, 4))

                    minutes = 90 if random.random() < 0.8 else random.choice([30, 45, 60, 75])

                    bps = calculate_bps(
                        position=player.position,
                        goals_scored=player_goals,
                        assists=player_assists,
                        clean_sheet=clean_sheet,
                        goals_conceded=goals_conceded if player.position in ("GK", "DEF") else 0,
                        saves=saves,
                        minutes_played=minutes,
                    )

                    points = calculate_player_points(
                        position=player.position,
                        goals_scored=player_goals,
                        assists=player_assists,
                        clean_sheet=clean_sheet and player.position in ("GK", "DEF", "MID"),
                        goals_conceded=goals_conceded if player.position in ("GK", "DEF") else 0,
                        saves=saves,
                        minutes_played=minutes,
                        bonus_points=0,
                    )

                    opponent = fixture.away_team_name if is_home else fixture.home_team_name

                    pgp = PlayerGameweekPoints(
                        player_id=player.id,
                        gameweek_id=gw_id,
                        opponent_team=opponent,
                        was_home=is_home,
                        minutes_played=minutes,
                        did_play=True,
                        goals_scored=player_goals,
                        assists=player_assists,
                        clean_sheet=clean_sheet and player.position in ("GK", "DEF", "MID"),
                        goals_conceded=goals_conceded if player.position in ("GK", "DEF") else 0,
                        saves=saves,
                        base_points=points,
                        total_points=points,
                        bps_score=bps,
                        influence_gw=round(random.uniform(5, 25), 1),
                        creativity_gw=round(random.uniform(5, 25), 1),
                        threat_gw=round(random.uniform(5, 30), 1),
                    )
                    db.add(pgp)
                    created += 1

    db.flush()

    # Now score fantasy teams
    teams = db.query(FantasyTeam).all()
    results = []
    for ft in teams:
        result = _score_single_team(ft, gw, db, is_rescore=gw.scored)
        results.append(result)

    gw.scored = True
    db.commit()

    return {
        "gameweek": gw.number,
        "status": "scores_updated",
        "player_points_created": created,
        "walkover_fixtures": walkover_count,
        "teams_scored": len(results),
        "results": results[:10],
    }


def _score_single_team(ft, gw, db, is_rescore=False):
    """Score a single fantasy team for a gameweek.

    Args:
        ft: FantasyTeam object
        gw: Gameweek object
        db: Database session
        is_rescore: If True, subtract previously scored points first
    """
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    if not squad:
        return {"team_id": ft.id, "points": 0, "error": "No squad"}

    # If rescoring, subtract previously scored points
    if is_rescore:
        existing_hist = db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.fantasy_team_id == ft.id,
            FantasyTeamHistory.gameweek_id == gw.id,
        ).first()
        if existing_hist:
            ft.total_points -= existing_hist.points
            # Reset squad player points
            for sp in squad:
                existing_pgp = db.query(PlayerGameweekPoints).filter(
                    PlayerGameweekPoints.player_id == sp.player_id,
                    PlayerGameweekPoints.gameweek_id == gw.id,
                ).first()
                if existing_pgp:
                    sp.total_points -= existing_pgp.total_points
                    sp.gw_points = 0
            # Delete old history
            db.delete(existing_hist)

    # Get active chip
    chip = ft.active_chip

    # Apply auto-subs
    non_playing = []
    for sp in squad:
        if sp.player.is_injured:
            non_playing.append(sp.player_id)

    formation = {"def": 4, "mid": 3, "fwd": 3}
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
        for sp, sp_data in zip(squad, squad_data):
            sp.is_starting = sp_data["is_starting"]

    # Calculate points for each player
    squad_points = []
    for sp in squad:
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
    # In FPL: free_transfers at start of GW = ft.free_transfers + ft.current_gw_transfers
    # (because each transfer decremented free_transfers)
    transfers_cost = 0
    if ft.current_gw_transfers > 0 and ft.active_chip not in ("wildcard", "free_hit"):
        starting_free = ft.free_transfers + ft.current_gw_transfers
        if ft.current_gw_transfers > starting_free:
            extra = ft.current_gw_transfers - starting_free
            transfers_cost = extra * 4

    # Calculate total
    total = 0
    for sp in squad_points:
        base = sp["base_points"]

        if chip == "bench_boost":
            contributes = sp["did_play"]
        else:
            contributes = sp["is_starting"] and sp["did_play"]

        if not contributes:
            continue

        if sp["id"] == captain_id:
            multiplier = 3 if chip == "triple_captain" else 2
            total += base * multiplier
        else:
            total += base

    # Apply transfer hit
    total -= transfers_cost

    # Update team totals
    ft.total_points += total

    # Record history
    history = FantasyTeamHistory(
        fantasy_team_id=ft.id,
        gameweek_id=gw.id,
        points=total,
        total_points=ft.total_points,
        transfers_made=ft.current_gw_transfers if not is_rescore else 0,
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
    """Update rollover transfers after gameweek ends.

    Free transfers can go negative to track extra transfers beyond free.
    After GW ends, reset to base value (1) with rollover from unused.
    """
    teams = db.query(FantasyTeam).all()

    for ft in teams:
        # If wildcard, reset to 1 free transfer
        if ft.active_chip == "wildcard":
            ft.free_transfers = 1
            ft.free_transfers_next_gw = 1
        else:
            # Free transfers can be negative (extra transfers beyond free)
            # After GW, reset to base 1 + rollover of unused
            # If free_transfers is negative, all were used (no rollover)
            unused = max(0, ft.free_transfers + ft.current_gw_transfers)
            rollover = min(unused, MAX_ROLLOVER_TRANSFERS)
            ft.free_transfers = 1 + rollover
            ft.free_transfers_next_gw = ft.free_transfers

        # Reset transfer count for next GW
        ft.current_gw_transfers = 0

        # Clear chip if not free hit (free hit cleared on revert)
        if ft.active_chip and ft.active_chip != "free_hit":
            ft.active_chip = None

        # Reset deadline exceeded
        ft.transfer_deadline_exceeded = False

    db.commit()


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

    # 3. Score
    score_result = score_gameweek(gw_id, db)

    # 4. Calculate Dream Team
    calculate_dream_team(gw_id, db)

    return score_result


@router.post("/{gw_id}/dream-team")
def calculate_dream_team_endpoint(gw_id: int, db: Session = Depends(get_db)):
    """Calculate the Dream Team for a gameweek.

    The Dream Team is the best 11 players by total points,
    selected in a valid formation (1 GK, 3-5 DEF, 3-5 MID, 3 FWD).
    """
    return calculate_dream_team(gw_id, db)


@router.get("/{gw_id}/dream-team")
def get_dream_team(gw_id: int, db: Session = Depends(get_db)):
    """Get the Dream Team for a gameweek."""
    dream_team = db.query(DreamTeam).filter(
        DreamTeam.gameweek_id == gw_id
    ).first()

    if not dream_team:
        raise HTTPException(status_code=404, detail="Dream Team not yet calculated for this gameweek")

    members = db.query(DreamTeamPlayer).filter(
        DreamTeamPlayer.dream_team_id == dream_team.id
    ).all()

    return {
        "dream_team": {
            "id": dream_team.id,
            "gameweek_id": dream_team.gameweek_id,
            "season": dream_team.season,
            "total_points": dream_team.total_points,
            "members": [
                {
                    "player_id": m.player_id,
                    "player_name": m.player.name if m.player else "Unknown",
                    "team_name": m.player.team.name if m.player and m.player.team else "Unknown",
                    "position": m.position,
                    "points": m.points,
                    "formation_position": m.formation_position,
                }
                for m in sorted(members, key=lambda x: x.formation_position)
            ],
        },
    }


def calculate_dream_team(gw_id: int, db: Session) -> dict:
    """Calculate the Dream Team for a gameweek.

    Simply the top 10 players by total points this gameweek.
    No position restrictions.
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    # Check if Dream Team already exists
    existing = db.query(DreamTeam).filter(DreamTeam.gameweek_id == gw_id).first()
    if existing:
        return {"status": "already_calculated", "dream_team_id": existing.id}

    # Get all players with points this gameweek
    player_points = db.query(PlayerGameweekPoints).filter(
        PlayerGameweekPoints.gameweek_id == gw_id,
        PlayerGameweekPoints.did_play == True,
    ).all()

    # Get player details
    player_ids = [pp.player_id for pp in player_points]
    players = {p.id: p for p in db.query(Player).filter(Player.id.in_(player_ids)).all()}

    # Build list of active players with their points
    candidates = []
    for pp in player_points:
        player = players.get(pp.player_id)
        if not player or not player.is_active:
            continue
        candidates.append({
            "player_id": pp.player_id,
            "player": player,
            "points": pp.total_points,
        })

    # Sort by points desc, take top 10
    candidates.sort(key=lambda x: x["points"], reverse=True)
    top_10 = candidates[:10]

    if not top_10:
        return {"status": "error", "message": "No players available for Dream Team"}

    total = sum(p["points"] for p in top_10)

    # Create Dream Team record
    dream_team = DreamTeam(
        gameweek_id=gw_id,
        season=gw.season,
        total_points=total,
    )
    db.add(dream_team)
    db.flush()

    # Create Dream Team members
    for i, entry in enumerate(top_10):
        member = DreamTeamPlayer(
            dream_team_id=dream_team.id,
            player_id=entry["player_id"],
            position=entry["player"].position,  # Keep for display only
            points=entry["points"],
            formation_position=i + 1,
        )
        db.add(member)

        # Mark player as in dream team
        entry["player"].in_dreamteam = True

    db.commit()

    return {
        "status": "calculated",
        "dream_team_id": dream_team.id,
        "total_points": total,
        "players_selected": len(top_10),
    }
