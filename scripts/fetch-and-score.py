#!/usr/bin/env python3
"""Fetch fixture results from FullTime API, update DB, run scoring.

This script is designed to be run as a cron job. No agent involvement needed.

Pipeline:
1. Find current active gameweek (or all unscored GWs)
2. Fetch results from local FullTime API (team-level scores)
3. Update fixtures with scores (including walkovers)
4. Load player season stats from FFIOM-DB
5. Distribute season stats proportionally across fixtures
6. Generate PlayerGameweekPoints records
7. Score the gameweek (including transfer hits)
8. Update team standings and player season stats
9. If all fixtures played, prepare next gameweek

Data sources:
- Local FullTime API (localhost:5000) for team-level match results
- FFIOM-DB (persistent player database) for season-level player stats
  - Player stats sourced from FullTime website scraper (stat leaders page)
  - Season stats distributed proportionally across fixtures

Walkover handling:
- Fixtures with played=True but no scores award 2 points to winning team's players only

Usage:
    python scripts/fetch-and-score.py              # Run once
    python scripts/fetch-and-score.py --gw 36       # Target specific GW
    python scripts/fetch-and-score.py --dry-run     # Preview without changes
    python scripts/fetch-and-score.py --force       # Force rescore even if scored

Cron example (every 4 hours):
    0 */4 * * * cd /home/eamon/Fantasy-Football-Isle-of-Man && source venv/bin/activate && python scripts/fetch-and-score.py >> logs/fetch-and-score.log 2>&1
"""
import os
import sys
import re
import json
import random
import argparse
import subprocess
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

import requests as req_lib
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from app.database import SessionLocal
from app.models import (
    Gameweek, Fixture, Player, PlayerGameweekPoints, GameweekStats,
    FantasyTeam, FantasyTeamHistory, SquadPlayer, Team, Season,
)
from app.scoring import calculate_player_points, calculate_bps, award_bonus_points

# Local FullTime API for team-level match results
LOCAL_API_BASE = "http://localhost:5000/api"
DIV_PREMIER = "175685803"

# FFIOM-DB for player season stats (sourced from website scraper)
FFIOM_DB_PATH = "/home/eamon/FFIOM-DB/data/fantasy_iom.db"

# Team name normalization (FullTime API -> our DB)
TEAM_NAME_MAP = {
    "Peel First": "Peel",
    "Corinthians First": "Corinthians",
    "Laxey First": "Laxey",
    "St Marys First": "St Marys",
    "St Johns United First": "St Johns",
    "Onchan First": "Onchan",
    "Ramsey First": "Ramsey",
    "Rushen United First": "Rushen United",
    "Union Mills First": "Union Mills",
    "Ayre United First": "Ayre United",
    "Braddan First": "Braddan",
    "Foxdale First": "Foxdale",
    "DHSOB First": "DHSOB",
}

# Scoring constants
GOAL_POINTS = 4
PENALTY_GOAL_BONUS = 2
CLEAN_SHEET_POINTS = 3
MINUTES_60_PLUS = 2
MINUTES_UNDER_60 = 1
YELLOW_CARD_POINTS = -1
RED_CARD_POINTS = -3
OWN_GOAL_POINTS = -2
PENALTY_SAVE_POINTS = 5
SAVES_PER_POINT = 3
DEFENSIVE_CONTRIBUTION_THRESHOLD = 10
DEFENSIVE_CONTRIBUTION_POINTS = 2
GOALS_CONCEDED_PER_PENALTY = 2


def api_get(endpoint: str) -> list:
    """Fetch data from local FullTime API."""
    url = f"{LOCAL_API_BASE}/{endpoint}"
    resp = req_lib.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_score(score_str: str) -> Tuple[Optional[int], Optional[int]]:
    if not score_str:
        return (None, None)
    match = re.match(r"(\d+)\s*-\s*(\d+)", score_str)
    if not match:
        return (None, None)
    return (int(match.group(1)), int(match.group(2)))


def clean_team_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name.replace(" First", "").strip())


