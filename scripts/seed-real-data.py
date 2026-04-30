#!/usr/bin/env python3
"""Seed the Fantasy Football IOM database with real data from FullTime API.

Usage:
    python scripts/seed-real-data.py --clear    # Clear existing data first
    python scripts/seed-real-data.py             # Seed data
"""
import os
import sys
import re
import json
import random
import argparse
import urllib3
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "sqlite:///./data/fantasy_iom.db"

from sqlalchemy.orm import Session
from app.database import engine, SessionLocal, Base, init_db
from app.models import (
    League, Division, Team, Player, Gameweek, Fixture,
    User, FantasyTeam, SquadPlayer, Season, PlayerPriceHistory,
    GameweekStats, PlayerGameweekPoints,
)
from app.utils.passwords import hash_password

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = "https://faapi.jwhsolutions.co.uk/api"
DIV_PREMIER = "175685803"

# Team name normalization
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

def api_get(endpoint: str) -> list:
    """Make an API request."""
    import requests
    url = f"{API_BASE}/{endpoint}"
    resp = requests.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    return resp.json()

def parse_score(score_str: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse '3 - 2 (HT 0-1)' -> (3, 2)."""
    if not score_str:
        return (None, None)
    match = re.match(r"(\d+)\s*-\s*(\d+)", score_str)
    if not match:
        return (None, None)
    return (int(match.group(1)), int(match.group(2)))

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse '28/04/26 19:00' -> datetime."""
    if not date_str:
        return None
    return datetime.strptime(date_str, "%d/%m/%y %H:%M")

def clean_team_name(name: str) -> str:
    """Normalize team name."""
    return TEAM_NAME_MAP.get(name, name.replace(" First", "").strip())

def get_all_results() -> list:
    """Get all results for the Premier League, filtering to only league matches."""
    all_results = api_get(f"Results/{DIV_PREMIER}")
    # Filter to only Canada Life Premier League matches
    league_results = [r for r in all_results if "Canada Life Premier League" in r.get("division", "")]
    return league_results

def get_fixtures() -> list:
    """Get upcoming fixtures for the Premier League."""
    all_fixtures = api_get(f"Fixtures/{DIV_PREMIER}")
    # Filter to only Canada Life Premier League matches
    league_fixtures = [f for f in all_fixtures if "Canada Life Premier League" in f.get("competition", "")]
    return league_fixtures

def get_league_table() -> list:
    """Get the Premier League table."""
    return api_get(f"League/{DIV_PREMIER}")

def assign_positions_to_players(players_for_team: list, team_name: str) -> list:
    """Assign positions to players based on goals and appearances data.

    Each team needs: 2 GK, 5 DEF, 5 MID, 3 FWD (total 15)
    """
    # Sort by goals desc, then by appearances desc
    sorted_players = sorted(players_for_team, key=lambda p: (p.get("goals", 0), p.get("apps", 0)), reverse=True)

    # Goalkeepers: 2 players with 0 goals and highest appearances
    gk_candidates = sorted(
        [p for p in sorted_players if p.get("goals", 0) == 0],
        key=lambda p: p.get("apps", 0), reverse=True
    )[:2]
    for p in gk_candidates:
        p["position"] = "GK"

    remaining = [p for p in sorted_players if p not in gk_candidates]

    # Forwards: top 3 scorers
    forwards = remaining[:3]
    for p in forwards:
        p["position"] = "FWD"

    remaining = [p for p in remaining if p not in forwards]

    # Midfielders: next 5 with most goals/assists
    midfielders = remaining[:5]
    for p in midfielders:
        p["position"] = "MID"

    remaining = [p for p in remaining if p not in midfielders]

    # Defenders: everyone else
    defenders = remaining[:5]
    for p in defenders:
        p["position"] = "DEF"

    # Combine all assigned players (up to 15)
    assigned = gk_candidates + forwards + midfielders + defenders
    return assigned[:15]

def estimate_price(goals: int, apps: int, assists: int, position: str) -> float:
    """Estimate FPL-style player price based on stats."""
    base = 4.5
    base += goals * 0.4
    base += assists * 0.3
    base += (apps / 20.0) * 0.5

    # Position adjustments
    if position == "GK":
        base += 0.2
    elif position == "FWD":
        base += 0.3
    elif position == "MID":
        base += 0.2

    return max(4.0, min(10.0, round(base, 1)))

def main():
    parser = argparse.ArgumentParser(description="Seed Fantasy Football IOM with real data")
    parser.add_argument("--clear", action="store_true", help="Clear existing data first")
    args = parser.parse_args()

    db: Session = SessionLocal()

    if args.clear:
        print("Clearing existing data...")
        # Drop and recreate all tables
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Data cleared.")

    # ---- Fetch real data ----
    print("\n=== Fetching data from FullTime API ===")

    # 1. League table
    table = get_league_table()
    print(f"League table: {len(table)} teams")

    # 2. Results
    results = get_all_results()
    print(f"Results: {len(results)} matches")

    # 3. Upcoming fixtures
    fixtures = get_fixtures()
    print(f"Upcoming fixtures: {len(fixtures)} matches")

    # 4. Team form data
    teams_form = {}
    for team_row in table:
        team_name = team_row["teamName"]
        try:
            form = api_get(f"Results/{DIV_PREMIER}/form?teamName={team_name}")
            if isinstance(form, str):
                form = []
            # Filter to league matches only
            league_form = [f for f in form if isinstance(f, dict) and "Canada Life Premier League" in f.get("division", "")]
            teams_form[clean_team_name(team_name)] = league_form[:5]
        except Exception as e:
            print(f"  Warning: Could not get form for {team_name}: {e}")
            teams_form[clean_team_name(team_name)] = []

    # ---- Seed League & Division ----
    print("\n=== Seeding League & Division ===")
    league = db.query(League).filter(League.name == "IOM Senior League").first()
    if not league:
        league = League(ft_id="9057188", name="IOM Senior League")
        db.add(league)
        db.flush()

    division = db.query(Division).filter(Division.name == "Canada Life Premier League").first()
    if not division:
        division = Division(ft_id=DIV_PREMIER, name="Canada Life Premier League", league_id=league.id)
        db.add(division)
        db.flush()

    # ---- Seed Teams ----
    print("\n=== Seeding Teams ===")
    team_map = {}  # Clean name -> Team model
    for row in table:
        raw_name = row["teamName"]
        clean = clean_team_name(raw_name)

        team = db.query(Team).filter(Team.name == clean).first()
        if not team:
            # Calculate strength ratings from league performance
            pos = row["position"]
            games = row["gamesPlayed"]
            goals_diff = row["goalDifference"]
            pts = row["points"]

            # Strength based on league position (1-5 scale)
            strength_defense = 5 if pos <= 3 else (4 if pos <= 6 else (3 if pos <= 9 else (2 if pos <= 11 else 1)))
            strength_attack = 5 if goals_diff > 30 else (4 if goals_diff > 10 else (3 if goals_diff > 0 else (2 if goals_diff > -10 else 1)))
            strength_home = 5 if pos <= 2 else (4 if pos <= 4 else (3 if pos <= 7 else 2))
            strength_away = 4 if pos <= 3 else (3 if pos <= 6 else (2 if pos <= 9 else 1))

            team = Team(
                name=clean,
                short_name=clean[:3].upper(),
                code=clean[:3].upper(),
                division_id=division.id,
                current_position=pos,
                strength_attack=strength_attack,
                strength_defense=strength_defense,
                strength_home=strength_home,
                strength_away=strength_away,
            )
            db.add(team)
        team_map[clean] = team
    db.flush()
    print(f"Seeded {len(team_map)} teams")

    # ---- Create Season ----
    season = db.query(Season).filter(Season.name == "2025-26").first()
    if not season:
        season = Season(name="2025-26", total_gameweeks=24, started=True)
        db.add(season)
        db.flush()

    # ---- Parse Results into Gameweeks ----
    print("\n=== Creating Gameweeks from Results ===")

    # Group results by date to identify gameweeks
    results_by_date = {}
    for r in results:
        dt = parse_date(r.get("fixtureDateTime", ""))
        if dt:
            date_key = dt.date()
            if date_key not in results_by_date:
                results_by_date[date_key] = []
            results_by_date[date_key].append(r)

    # Sort dates and create gameweeks
    sorted_dates = sorted(results_by_date.keys())
    print(f"Found {len(sorted_dates)} unique match dates")

    # Group dates into gameweeks (matches within 2 days of each other = same GW)
    gameweek_dates = []
    current_gw_dates = []
    for d in sorted_dates:
        if not current_gw_dates or (d - current_gw_dates[-1]).days <= 2:
            current_gw_dates.append(d)
        else:
            gameweek_dates.append(current_gw_dates)
            current_gw_dates = [d]
    if current_gw_dates:
        gameweek_dates.append(current_gw_dates)

    print(f"Grouped into {len(gameweek_dates)} gameweeks")

    # Create gameweeks and fixtures
    for gw_num, dates in enumerate(gameweek_dates, 1):
        start_date = dates[0]
        end_date = dates[-1]
        deadline = datetime.combine(start_date - timedelta(days=1), datetime.min.time())
        deadline = deadline.replace(hour=11)

        # Check if gameweek already exists
        gw = db.query(Gameweek).filter(
            Gameweek.number == gw_num,
            Gameweek.season == "2025-26"
        ).first()

        if not gw:
            gw = Gameweek(
                number=gw_num,
                season="2025-26",
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                closed=True,  # All past gameweeks are closed
                scored=True,   # All past gameweeks are scored
            )
            db.add(gw)
            db.flush()

        # Create fixtures for this gameweek
        for d in dates:
            for r in results_by_date[d]:
                home_raw = r["homeTeam"]
                away_raw = r["awayTeam"]
                home_name = clean_team_name(home_raw)
                away_name = clean_team_name(away_raw)

                home_score, away_score = parse_score(r.get("score", ""))
                home_team = team_map.get(home_name)
                away_team = team_map.get(away_name)

                # Skip if we don't have both teams
                if not home_team or not away_team:
                    continue

                # Check if fixture already exists
                existing = db.query(Fixture).filter(
                    Fixture.gameweek_id == gw.id,
                    Fixture.home_team_name == home_raw,
                    Fixture.away_team_name == away_raw,
                ).first()

                if not existing:
                    # Fixture difficulty based on opponent strength
                    home_difficulty = away_team.strength_attack if away_team else 3
                    away_difficulty = home_team.strength_defense if home_team else 3

                    fixture = Fixture(
                        gameweek_id=gw.id,
                        date=parse_date(r.get("fixtureDateTime", "")) or datetime.now(),
                        home_team_name=home_raw,
                        away_team_name=away_raw,
                        home_team_id=home_team.id,
                        away_team_id=away_team.id,
                        home_difficulty=home_difficulty,
                        away_difficulty=away_difficulty,
                        played=True,
                        home_score=home_score,
                        away_score=away_score,
                    )
                    db.add(fixture)

    db.flush()

    # Add upcoming fixtures to a future gameweek
    if fixtures:
        # Create a new open gameweek for upcoming fixtures
        last_gw = db.query(Gameweek).filter(
            Gameweek.season == "2025-26"
        ).order_by(Gameweek.number.desc()).first()
        next_gw_num = (last_gw.number if last_gw else 0) + 1

        # Group upcoming fixtures by date
        upcoming_by_date = {}
        for f in fixtures:
            dt = parse_date(f.get("fixtureDateTime", ""))
            if dt:
                date_key = dt.date()
                if date_key not in upcoming_by_date:
                    upcoming_by_date[date_key] = []
                upcoming_by_date[date_key].append(f)

        for d in sorted(upcoming_by_date.keys()):
            gw = db.query(Gameweek).filter(
                Gameweek.number == next_gw_num,
                Gameweek.season == "2025-26"
            ).first()

            if not gw:
                gw = Gameweek(
                    number=next_gw_num,
                    season="2025-26",
                    start_date=d,
                    end_date=d + timedelta(days=7),
                    deadline=datetime.combine(d, datetime.min.time()).replace(hour=11),
                    closed=False,
                    scored=False,
                )
                db.add(gw)
                db.flush()

            for f in upcoming_by_date[d]:
                home_raw = f["homeTeam"]
                away_raw = f["awayTeam"]
                home_name = clean_team_name(home_raw)
                away_name = clean_team_name(away_raw)
                home_team = team_map.get(home_name)
                away_team = team_map.get(away_name)

                if not home_team or not away_team:
                    continue

                existing = db.query(Fixture).filter(
                    Fixture.gameweek_id == gw.id,
                    Fixture.home_team_name == home_raw,
                    Fixture.away_team_name == away_raw,
                ).first()

                if not existing:
                    fixture = Fixture(
                        gameweek_id=gw.id,
                        date=parse_date(f.get("fixtureDateTime", "")) or datetime.now(),
                        home_team_name=home_raw,
                        away_team_name=away_raw,
                        home_team_id=home_team.id,
                        away_team_id=away_team.id,
                        home_difficulty=away_team.strength_attack if away_team else 3,
                        away_difficulty=home_team.strength_defense if home_team else 3,
                        played=False,
                    )
                    db.add(fixture)

            next_gw_num += 1

    db.flush()
    print(f"Created {db.query(Gameweek).count()} gameweeks")
    print(f"Total fixtures: {db.query(Fixture).count()}")

    # ---- Create Players from Real Data ----
    print("\n=== Loading Real Players from Cache ===")

    # Load player data from cached FullTime API scrape
    real_players_file = "data/real_players.json"
    stats_cache_file = "data/player_stats_cache.json"

    player_data = []
    if os.path.exists(real_players_file):
        with open(real_players_file) as f:
            raw = json.load(f)
            player_data = raw.get("players", raw) if isinstance(raw, dict) else raw
        print(f"Loaded {len(player_data)} players from {real_players_file}")

    # Load stats cache for additional data
    stats_cache = {}
    if os.path.exists(stats_cache_file):
        with open(stats_cache_file) as f:
            stats_cache = json.load(f)
        print(f"Loaded {len(stats_cache)} stats entries from {stats_cache_file}")

    # Group players by team
    players_by_team = {}
    for p in player_data:
        name = p.get("name", "").strip()
        person_id = p.get("personID", "")
        if not name:
            continue

        # Get team from stats cache
        team_raw = None
        if person_id in stats_cache:
            team_raw = stats_cache[person_id].get("team", "")

        # If no team in cache, try to find it from existing DB players
        if not team_raw:
            existing = db.query(Player).filter(
                Player.name == name, Player.is_active == True
            ).first()
            if existing and existing.team:
                team_raw = existing.team.name

        team = clean_team_name(team_raw) if team_raw else None

        if team and team in team_map:
            players_by_team.setdefault(team, []).append({
                "name": name,
                "personID": person_id,
                "team": team,
            })

    # Assign positions and create players
    total_players = 0
    for team_name, players_list in players_by_team.items():
        team = team_map[team_name]
        existing_count = db.query(Player).filter(Player.team_id == team.id).count()

        if existing_count >= 15:
            print(f"  {team_name}: already has {existing_count} players, skipping")
            continue

        # Get form data for this team
        form_matches = teams_form.get(team_name, [])
        team_goals = sum(
            parse_score(r.get("score", ""))[0] if clean_team_name(r.get("homeTeam", "")) == team_name
            else parse_score(r.get("score", ""))[1]
            for r in form_matches
            if parse_score(r.get("score", ""))[0] is not None
        )
        team_games = sum(1 for r in results if clean_team_name(r.get("homeTeam", "")) == team_name or clean_team_name(r.get("awayTeam", "")) == team_name)

        # Assign positions using the position assignment function
        players_with_positions = assign_positions_to_players(
            [{"name": p["name"], "personID": p["personID"], "goals": 0, "apps": 0} for p in players_list],
            team_name
        )

        for p in players_with_positions:
            name = p["name"]
            person_id = p.get("personID", "")
            pos = p.get("position", "MID")

            # Get stats from cache
            goals = 0
            apps = 0
            yellows = 0
            reds = 0
            if person_id in stats_cache:
                goals = stats_cache[person_id].get("goals", 0)
                apps = stats_cache[person_id].get("appearances", 0)
                yellows = stats_cache[person_id].get("yellows", 0)
                reds = stats_cache[person_id].get("reds", 0)

            # Skip players with too few appearances
            if apps < 3:
                continue

            price = estimate_price(goals, apps, 0, pos)

            player = Player(
                name=name,
                web_name=name.lower().replace(" ", "_").replace("'", ""),
                team_id=team.id,
                position=pos,
                goals=goals,
                assists=0,
                apps=apps,
                yellow_cards=yellows,
                red_cards=reds,
                is_active=True,
                total_points_season=0,
                price=price,
            )
            db.add(player)
            total_players += 1

    db.flush()
    print(f"Created {total_players} real players")

    # ---- Identify and fix Goalkeepers ----
    print("\n=== Identifying Goalkeepers ===")
    # Players with 24+ apps, 0 goals, 0 assists are almost certainly GKs
    gk_candidates = db.query(Player).filter(
        Player.is_active == True,
        Player.goals == 0,
        Player.assists == 0,
        Player.apps >= 24,
        Player.position != "GK"
    ).all()

    # Cross-reference with stats cache for additional GK identification
    gk_names_from_cache = set()
    for pid, stats in stats_cache.items():
        if stats.get("appearances", 0) >= 24 and stats.get("goals", 0) == 0 and stats.get("assists", 0) == 0:
            gk_names_from_cache.add(stats.get("name", "").lower())

    for p in gk_candidates:
        if p.name.lower() in gk_names_from_cache:
            p.position = "GK"
    db.commit()
    print(f"Total GKs: {db.query(Player).filter(Player.position == 'GK').count()}")

    # ---- Create Sample User ----
    print("\n=== Creating Sample User ===")
    existing_user = db.query(User).filter(User.username == "test_manager").first()
    if not existing_user:
        user = User(
            username="test_manager",
            email="test@example.com",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.flush()
    else:
        user = existing_user

    # Create fantasy team for user
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user.id).first()
    if not ft:
        ft = FantasyTeam(
            user_id=user.id,
            name="Test FC",
            season="2025-26",
            budget=60.0,
            budget_remaining=60.0,
            free_transfers=1,
            free_transfers_next_gw=1,
        )
        db.add(ft)
        db.flush()

        # Pick 13 players within budget (no position restrictions)
        all_players = db.query(Player).filter(Player.is_active == True).order_by(
            Player.price.desc()
        ).all()

        budget = 60.0
        squad_players = []
        used_names = set()

        # Shuffle and pick unique players (no duplicate names)
        random.shuffle(all_players)
        for player in all_players:
            if len(squad_players) >= 13:
                break
            if player.name in used_names:
                continue  # Skip duplicate names
            if budget < player.price:
                continue

            budget -= player.price
            used_names.add(player.name)
            squad_players.append(player)

        # Assign positions
        slot = 1
        captain_set = False
        vice_captain_set = False

        # Sort: GK first, then DEF, MID, FWD
        pos_order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
        squad_players.sort(key=lambda p: pos_order.get(p.position, 99))

        for player in squad_players:
            is_captain = not captain_set and slot <= 11
            is_vice_captain = not vice_captain_set and slot <= 11 and not is_captain
            sp = SquadPlayer(
                fantasy_team_id=ft.id,
                player_id=player.id,
                position_slot=slot,
                is_starting=slot <= 11,
                is_captain=is_captain,
                is_vice_captain=is_vice_captain,
                purchase_price=player.price,
                selling_price=player.price,
                bench_priority=slot if slot > 11 else 99,
            )
            if is_captain:
                captain_set = True
            elif is_vice_captain:
                vice_captain_set = True

            db.add(sp)
            slot += 1

        ft.budget_remaining = budget

    db.commit()
    print(f"User: {user.username}, Fantasy Team: {ft.name}")

    # ---- Summary ----
    print("\n=== Database Summary ===")
    print(f"Leagues: {db.query(League).count()}")
    print(f"Divisions: {db.query(Division).count()}")
    print(f"Teams: {db.query(Team).count()}")
    print(f"Players: {db.query(Player).count()}")
    print(f"Gameweeks: {db.query(Gameweek).count()}")
    print(f"Fixtures: {db.query(Fixture).count()}")
    print(f"Users: {db.query(User).count()}")
    print(f"Fantasy Teams: {db.query(FantasyTeam).count()}")

    db.close()
    print("\nDone! Login: test_manager / password123")

if __name__ == "__main__":
    main()
