"""Gameweeks API routes - manage gameweeks and fixtures."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from typing import List, Optional
import re

from app.database import get_db
from app.models import Gameweek, Fixture, PlayerFixture, SquadPlayer, FantasyTeam
from app.schemas import GameweekResponse, GameweekWithFixtures, FixtureResponse, GameweekScoreResponse, TeamScore
from app import api_client, scoring

router = APIRouter(prefix="/api/gameweeks", tags=["gameweeks"])


def parse_score_safe(val):
    """Safely parse a score value that may be string or None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


@router.get("/current")
def get_current_gameweek(db: Session = Depends(get_db)):
    """Get the current active gameweek."""
    gw = db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.start_date.desc()).first()

    if not gw:
        return {"message": "No active gameweek", "gameweek": None}

    fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw.id).all()

    return {
        "gameweek": {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "start_date": str(gw.start_date),
            "deadline": gw.deadline.isoformat(),
            "bonus_calculated": gw.bonus_calculated,
            "closed": gw.closed,
        },
        "fixtures": [
            {
                "id": f.id,
                "date": f.date.isoformat() if f.date else None,
                "home_team": f.home_team,
                "away_team": f.away_team,
                "home_score": f.home_score,
                "away_score": f.away_score,
                "played": f.played,
            }
            for f in fixtures
        ],
    }


@router.post("/sync")
def sync_gameweeks(db: Session = Depends(get_db)):
    """Sync fixtures from FullTime API into gameweeks."""
    client = api_client.FullTimeAPIClient()

    # Get all division data
    divisions = client.get_league_divisions()

    # Collect all fixtures across divisions
    all_fixtures = []
    for div in divisions:
        div_id = div["id"]

        try:
            fixtures = client.get_fixtures(div_id)
            for f in fixtures:
                if f.get("fixtureDateTime"):
                    all_fixtures.append({
                        **f,
                        "division": div["name"],
                    })
        except Exception:
            pass

        try:
            results = client.get_results(div_id)
            for r in results[:20]:
                if r.get("fixtureDateTime"):
                    all_fixtures.append({
                        **r,
                        "division": r.get("division", div["name"]),
                    })
        except Exception:
            pass

    # Group by date (gameweek)
    date_groups = {}
    for f in all_fixtures:
        dt = client.parse_date(f.get("fixtureDateTime", ""))
        if dt:
            # Round to the Saturday of the week
            week_start = dt - timedelta(days=dt.weekday() + 1)
            key = week_start.date()
            if key not in date_groups:
                date_groups[key] = []
            date_groups[key].append(f)

    synced = 0
    gw_number = db.query(Gameweek).count() + 1

    for gw_date, fixtures in sorted(date_groups.items()):
        gw_deadline = datetime.combine(gw_date, datetime.min.time().replace(hour=11, minute=0))

        # Find or create gameweek
        gw = db.query(Gameweek).filter(
            Gameweek.start_date == gw_date
        ).first()

        if not gw:
            gw = Gameweek(
                number=gw_number,
                season="2025-26",
                start_date=gw_date,
                deadline=gw_deadline,
            )
            db.add(gw)
            db.flush()
            gw_number += 1

        existing_fixture_ids = {
            (f.home_team, f.away_team)
            for f in db.query(Fixture).filter(Fixture.gameweek_id == gw.id).all()
        }

        # Add/update fixtures
        for f in fixtures:
            home_team = f.get("homeTeam", "")
            away_team = f.get("awayTeam", "")
            if not home_team or not away_team:
                continue

            if (home_team, away_team) in existing_fixture_ids:
                continue

            home_score = parse_score_safe(f.get("homeScore"))
            away_score = parse_score_safe(f.get("awayScore"))

            ht_home, ht_away = None, None
            if home_score is not None and away_score is not None:
                score_str = f.get("score", "") or ""
                ht_match = re.search(r"\(HT\s*(\d+)\s*-\s*(\d+)\)", score_str)
                if ht_match:
                    ht_home = int(ht_match.group(1))
                    ht_away = int(ht_match.group(2))

            fixture = Fixture(
                gameweek_id=gw.id,
                date=client.parse_date(f.get("fixtureDateTime", "")) or datetime.combine(gw_date, datetime.min.time()),
                home_team=home_team,
                away_team=away_team,
                competition=f.get("division", f.get("competition", "")) or "",
                home_score=home_score,
                away_score=away_score,
                half_time_home=ht_home,
                half_time_away=ht_away,
                played=(home_score is not None and away_score is not None),
            )
            db.add(fixture)
            synced += 1
            existing_fixture_ids.add((home_team, away_team))

    db.commit()
    return {"status": "synced", "fixtures_synced": synced, "gameweeks": len(date_groups)}


@router.get("/", response_model=List[GameweekResponse])
def list_gameweeks(db: Session = Depends(get_db)):
    """List all gameweeks."""
    return db.query(Gameweek).order_by(Gameweek.number).all()


@router.get("/{gw_id}", response_model=GameweekWithFixtures)
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
        "deadline": gw.deadline,
        "bonus_calculated": gw.bonus_calculated,
        "closed": gw.closed,
        "fixtures": fixtures,
    }


@router.get("/{gw_id}/score/{user_id}")
def get_gameweek_score(gw_id: int, user_id: int, db: Session = Depends(get_db)):
    """Get a user's score for a specific gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    player_fixtures = db.query(PlayerFixture).filter(
        PlayerFixture.gameweek_id == gw_id,
    ).all()

    team_scores = []
    total_points = 0

    for sp in squad:
        pf = next(
            (pf for pf in player_fixtures if pf.squad_player_id == sp.id),
            None
        )

        if pf:
            score = pf.points + pf.bonus_points
            total_points += score
            team_scores.append({
                "team_id": sp.team_id,
                "team_name": sp.team.name,
                "points": score,
                "captain": sp.is_captain,
                "opponent": pf.opponent,
                "is_home": pf.was_home,
            })
        else:
            team_scores.append({
                "team_id": sp.team_id,
                "team_name": sp.team.name,
                "points": 0,
                "captain": sp.is_captain,
                "opponent": None,
                "is_home": None,
            })

    return {
        "gameweek": gw.number,
        "total_points": total_points,
        "team_scores": team_scores,
    }
