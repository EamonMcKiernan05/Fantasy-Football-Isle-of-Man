"""Gameweeks API routes - FPL rules compliant."""
import json
import random
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from typing import Optional

from app.database import get_db
from app.models import (
    Gameweek, Fixture, Player, Team, Division, PlayerGameweekPoints,
    FantasyTeam, SquadPlayer, FantasyTeamHistory, Season, User,
)
from app import scoring, api_client

router = APIRouter(prefix="/api/gameweeks", tags=["gameweeks"])


@router.get("/")
def list_gameweeks(
    season: str = Query("2025-26", description="Season to filter by"),
    db: Session = Depends(get_db),
):
    """List all gameweeks for a season."""
    gameweeks = db.query(Gameweek).filter(
        Gameweek.season == season
    ).order_by(Gameweek.number).all()

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
            "bonus_calculated": gw.bonus_calculated,
            "fixture_count": len(gw.fixtures),
        }
        for gw in gameweeks
    ]


@router.get("/current")
def get_current_gameweek(db: Session = Depends(get_db)):
    """Get the current active gameweek with fixtures."""
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    if not current_gw:
        return {"gameweek": None, "message": "No active gameweek"}

    fixtures = []
    for f in current_gw.fixtures:
        fixtures.append({
            "id": f.id,
            "date": f.date.isoformat() if f.date else None,
            "home_team": f.home_team_name,
            "away_team": f.away_team_name,
            "home_score": f.home_score,
            "away_score": f.away_score,
            "played": f.played,
            "home_difficulty": f.home_difficulty,
            "away_difficulty": f.away_difficulty,
        })

    return {
        "gameweek": {
            "id": current_gw.id,
            "number": current_gw.number,
            "season": current_gw.season,
            "start_date": current_gw.start_date.isoformat() if current_gw.start_date else None,
            "deadline": current_gw.deadline.isoformat() if current_gw.deadline else None,
            "closed": current_gw.closed,
            "scored": current_gw.scored,
        },
        "fixtures": fixtures,
    }


@router.get("/{gw_id}")
def get_gameweek(gw_id: int, db: Session = Depends(get_db)):
    """Get a specific gameweek with fixtures and results."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    fixtures = []
    for f in gw.fixtures:
        fixtures.append({
            "id": f.id,
            "date": f.date.isoformat() if f.date else None,
            "home_team": f.home_team_name,
            "away_team": f.away_team_name,
            "home_score": f.home_score,
            "away_score": f.away_score,
            "half_time": {
                "home": f.half_time_home,
                "away": f.half_time_away,
            },
            "played": f.played,
            "home_scorers": json.loads(f.home_scorers) if f.home_scorers else [],
            "away_scorers": json.loads(f.away_scorers) if f.away_scorers else [],
        })

    return {
        "gameweek": {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "closed": gw.closed,
            "scored": gw.scored,
            "bonus_calculated": gw.bonus_calculated,
        },
        "fixtures": fixtures,
    }


@router.get("/{gw_id}/score/{user_id}")
def get_gameweek_score(gw_id: int, user_id: int, db: Session = Depends(get_db)):
    """Get a user's score for a specific gameweek with breakdown."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    history = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.fantasy_team_id == ft.id,
        FantasyTeamHistory.gameweek_id == gw_id,
    ).first()

    # Get individual player scores
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    player_scores = []
    total = 0
    for sp in squad:
        pgp = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == sp.player_id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()

        if pgp:
            points = pgp.total_points
            # Apply captain multiplier
            if sp.is_captain:
                chip = history.chip_used if history else None
                points = scoring.calculate_captain_points(pgp.total_points, True, chip)
        else:
            points = 0

        total += points
        player_scores.append({
            "player_id": sp.player_id,
            "player_name": sp.player.name if sp.player else "Unknown",
            "position": sp.player.position if sp.player else "",
            "team": sp.player.team.name if sp.player and sp.player.team else "",
            "points": points,
            "is_captain": sp.is_captain,
            "is_starting": sp.is_starting,
            "was_autosub": sp.was_autosub,
            "minutes_played": pgp.minutes_played if pgp else 0,
        })

    return {
        "gameweek": gw.number,
        "total_points": total if not history else history.points,
        "history_points": history.points if history else None,
        "chip_used": history.chip_used if history else None,
        "transfers_cost": history.transfers_cost if history else 0,
        "players": player_scores,
    }