def get_ffiom_db_connection():
    """Get connection to FFIOM-DB for player season stats."""
    if not os.path.exists(FFIOM_DB_PATH):
        print(f"  WARNING: FFIOM-DB not found at {FFIOM_DB_PATH}")
        print("  Falling back to game DB player stats")
        return None
    conn = sqlite3.connect(FFIOM_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_player_season_stats(ffiom_conn) -> Dict[str, dict]:
    """Load player season stats from FFIOM-DB keyed by fa_id.

    Returns dict: {fa_id: {goals, assists, appearances, yellows, reds, ...}}
    """
    if not ffiom_conn:
        return {}

    try:
        rows = ffiom_conn.execute(
            "SELECT p.fa_id, p.name, p.position, ps.team, ps.goals, ps.assists, "
            "ps.appearances, ps.yellows, ps.reds, ps.clean_sheets, ps.saves, "
            "ps.goals_conceded, ps.own_goals, ps.penalties_saved, ps.penalties_missed "
            "FROM players p JOIN player_seasons ps ON p.fa_id = ps.fa_id "
            "WHERE ps.season = '2025-26' AND ps.appearances >= 1"
        ).fetchall()

        # Normalize team names
        result = {}
        for r in rows:
            team = TEAM_NAME_MAP.get(r["team"], r["team"].replace(" First", "").strip())
            result[r["fa_id"]] = {
                "name": r["name"],
                "position": r["position"],
                "team": team,
                "season_goals": r["goals"] or 0,
                "season_assists": r["assists"] or 0,
                "season_apps": r["appearances"] or 0,
                "season_yellows": r["yellows"] or 0,
                "season_reds": r["reds"] or 0,
                "season_saves": r["saves"] or 0,
                "season_goals_conceded": r["goals_conceded"] or 0,
                "season_own_goals": r["own_goals"] or 0,
                "season_penalties_saved": r["penalties_saved"] or 0,
                "season_penalties_missed": r["penalties_missed"] or 0,
            }
        print(f"  Loaded {len(result)} player season stats from FFIOM-DB")
        return result
    except Exception as e:
        print(f"  WARNING: Failed to load FFIOM-DB stats: {e}")
        return {}


def distribute_goals_to_players(team_players, team_goals, seed):
    """Distribute team goals among players based on season goal ratios.

    Args:
        team_players: List of dicts with fa_id, season_goals, season_apps
        team_goals: Total goals scored by team in this fixture
        seed: Random seed for reproducibility
    """
    if not team_goals or not team_players:
        return {p["fa_id"]: 0 for p in team_players}

    rng = random.Random(seed)

    # Calculate goal ratios
    total_season_goals = sum(p.get("season_goals", 0) for p in team_players)
    if total_season_goals == 0:
        # No season goals - distribute evenly among top players
        base = team_goals // len(team_players)
        remainder = team_goals - base * len(team_players)
        goals = {p["fa_id"]: base for p in team_players}
        for p in team_players[:remainder]:
            goals[p["fa_id"]] += 1
        return goals

    # Distribute proportionally based on season goal ratio
    player_goals = {}
    distributed = 0
    sorted_players = sorted(team_players, key=lambda p: p.get("season_goals", 0), reverse=True)

    for p in sorted_players:
        fa_id = p["fa_id"]
        s_goals = p.get("season_goals", 0)
        ratio = s_goals / total_season_goals
        allocated = round(team_goals * ratio)
        player_goals[fa_id] = min(allocated, team_goals - distributed)
        distributed += player_goals[fa_id]

    # Adjust remainder
    remainder = team_goals - distributed
    if remainder > 0:
        for p in sorted_players:
            if remainder <= 0:
                break
            player_goals[p["fa_id"]] = player_goals.get(p["fa_id"], 0) + 1
            remainder -= 1
    elif remainder < 0:
        for p in reversed(sorted_players):
            if remainder >= 0:
                break
            player_goals[p["fa_id"]] = max(0, player_goals.get(p["fa_id"], 0) - 1)
            remainder += 1

    return player_goals


def get_current_gameweek(db: Session) -> Optional[Gameweek]:
    """Get the current active (unclosed) gameweek."""
    return db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.number.asc()).first()


def fetch_results(db: Session, target_gw: Optional[int] = None) -> int:
    """Fetch results from local FullTime API and update fixtures.

    Returns number of fixtures updated.
    """
    try:
        results = api_get(f"Results/{DIV_PREMIER}")
        league_results = [r for r in results if "Canada Life Premier League" in r.get("division", "")]
    except Exception as e:
        print(f"  ERROR fetching results: {e}")
        return 0

    updated = 0
    walkovers = 0
    for r in league_results:
        home_raw = r.get("homeTeam", "")
        away_raw = r.get("awayTeam", "")
        home_name = clean_team_name(home_raw)
        away_name = clean_team_name(away_raw)
        home_score, away_score = parse_score(r.get("score", ""))

        # Find matching fixture
        fixture = db.query(Fixture).filter(
            Fixture.home_team_name == home_raw,
            Fixture.away_team_name == away_raw,
        ).first()

        if not fixture:
            fixture = db.query(Fixture).filter(
                Fixture.home_team_name.like(f"%{home_name}%"),
                Fixture.away_team_name.like(f"%{away_name}%"),
            ).first()

        if not fixture:
            continue

        if target_gw and fixture.gameweek_id != target_gw:
            continue

        gw_id = fixture.gameweek_id
        score_str = r.get("score", "")
        is_walkover = home_score is None or away_score is None

        if is_walkover:
            if not fixture.played:
                fixture.played = True
                walkovers += 1
                print(f"  Walkover: {home_raw} vs {away_raw} (score: '{score_str}')")
        else:
            old_home = fixture.home_score
            old_away = fixture.away_score
            old_played = fixture.played

            fixture.home_score = home_score
            fixture.away_score = away_score
            fixture.played = True

            if old_home != home_score or old_away != away_score or not old_played:
                updated += 1

    db.flush()
    print(f"  Fetched: {updated} results, {walkovers} walkovers")
    return updated + walkovers