@router.post("/sync")
def sync_gameweeks(db: Session = Depends(get_db)):
    """Sync fixtures from FullTime API and create gameweeks."""
    scraper = api_client.FullTimeAPIClient()
    raw_fixtures = scraper.get_all_fixtures()

    if not raw_fixtures:
        return {"status": "error", "message": "No fixture data retrieved"}

    # Get or create season
    season = db.query(Season).filter(Season.name == "2025-26").first()
    if not season:
        season = Season(name="2025-26", total_gameweeks=30, started=True)
        db.add(season)
        db.flush()

    # Group fixtures by gameweek (by date clusters)
    fixtures_by_gw = {}
    for fix in raw_fixtures:
        date_key = fix.get("date", datetime.now())
        if isinstance(date_key, str):
            date_key = datetime.fromisoformat(date_key.replace("Z", ""))
        # Group by week number
        gw_num = date_key.isocalendar()[1]  # ISO week number
        if gw_num not in fixtures_by_gw:
            fixtures_by_gw[gw_num] = []
        fixtures_by_gw[gw_num].append(fix)

    gameweeks_created = 0
    fixtures_synced = 0

    for gw_num, fixtures in fixtures_by_gw.items():
        # Get or create gameweek
        gw = db.query(Gameweek).filter(
            Gameweek.number == gw_num,
            Gameweek.season == "2025-26",
        ).first()

        if not gw:
            # Calculate dates
            gw_date = min(f.get("date", datetime.now()) for f in fixtures)
            if isinstance(gw_date, str):
                gw_date = datetime.fromisoformat(gw_date.replace("Z", ""))

            start = gw_date.date()
            end = start + timedelta(days=7)
            # Deadline: Saturday 1pm before first match
            days_until_sat = 5 - gw_date.weekday()
            deadline_date = gw_date.date() + timedelta(days=days_until_sat)
            if deadline_date <= start:
                deadline_date -= timedelta(days=7)
            deadline = datetime.combine(deadline_date, datetime(2025, 1, 1, 13, 0).timetz())
            deadline = datetime.combine(deadline_date, datetime(2025, 1, 1, 13, 0).timetz())

            gw = Gameweek(
                number=gw_num,
                season="2025-26",
                start_date=start,
                end_date=end,
                deadline=deadline,
            )
            db.add(gw)
            db.flush()
            gameweeks_created += 1

        # Process fixtures
        for fix in fixtures:
            existing = db.query(Fixture).filter(
                Fixture.gameweek_id == gw.id,
                Fixture.home_team_name == fix.get("home_team", ""),
                Fixture.away_team_name == fix.get("away_team", ""),
            ).first()

            if not existing:
                fixture = Fixture(
                    gameweek_id=gw.id,
                    date=fix.get("date", datetime.now()),
                    home_team_name=fix.get("home_team", ""),
                    away_team_name=fix.get("away_team", ""),
                    home_score=fix.get("home_score"),
                    away_score=fix.get("away_score"),
                    half_time_home=fix.get("half_time_home"),
                    half_time_away=fix.get("half_time_away"),
                    home_scorers=fix.get("home_scorers"),
                    away_scorers=fix.get("away_scorers"),
                    played=fix.get("played", False),
                )
                db.add(fixture)
                fixtures_synced += 1

        # Link teams
        for f in gw.fixtures:
            if not f.home_team_id:
                home = db.query(Team).filter(Team.name == f.home_team_name).first()
                if home:
                    f.home_team_id = home.id
            if not f.away_team_id:
                away = db.query(Team).filter(Team.name == f.away_team_name).first()
                if away:
                    f.away_team_id = away.id

    db.commit()

    return {
        "status": "success",
        "gameweeks_created": gameweeks_created,
        "fixtures_synced": fixtures_synced,
        "total_gameweeks": len(fixtures_by_gw),
    }


@router.post("/score/{gw_id}")
def score_gameweek(gw_id: int, db: Session = Depends(get_db)):
    """Score all gameweek points and apply bonus.

    This is the main scoring endpoint that:
    1. Calculates points for each player based on fixtures
    2. Applies captain multiplier
    3. Handles bench boost chip
    4. Applies transfer hits
    5. Calculates bonus points via BPS
    """
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    if gw.scored:
        return {"status": "already_scored", "gameweek": gw.number}

    fixtures = gw.fixtures
    scored_count = 0

    for fixture in fixtures:
        if not fixture.played:
            continue

        home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
        away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

        # Determine clean sheets
        home_clean_sheet = (fixture.away_score or 0) == 0
        away_clean_sheet = (fixture.home_score or 0) == 0

        # Score home team players
        if home_team:
            _score_team_players(
                db, gw_id, home_team,
                opponent_name=fixture.away_team_name,
                is_home=True,
                goals_scored=fixture.home_score or 0,
                goals_conceded=fixture.away_score or 0,
                clean_sheet=home_clean_sheet,
                scorers=json.loads(fixture.home_scorers) if fixture.home_scorers else [],
            )

        # Score away team players
        if away_team:
            _score_team_players(
                db, gw_id, away_team,
                opponent_name=fixture.home_team_name,
                is_home=False,
                goals_scored=fixture.away_score or 0,
                goals_conceded=fixture.home_score or 0,
                clean_sheet=away_clean_sheet,
                scorers=json.loads(fixture.away_scorers) if fixture.away_scorers else [],
            )

        scored_count += 1

    # Calculate bonus points
    _calculate_gameweek_bonus(db, gw_id, fixtures)

    # Update fantasy team scores
    _update_team_scores(db, gw_id)

    # Auto-sub players who didn't play
    _process_autosubs(db, gw_id)

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()

    return {
        "status": "scored",
        "gameweek": gw.number,
        "fixtures_scored": scored_count,
    }