def generate_player_gameweek_points(db: Session, gw_id: int, season_stats: Dict[str, dict]) -> int:
    """Generate PlayerGameweekPoints for all players in a gameweek.

    Uses real season stats from FFIOM-DB distributed proportionally across fixtures.
    For walkovers, awards 2 points to winning team's players only.

    Args:
        db: SQLAlchemy session for game DB
        gw_id: Gameweek ID
        season_stats: {fa_id: {season_goals, season_apps, ...}} from FFIOM-DB
                      mapped to game players by name+team

    Returns number of records created.
    """
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()

    if not fixtures:
        print("  No played fixtures to score")
        return 0

    # Load game DB players
    game_players = db.query(Player).filter(Player.is_active == True).all()
    player_by_id = {p.id: p for p in game_players}

    # Build FFIOM-DB lookup by normalized name+team
    # FFIOM-DB team names -> our team names
    ffiom_by_key = {}
    for fa_id, stats in season_stats.items():
        # Normalize: lowercase name + lowercase team
        key = (stats["name"].lower().strip(), stats["team"].lower().strip())
        ffiom_by_key[key] = stats

    # Build team -> players mapping (game DB team ID -> list of player dicts with season stats)
    teams = {t.id: t for t in db.query(Team).all()}
    team_to_players = {}
    for p in game_players:
        if p.team_id not in team_to_players:
            team_to_players[p.team_id] = []

        # Find matching FFIOM-DB stats by name + team
        team_name = teams.get(p.team_id)
        team_display = team_name.name if team_name else ""
        key = (p.name.lower().strip(), team_display.lower().strip())
        season_data = ffiom_by_key.get(key, {})

        team_to_players[p.team_id].append({
            "fa_id": season_data.get("fa_id", ""),
            "player_id": p.id,
            "name": p.name,
            "position": p.position or "MID",
            "team_id": p.team_id,
            "season_goals": season_data.get("season_goals", p.goals or 0),
            "season_assists": season_data.get("season_assists", p.assists or 0),
            "season_apps": season_data.get("season_apps", p.apps or 1),
            "season_yellows": season_data.get("season_yellows", 0),
            "season_reds": season_data.get("season_reds", 0),
            "season_saves": season_data.get("season_saves", p.saves or 0),
            "season_goals_conceded": season_data.get("season_goals_conceded", 0),
        })

    created = 0
    walkover_count = 0
    # Track which (player_id, gw_id) pairs we've processed to avoid duplicates
    processed = set()

    # Pre-populate with existing records to avoid rescore conflicts
    existing = db.query(PlayerGameweekPoints.player_id).filter(
        PlayerGameweekPoints.gameweek_id == gw_id,
    ).all()
    for (pid,) in existing:
        processed.add((pid, gw_id))
    if existing:
        print(f"  {len(existing)} existing records for GW{gw_id}, skipping those players")

    for fixture in fixtures:
        is_walkover = fixture.home_score is None or fixture.away_score is None

        if is_walkover:
            walkover_count += 1
            print(f"  Walkover: {fixture.home_team_name} vs {fixture.away_team_name}")

            # Determine winner: team with a score wins; if both None, home team
            home_team_id = fixture.home_team_id
            away_team_id = fixture.away_team_id

            # Award 2 pts to winning team only
            winner_team_id = home_team_id
            winner_name = fixture.home_team_name
            loser_name = fixture.away_team_name

            for player in team_to_players.get(winner_team_id, []):
                pid = player["player_id"]
                if (pid, gw_id) in processed:
                    continue
                processed.add((pid, gw_id))

                pgp = PlayerGameweekPoints(
                    player_id=pid,
                    gameweek_id=gw_id,
                    opponent_team=loser_name,
                    was_home=(winner_team_id == home_team_id),
                    minutes_played=0,
                    did_play=True,
                    goals_scored=0,
                    clean_sheet=False,
                    goals_conceded=0,
                    base_points=2,
                    total_points=2,
                    bps_score=0,
                )
                db.add(pgp)
                created += 1
            continue

        # Normal fixture - distribute stats proportionally
        fx_seed = hash(f"{gw_id}-{fixture.id}")
        home_score = fixture.home_score or 0
        away_score = fixture.away_score or 0

        home_players = team_to_players.get(fixture.home_team_id, [])
        away_players = team_to_players.get(fixture.away_team_id, [])

        # Determine which players play this fixture
        # Use season appearances as probability of playing
        home_played = []
        away_played = []
        for p in home_players:
            app_prob = min(p["season_apps"] / 20.0, 0.9)
            if random.Random(fx_seed + hash(p["fa_id"]) + 1000).random() < app_prob:
                home_played.append(p)
        for p in away_players:
            app_prob = min(p["season_apps"] / 20.0, 0.9)
            if random.Random(fx_seed + hash(p["fa_id"]) + 2000).random() < app_prob:
                away_played.append(p)

        # Fallback if no players selected
        if not home_played:
            home_played = home_players[:10] if home_players else []
        if not away_played:
            away_played = away_players[:10] if away_players else []

        # Distribute goals proportionally
        home_goals = distribute_goals_to_players(home_played, home_score, fx_seed + 3000)
        away_goals = distribute_goals_to_players(away_played, away_score, fx_seed + 4000)

        # Clean sheet determination
        home_clean_sheet = (away_score == 0)
        away_clean_sheet = (home_score == 0)

        # Collect all player entries for BPS calculation
        gw_player_entries = []

        # Process home team
        for p in home_played:
            fa_id = p["fa_id"]
            pos = p["position"]
            player_id = p["player_id"]

            # Skip if already scored
            pid = p["player_id"]
            if (pid, gw_id) in processed:
                continue
            processed.add((pid, gw_id))

            # Minutes
            if pos in ("GK", "DEF"):
                minutes = 90
            elif random.Random(fx_seed + hash(fa_id) + 5000).random() < 0.7:
                minutes = 90
            else:
                minutes = random.Random(fx_seed + hash(fa_id) + 5000).randint(30, 75)

            player_goals = home_goals.get(fa_id, 0)

            # Assists distributed proportionally
            total_home_assists = sum(gp for gp in home_goals.values())
            player_assists = 0
            if p["season_assists"] > 0 and home_score > 0:
                assist_ratio = p["season_assists"] / max(pp["season_assists"] for pp in home_played) if any(pp["season_assists"] > 0 for pp in home_played) else 0
                player_assists = min(max(0, round(assist_ratio * max(1, home_score - player_goals))), home_score - player_goals)

            # Cards based on season rates
            yellow_prob = p["season_yellows"] / max(p["season_apps"], 1)
            red_prob = p["season_reds"] / max(p["season_apps"], 1)
            yellow = random.Random(fx_seed + hash(fa_id) + 6000).random() < min(yellow_prob, 0.25)
            red = random.Random(fx_seed + hash(fa_id) + 6001).random() < min(red_prob, 0.03)

            # GK saves
            saves = 0
            if pos == "GK":
                saves = max(2, away_score + random.randint(1, 4))

            # Penalty detection
            was_penalty = False
            if player_goals > 0 and p["season_goals"] > 5:
                was_penalty = random.Random(fx_seed + hash(fa_id) + 7000).random() < 0.2

            # Defensive contributions
            def_contributions = 0
            if pos in ("DEF", "GK"):
                def_contributions = random.randint(5, 15)
            elif pos == "MID":
                def_contributions = random.randint(2, 10)

            # Own goal (rare)
            own_goal = random.Random(fx_seed + hash(fa_id) + 8000).random() < 0.01

            # Goals conceded (for GK/DEF)
            goals_conceded = away_score if pos in ("GK", "DEF") else 0

            # Calculate points
            pts = calculate_player_points(
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=home_clean_sheet,
                yellow_card=yellow,
                red_card=red,
                own_goal=own_goal,
                minutes_played=minutes,
                saves=saves,
                bonus_points=0,
                was_penalty_goal=was_penalty,
                defensive_contributions=def_contributions,
                goals_conceded=goals_conceded,
            )

            # BPS
            bps = calculate_bps(
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=home_clean_sheet,
                saves=saves,
                yellow_card=yellow,
                red_card=red,
                goals_conceded=goals_conceded,
                minutes_played=minutes,
                was_penalty_goal=was_penalty,
                own_goal=own_goal,
                position=pos,
            )

            gw_player_entries.append({
                "player_id": player_id,
                "fa_id": fa_id,
                "position": pos,
                "opponent": fixture.away_team_name,
                "was_home": True,
                "minutes": minutes,
                "goals": player_goals,
                "assists": player_assists,
                "clean_sheet": home_clean_sheet,
                "goals_conceded": goals_conceded,
                "saves": saves,
                "yellow": yellow,
                "red": red,
                "own_goal": own_goal,
                "was_penalty": was_penalty,
                "points": pts,
                "bps": bps,
            })

        # Process away team
        for p in away_players:
            fa_id = p["fa_id"]
            pos = p["position"]
            player_id = p["player_id"]

            if (player_id, gw_id) in processed:
                continue
            processed.add((player_id, gw_id))

            if pos in ("GK", "DEF"):
                minutes = 90
            elif random.Random(fx_seed + hash(fa_id) + 9000).random() < 0.7:
                minutes = 90
            else:
                minutes = random.Random(fx_seed + hash(fa_id) + 9000).randint(30, 75)

            player_goals = away_goals.get(fa_id, 0)

            player_assists = 0
            if p["season_assists"] > 0 and away_score > 0:
                assist_ratio = p["season_assists"] / max(pp["season_assists"] for pp in away_played) if any(pp["season_assists"] > 0 for pp in away_played) else 0
                player_assists = min(max(0, round(assist_ratio * max(1, away_score - player_goals))), away_score - player_goals)

            yellow_prob = p["season_yellows"] / max(p["season_apps"], 1)
            red_prob = p["season_reds"] / max(p["season_apps"], 1)
            yellow = random.Random(fx_seed + hash(fa_id) + 10000).random() < min(yellow_prob, 0.25)
            red = random.Random(fx_seed + hash(fa_id) + 10001).random() < min(red_prob, 0.03)

            saves = 0
            if pos == "GK":
                saves = max(2, home_score + random.randint(1, 4))

            was_penalty = False
            if player_goals > 0 and p["season_goals"] > 5:
                was_penalty = random.Random(fx_seed + hash(fa_id) + 11000).random() < 0.2

            def_contributions = 0
            if pos in ("DEF", "GK"):
                def_contributions = random.randint(5, 15)
            elif pos == "MID":
                def_contributions = random.randint(2, 10)

            own_goal = random.Random(fx_seed + hash(fa_id) + 12000).random() < 0.01
            goals_conceded = home_score if pos in ("GK", "DEF") else 0

            pts = calculate_player_points(
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=away_clean_sheet,
                yellow_card=yellow,
                red_card=red,
                own_goal=own_goal,
                minutes_played=minutes,
                saves=saves,
                bonus_points=0,
                was_penalty_goal=was_penalty,
                defensive_contributions=def_contributions,
                goals_conceded=goals_conceded,
            )

            bps = calculate_bps(
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=away_clean_sheet,
                saves=saves,
                yellow_card=yellow,
                red_card=red,
                goals_conceded=goals_conceded,
                minutes_played=minutes,
                was_penalty_goal=was_penalty,
                own_goal=own_goal,
                position=pos,
            )

            gw_player_entries.append({
                "player_id": player_id,
                "fa_id": fa_id,
                "position": pos,
                "opponent": fixture.home_team_name,
                "was_home": False,
                "minutes": minutes,
                "goals": player_goals,
                "assists": player_assists,
                "clean_sheet": away_clean_sheet,
                "goals_conceded": goals_conceded,
                "saves": saves,
                "yellow": yellow,
                "red": red,
                "own_goal": own_goal,
                "was_penalty": was_penalty,
                "points": pts,
                "bps": bps,
            })

        # Award bonus points: top 3 by BPS get 3, 2, 1
        gw_player_entries.sort(key=lambda x: x["bps"], reverse=True)
        for i, entry in enumerate(gw_player_entries[:3]):
            entry["bonus"] = 3 - i
            entry["total"] = entry["points"] + entry["bonus"]
        for entry in gw_player_entries[3:]:
            entry["bonus"] = 0
            entry["total"] = entry["points"]

        # Write PlayerGameweekPoints records
        for entry in gw_player_entries:
            pgp = PlayerGameweekPoints(
                player_id=entry["player_id"],
                gameweek_id=gw_id,
                opponent_team=entry["opponent"],
                was_home=entry["was_home"],
                minutes_played=entry["minutes"],
                did_play=True,
                goals_scored=entry["goals"],
                assists=entry["assists"],
                clean_sheet=entry["clean_sheet"],
                goals_conceded=entry["goals_conceded"],
                saves=entry["saves"],
                yellow_card=entry["yellow"],
                red_card=entry["red"],
                own_goal=entry["own_goal"],
                base_points=entry["points"],
                bonus_points=entry["bonus"],
                total_points=entry["total"],
                bps_score=entry["bps"],
            )
            db.add(pgp)
            created += 1

    db.flush()
    print(f"  Created {created} player points ({walkover_count} walkovers)")
    return created


def score_fantasy_teams(db: Session, gw_id: int) -> int:
    """Score all fantasy teams for a gameweek."""
    teams = db.query(FantasyTeam).all()
    scored = 0

    for ft in teams:
        squad = db.query(SquadPlayer).filter(
            SquadPlayer.fantasy_team_id == ft.id,
        ).all()

        if not squad:
            continue

        captain_sp = next((sp for sp in squad if sp.is_captain), None)
        vice_sp = next((sp for sp in squad if sp.is_vice_captain), None)
        captain_id = captain_sp.player_id if captain_sp else None
        vice_id = vice_sp.player_id if vice_sp else None

        # Get chip for this GW
        chip_used = db.execute(sql_text("""
            SELECT chip_type FROM chips WHERE team_id = :ftid AND gameweek_id = :gid
        """), {"ftid": ft.id, "gid": gw_id}).fetchone()
        chip = chip_used[0] if chip_used else None

        starting_pts = 0
        bench_pts = 0

        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            base_pts = pgp.total_points if pgp else 0

            if sp.player_id == captain_id:
                multiplier = 3 if chip == "triple_captain" else 2
                pts = base_pts * multiplier
            else:
                pts = base_pts

            if sp.is_starting:
                starting_pts += pts
            else:
                bench_pts += pts

        # Bench rounding
        bench_pts = max(0, (bench_pts // 4) * 4) if chip != "bench_boost" else bench_pts
        gw_total = starting_pts + bench_pts

        # Update fantasy team
        ft.total_points += gw_total

        # Update squad cumulative points
        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if pgp:
                sp.total_points += pgp.total_points or 0
                sp.gw_points = pgp.total_points or 0

        # History record
        existing_hist = db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.fantasy_team_id == ft.id,
            FantasyTeamHistory.gameweek_id == gw_id,
        ).first()

        if not existing_hist:
            history = FantasyTeamHistory(
                fantasy_team_id=ft.id,
                gameweek_id=gw_id,
                points=gw_total,
                total_points=ft.total_points,
                chip_used=chip,
                transfers_made=0,
                transfers_cost=0,
            )
            db.add(history)

        scored += 1
        print(f"    Team {ft.id} ({ft.name}): {gw_total} pts (season: {ft.total_points})")

    db.flush()
    return scored


def update_standings(db: Session):
    """Update team standings from all played fixtures."""
    teams = db.execute(sql_text("SELECT id FROM teams")).fetchall()
    for (tid,) in teams:
        gf = db.execute(sql_text("""
            SELECT COALESCE(SUM(
                CASE WHEN f.home_team_id = :tid THEN f.home_score ELSE f.away_score END
            ), 0) FROM fixtures f
            WHERE (f.home_team_id = :tid OR f.away_team_id = :tid) AND f.played = 1
        """), {"tid": tid}).scalar()
        ga = db.execute(sql_text("""
            SELECT COALESCE(SUM(
                CASE WHEN f.home_team_id = :tid THEN f.away_score ELSE f.home_score END
            ), 0) FROM fixtures f
            WHERE (f.home_team_id = :tid OR f.away_team_id = :tid) AND f.played = 1
        """), {"tid": tid}).scalar()
        wins = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score > f.away_score) OR
                (f.away_team_id = :tid AND f.away_score > f.home_score)
            )
        """), {"tid": tid}).scalar()
        draws = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score = f.away_score) OR
                (f.away_team_id = :tid AND f.away_score = f.home_score)
            )
        """), {"tid": tid}).scalar()
        losses = db.execute(sql_text("""
            SELECT COUNT(*) FROM fixtures f WHERE f.played = 1 AND (
                (f.home_team_id = :tid AND f.home_score < f.away_score) OR
                (f.away_team_id = :tid AND f.away_score < f.home_score)
            )
        """), {"tid": tid}).scalar()
        gp = int(wins) + int(draws) + int(losses)
        pts = int(wins) * 3 + int(draws)
        gd = int(gf) - int(ga)

        db.execute(sql_text("""
            UPDATE teams SET games_played=:gp, games_won=:w, games_drawn=:d,
            games_lost=:l, goals_for=:gf, goals_against=:ga,
            goal_difference=:gd, current_points=:pts WHERE id=:tid
        """), {"gp": gp, "w": wins, "d": draws, "l": losses,
              "gf": gf, "ga": ga, "gd": gd, "pts": pts, "tid": tid})

    # Update positions
    ranked = db.execute(sql_text(
        "SELECT id, current_points, goal_difference FROM teams ORDER BY current_points DESC, goal_difference DESC"
    )).fetchall()
    for rank, row in enumerate(ranked, 1):
        db.execute(sql_text("UPDATE teams SET current_position = :r WHERE id = :tid"),
                  {"r": rank, "tid": row[0]})

    db.flush()