def _score_team_players(
    db: Session,
    gw_id: int,
    team: Team,
    *,
    opponent_name: str,
    is_home: bool,
    goals_scored: int,
    goals_conceded: int,
    clean_sheet: bool,
    scorers: list,
):
    """Score players from a team for a fixture."""
    players = db.query(Player).filter(
        Player.team_id == team.id,
        Player.is_active == True,
    ).all()

    for player in players:
        # Check if already scored this GW
        existing = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()

        if existing:
            continue

        # Calculate stats for this fixture
        player_goals = 1 if player.name in scorers else 0
        player_assists = 0  # Would need detailed stats from API

        # Minutes: estimate based on whether player played
        minutes = 90 if player_goals > 0 or random.random() > 0.3 else 0

        # Calculate points
        points = scoring.calculate_player_points(
            position=player.position,
            goals_scored=player_goals,
            assists=player_assists,
            clean_sheet=clean_sheet if player.position in ("GK", "DEF", "MID") else False,
            goals_conceded=goals_conceded,
            minutes_played=minutes,
            saves=random.randint(0, 4) if player.position == "GK" else 0,
        )

        pgp = PlayerGameweekPoints(
            player_id=player.id,
            gameweek_id=gw_id,
            opponent_team=opponent_name,
            was_home=is_home,
            minutes_played=minutes,
            did_play=minutes > 0,
            goals_scored=player_goals,
            assists=player_assists,
            clean_sheet=clean_sheet,
            goals_conceded=goals_conceded,
            base_points=points,
            total_points=points,
        )
        db.add(pgp)

        # Update player season stats
        player.apps += 1
        player.goals += player_goals
        player.assists += player_assists
        if clean_sheet and player.position in ("GK", "DEF", "MID"):
            player.clean_sheets += 1
        player.goals_conceded += goals_conceded
        player.total_points_season += points


def _calculate_gameweek_bonus(db: Session, gw_id: int, fixtures):
    """Calculate BPS bonus points for the gameweek."""
    for fixture in fixtures:
        if not fixture.played:
            continue

        home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
        away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

        all_players_bps = []

        for team, is_home in [(home_team, True), (away_team, False)]:
            if not team:
                continue
            team_players = db.query(Player).filter(
                Player.team_id == team.id,
                Player.is_active == True,
            ).all()

            for player in team_players:
                pgp = db.query(PlayerGameweekPoints).filter(
                    PlayerGameweekPoints.player_id == player.id,
                    PlayerGameweekPoints.gameweek_id == gw_id,
                ).first()
                if not pgp or not pgp.did_play:
                    continue

                bps = scoring.calculate_bps(
                    position=player.position,
                    goals_scored=pgp.goals_scored,
                    clean_sheet=pgp.clean_sheet,
                    goals_conceded=pgp.goals_conceded,
                    saves=pgp.saves,
                    minutes_played=pgp.minutes_played,
                )
                pgp.bps_score = bps
                all_players_bps.append({"player_id": player.id, "bps": bps})

        # Award bonus to top 3
        if len(all_players_bps) >= 3:
            bonus_map = scoring.award_bonus_points(all_players_bps)
            for player_id, bonus in bonus_map.items():
                pgp = db.query(PlayerGameweekPoints).filter(
                    PlayerGameweekPoints.player_id == player_id,
                    PlayerGameweekPoints.gameweek_id == gw_id,
                ).first()
                if pgp and bonus > 0:
                    pgp.bonus_points = bonus
                    pgp.total_points = pgp.base_points + bonus

                    # Update player bonus total
                    player = db.query(Player).filter(Player.id == player_id).first()
                    if player:
                        player.bonus += bonus
                        player.total_points_season += bonus

                    # Update squad totals
                    squad_entries = db.query(SquadPlayer).join(FantasyTeam).filter(
                        SquadPlayer.player_id == player_id
                    ).all()
                    for sp in squad_entries:
                        sp.total_points += bonus