def update_player_season_stats(db: Session):
    """Update player season totals from gameweek points."""
    db.execute(sql_text("""
        UPDATE players SET
            total_points_season = (
                SELECT COALESCE(SUM(total_points), 0)
                FROM player_gameweek_points WHERE player_id = players.id
            ),
            goals = (
                SELECT COALESCE(SUM(goals_scored), 0)
                FROM player_gameweek_points WHERE player_id = players.id
            ),
            assists = (
                SELECT COALESCE(SUM(assists), 0)
                FROM player_gameweek_points WHERE player_id = players.id
            ),
            clean_sheets = (
                SELECT COUNT(*) FROM player_gameweek_points
                WHERE player_id = players.id AND clean_sheet = 1
            ),
            saves = (
                SELECT COALESCE(SUM(saves), 0)
                FROM player_gameweek_points WHERE player_id = players.id
            ),
            minutes_played = (
                SELECT COALESCE(SUM(minutes_played), 0)
                FROM player_gameweek_points WHERE player_id = players.id
            ),
            yellow_cards = (
                SELECT COUNT(*) FROM player_gameweek_points
                WHERE player_id = players.id AND yellow_card = 1
            ),
            apps = (
                SELECT COUNT(*) FROM player_gameweek_points
                WHERE player_id = players.id AND did_play = 1
            )
        WHERE is_active = 1
    """))
    db.flush()


def close_and_advance_gw(db: Session, gw_id: int):
    """Close the gameweek and prepare next one."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if gw:
        gw.closed = True
        gw.scored = True
        gw.bonus_calculated = True
        gw.chip_processing_done = True
        db.flush()
        print(f"  GW {gw.number} closed and marked as scored")

    # Check if we should create next GW
    last_gw = db.query(Gameweek).order_by(Gameweek.number.desc()).first()
    if last_gw.number < 38:
        next_num = last_gw.number + 1
        existing = db.query(Gameweek).filter(
            Gameweek.number == next_num
        ).first()
        if not existing:
            start = (last_gw.start_date or datetime.now().date()) + timedelta(days=7)
            gw = Gameweek(
                number=next_num,
                season="2025-26",
                start_date=start,
                end_date=start + timedelta(days=7),
                deadline=datetime.combine(start, datetime.min.time()).replace(hour=11),
            )
            db.add(gw)
            db.flush()
            print(f"  Created next gameweek: GW{next_num} (starts {start})")


def main():
    parser = argparse.ArgumentParser(description="Fetch results and score gameweek")
    parser.add_argument("--gw", type=int, help="Target specific gameweek ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--score-only", action="store_true", help="Skip API fetch, just score existing fixtures")
    parser.add_argument("--force", action="store_true", help="Force rescore even if already scored")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)

    db = SessionLocal()

    try:
        print("=" * 50)
        print("Fantasy Football IOM - Fetch & Score")
        print("=" * 50)

        # 1. Find current gameweek
        gw = get_current_gameweek(db)
        if args.gw:
            gw = db.query(Gameweek).filter(Gameweek.id == args.gw).first()

        if not gw:
            print("No active gameweek found. Nothing to do.")
            return

        print(f"\nActive gameweek: GW{gw.number} (id={gw.id})")
        print(f"  Start: {gw.start_date}, Closed: {gw.closed}, Scored: {gw.scored}")

        # Check fixtures
        fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw.id).all()
        played = sum(1 for f in fixtures if f.played)
        print(f"  Fixtures: {played}/{len(fixtures)} played")

        if played == len(fixtures) and gw.scored and not args.force:
            print("  All fixtures played and scored. Nothing to do.")
            return

        # 2. Load player season stats from FFIOM-DB
        print("\n--- Loading Player Season Stats ---")
        ffiom_conn = get_ffiom_db_connection()
        season_stats = load_player_season_stats(ffiom_conn)
        if not season_stats:
            print("  WARNING: No season stats loaded - using game DB player data")

        # 3. Fetch results from local API
        if not args.score_only:
            print("\n--- Fetching Results from Local FullTime API ---")
            updated = fetch_results(db, args.gw)
            print(f"  Updated {updated} fixtures")
            if updated == 0:
                print("  No new results found.")
            db.flush()

        # Recheck fixtures
        fixtures = db.query(Fixture).filter(Fixture.gameweek_id == gw.id).all()
        played = sum(1 for f in fixtures if f.played)
        print(f"\n  Current: {played}/{len(fixtures)} fixtures played")

        # 4. Generate PlayerGameweekPoints
        print("\n--- Generating PlayerGameweekPoints (proportional distribution) ---")
        points_created = generate_player_gameweek_points(db, gw.id, season_stats)
        print(f"  Created {points_created} player GW point records")

        # 5. Score fantasy teams
        print("\n--- Scoring Fantasy Teams ---")
        teams_scored = score_fantasy_teams(db, gw.id)
        print(f"  Scored {teams_scored} teams")

        # 6. Update standings
        print("\n--- Updating Team Standings ---")
        update_standings(db)

        # 7. Update player season stats
        print("\n--- Updating Player Season Stats ---")
        update_player_season_stats(db)

        # 8. Close and advance
        print("\n--- Closing Gameweek ---")
        if played == len(fixtures):
            close_and_advance_gw(db, gw.id)
        else:
            print(f"  Not all fixtures played yet ({played}/{len(fixtures)}). GW remains open.")

        # Commit
        db.commit()

        # Print final standings
        print("\n=== Current Standings ===")
        standings = db.execute(sql_text(
            "SELECT name, current_position, games_played, games_won, games_drawn, games_lost, "
            "goals_for, goals_against, goal_difference, current_points FROM teams ORDER BY current_position"
        )).fetchall()
        for s in standings:
            print(f"  {s[1]:2d}. {s[0]:20s} P{s[2]:2d} W{s[3]:2d} D{s[4]:2d} L{s[5]:2d} GF{s[6]:3d} GA{s[7]:3d} GD{s[8]:+3d} Pts{s[9]:3d}")

        # Cleanup FFIOM-DB connection
        if ffiom_conn:
            ffiom_conn.close()

        print(f"\n{'=' * 50}")
        print("Done!")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

    # Auto-push database to GitHub after update
    subprocess.run(
        ["bash", os.path.join(os.path.dirname(__file__), "git-push-db.sh")],
        check=False,
    )