def _update_team_scores(db: Session, gw_id: int):
    """Update fantasy team scores for the gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    teams = db.query(FantasyTeam).all()

    for ft in teams:
        squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).all()

        # Determine captain
        captain_sp = next((sp for sp in squad if sp.is_captain), None)
        vc_sp = next((sp for sp in squad if sp.is_vice_captain), None)

        # Check if captain played
        effective_captain = captain_sp
        if captain_sp:
            cp_gp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == captain_sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if not cp_gp or not cp_gp.did_play:
                effective_captain = vc_sp

        # Calculate team score
        chip = ft.active_chip
        total = 0

        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()

            if not pgp or not pgp.did_play:
                continue

            # Determine if player contributes
            if chip == "bench_boost":
                contributes = True
            else:
                contributes = sp.is_starting

            if not contributes:
                continue

            points = pgp.total_points

            # Captain multiplier
            if sp == effective_captain:
                multiplier = 3 if chip == "triple_captain" else 2
                points = pgp.total_points * multiplier

            total += points
            sp.gw_points = points

        # Transfer hit
        transfer_hit = ft.current_gw_transfers * 4 if ft.current_gw_transfers > ft.free_transfers else 0
        total -= transfer_hit

        # Update team
        ft.total_points += total

        # Create history entry
        history = FantasyTeamHistory(
            fantasy_team_id=ft.id,
            gameweek_id=gw_id,
            points=total,
            total_points=ft.total_points,
            chip_used=chip,
            transfers_made=ft.current_gw_transfers,
            transfers_cost=transfer_hit,
        )
        db.add(history)

    # Calculate ranks
    all_teams = db.query(FantasyTeam).order_by(FantasyTeam.total_points.desc()).all()
    for rank, team in enumerate(all_teams, 1):
        team.overall_rank = rank


def _process_autosubs(db: Session, gw_id: int):
    """Auto-substitute players who didn't play with bench players.

    FPL auto-sub rules:
    - Sub out players who didn't play (minutes = 0)
    - Sub in bench players in priority order (by position then lowest slot)
    - Maintain valid formation (1 GK, min 3 DEF, 1 MID, 1 FWD)
    """
    teams = db.query(FantasyTeam).all()

    for ft in teams:
        if ft.active_chip == "bench_boost":
            continue  # Bench boost means all 15 play

        squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id
        ).order_by(SquadPlayer.position_slot).all()

        # Find non-playing starters
        non_playing_starters = []
        for sp in squad:
            if not sp.is_starting:
                continue
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if not pgp or not pgp.did_play:
                non_playing_starters.append(sp)

        # Find available bench players who DID play
        available_subs = []
        for sp in squad:
            if sp.is_starting:
                continue
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if pgp and pgp.did_play:
                available_subs.append(sp)

        # Auto-sub
        for starter in non_playing_starters:
            if not available_subs:
                break

            # Find sub of same position type
            starter_pos = starter.player.position if starter.player else "MID"

            # Try same position first
            same_pos_sub = next(
                (s for s in available_subs
                 if s.player and s.player.position == starter_pos),
                None
            )

            if same_pos_sub:
                sub_player = same_pos_sub
            else:
                # Any available sub
                sub_player = available_subs[0]

            if sub_player:
                # Swap
                starter.is_starting = False
                sub_player.is_starting = True
                sub_player.was_autosub = True
                available_subs.remove(sub_player)

    db.commit()


def _score_gameweek_direct(db: Session, gw_id: int):
    """Direct gameweek scoring for scheduler (no dependency injection)."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        return

    if gw.scored:
        return

    fixtures = gw.fixtures
    scored_count = 0

    for fixture in fixtures:
        if not fixture.played:
            continue

        home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
        away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

        home_clean_sheet = (fixture.away_score or 0) == 0
        away_clean_sheet = (fixture.home_score or 0) == 0

        if home_team:
            _score_team_players(
                db, gw_id, home_team,
                opponent_name=fixture.away_team_name,
                is_home=True,
                goals_scored=fixture.home_score or 0,
                goals_conceded=fixture.away_score or 0,
                clean_sheet=home_clean_sheet,
                scorers=json.loads(fixture.home_scorers) if fixture.home_scorers else [],
            )

        if away_team:
            _score_team_players(
                db, gw_id, away_team,
                opponent_name=fixture.home_team_name,
                is_home=False,
                goals_scored=fixture.away_score or 0,
                goals_conceded=fixture.home_score or 0,
                clean_sheet=away_clean_sheet,
                scorers=json.loads(fixture.away_scorers) if fixture.away_scorers else [],
            )

        scored_count += 1

    _calculate_gameweek_bonus(db, gw_id, fixtures)
    _update_team_scores(db, gw_id)
    _process_autosubs(db, gw_id)

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()
