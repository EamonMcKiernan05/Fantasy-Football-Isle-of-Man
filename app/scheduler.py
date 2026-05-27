"""APScheduler tasks for Fantasy Football Isle of Man.

FPL Schedule:
- Team deadline: Saturday 11:00 AM (no more transfers after this)
- Bonus points calculated: Saturday 9:00 PM
- Gameweek scoring: After all matches complete
- Transfer rollover: When new gameweek starts
- Player price updates: After gameweek scoring
- Per-fixture result sync: 4 hours after kickoff, retry hourly x3
"""
import json
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta

from app.database import SessionLocal, Base, engine, init_binds, get_bound_db
from app.models import (
    Gameweek, Season, Player, PlayerGameweekPoints,
    FantasyTeam, SquadPlayer, FantasyTeamHistory, Team, Fixture,
)
from app import scoring

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# Per-fixture retry config
MAX_RESULT_RETRIES = 3
INITIAL_CHECK_DELAY_HOURS = 4
RETRY_INTERVAL_HOURS = 1


def start_scheduler():
    """Start the background scheduler with FPL-compatible timing."""
    logger.info("Starting scheduler...")

    # Saturday 11:00 AM - Team deadline
    scheduler.add_job(
        apply_deadline,
        CronTrigger(day_of_week="sat", hour=11, minute=0),
        id="apply_deadline",
        name="Apply transfer deadline",
        replace_existing=True,
    )

    # Sunday 11:00 PM - Score gameweek and process transfers
    scheduler.add_job(
        process_gameweek_end,
        CronTrigger(day_of_week="sun", hour=23, minute=0),
        id="process_gw_end",
        name="Process gameweek end",
        replace_existing=True,
    )

    # Daily at 3 AM - Bulk sync fixtures from FullTime API
    # This picks up new seasons, schedule changes, and kickoffs
    scheduler.add_job(
        sync_fixtures,
        CronTrigger(hour=3, minute=0),
        id="sync_fixtures_bulk",
        name="Sync fixtures (bulk)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Shutdown the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down.")


def schedule_per_fixture_sync(db):
    """Schedule per-fixture result sync jobs for upcoming unplayed fixtures.

    For each unplayed fixture with a kickoff_time, schedule a sync job
    at kickoff_time + INITIAL_CHECK_DELAY_HOURS.
    Fixtures without kickoff_time get a default 4-hour delay from the date.
    """
    unplayed = db.query(Fixture).filter(
        Fixture.played == False,
        Fixture.result_check_attempts < MAX_RESULT_RETRIES,
    ).all()

    scheduled = 0
    for fx in unplayed:
        job_id = f"fixture_result_{fx.id}"

        # Skip if already scheduled
        existing = scheduler.get_job(job_id)
        if existing:
            continue

        # Calculate next check time
        if fx.kickoff_time and fx.date:
            kickoff = datetime.combine(fx.date, fx.kickoff_time)
        else:
            # Default: match date at 3 PM
            kickoff = datetime.combine(fx.date, datetime.strptime("15:00", "%H:%M").time())

        # If kickoff is in the past, check immediately (was missed)
        if kickoff < datetime.now():
            check_time = datetime.now() + timedelta(minutes=5)
        else:
            check_time = kickoff + timedelta(hours=INITIAL_CHECK_DELAY_HOURS)

        scheduler.add_job(
            sync_single_fixture,
            DateTrigger(run_date=check_time),
            id=job_id,
            name=f"Sync result: {fx.home_team_name} vs {fx.away_team_name}",
            args=[fx.id],
            replace_existing=True,
        )
        scheduled += 1

    if scheduled:
        logger.info(f"Scheduled {scheduled} per-fixture result sync jobs")


def sync_single_fixture(fixture_id: int):
    """Sync results for a single fixture.

    Fetches results from FullTime API for the division this fixture belongs to.
    If results are available, updates the fixture and triggers scoring.
    If not, schedules a retry (up to MAX_RESULT_RETRIES times).
    """
    logger.info(f"Checking result for fixture {fixture_id}...")
    init_binds()
    from app.database import BoundSessionLocal
    if BoundSessionLocal is None:
        logger.error("Database not initialized")
        return
    db = BoundSessionLocal()
    try:
        fixture = db.query(Fixture).filter(Fixture.id == fixture_id).first()
        if not fixture or fixture.played:
            logger.info(f"Fixture {fixture_id}: already played or not found, skipping")
            return

        # Fetch results for this fixture's division
        from app.api_client import FullTimeAPIClient
        client = FullTimeAPIClient()

        # Determine division ID from division_name
        div_id = None
        for div_name, did in FullTimeAPIClient.DIVISIONS.items():
            if fixture.competition and div_name in fixture.competition.lower():
                div_id = did
                break
            if fixture.division_name and div_name in fixture.division_name.lower():
                div_id = did
                break

        if not div_id:
            # Try all divisions
            for div_name, did in FullTimeAPIClient.DIVISIONS.items():
                _update_fixture_from_results(db, fixture, did, client)
                fixture = db.query(Fixture).filter(Fixture.id == fixture_id).first()
                if fixture and fixture.played:
                    break
        else:
            _update_fixture_from_results(db, fixture, div_id, client)
            fixture = db.query(Fixture).filter(Fixture.id == fixture_id).first()

        if fixture and fixture.played:
            logger.info(
                f"Fixture {fixture_id}: {fixture.home_team_name} "
                f"{fixture.home_score}-{fixture.away_score} {fixture.away_team_name}"
            )
            db.commit()
            # Trigger scoring for affected gameweek
            _score_updated_gameweek(db, fixture.gameweek_id)
        else:
            fixture.result_check_attempts += 1
            db.commit()
            if fixture.result_check_attempts < MAX_RESULT_RETRIES:
                retry_in = timedelta(hours=RETRY_INTERVAL_HOURS)
                retry_time = datetime.now() + retry_in
                job_id = f"fixture_result_{fixture_id}"
                scheduler.add_job(
                    sync_single_fixture,
                    DateTrigger(run_date=retry_time),
                    id=job_id,
                    name=f"Retry result: {fixture.home_team_name} vs {fixture.away_team_name} "
                         f"(attempt {fixture.result_check_attempts + 1})",
                    args=[fixture_id],
                    replace_existing=True,
                )
                logger.info(
                    f"Fixture {fixture_id}: no result yet (attempt {fixture.result_check_attempts}/{MAX_RESULT_RETRIES}), "
                    f"retrying at {retry_time}"
                )
            else:
                logger.warning(
                    f"Fixture {fixture_id}: exhausted {MAX_RESULT_RETRIES} attempts, giving up"
                )

    except Exception as e:
        logger.error(f"Fixture {fixture_id} sync error: {e}")
        db.rollback()
    finally:
        db.close()


def _update_fixture_from_results(db, fixture, div_id, client):
    """Check if a fixture has results in the given division and update it."""
    import re
    try:
        results = client.get_results(div_id)
        for r in results:
            home_raw = r.get("homeTeam", "")
            away_raw = r.get("awayTeam", "")
            score_str = r.get("score", "")

            if not (fixture.home_team_name.lower() in home_raw.lower()
                    and fixture.away_team_name.lower() in away_raw.lower()):
                continue

            home_score, away_score, ht_home, ht_away = client.parse_score(score_str)
            is_walkover = home_score is None or away_score is None

            if is_walkover:
                fixture.played = True
                logger.info(f"  Walkover: {home_raw} vs {away_raw}")
            elif home_score is not None and away_score is not None:
                fixture.home_score = home_score
                fixture.away_score = away_score
                fixture.half_time_home = ht_home
                fixture.half_time_away = ht_away
                fixture.played = True
                logger.info(f"  Updated: {home_raw} {home_score}-{away_score} {away_raw}")

            break
    except Exception as e:
        logger.error(f"Error fetching results for division {div_id}: {e}")


def _score_updated_gameweek(db, gw_id: int):
    """Score a single gameweek that has new results.

    Generates player points for each played fixture and updates
    fantasy team totals and ranks.
    """
    from app.scoring import calculate_player_points
    import random

    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        return

    played_fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()

    if not played_fixtures:
        return

    for fixture in played_fixtures:
        is_walkover = fixture.home_score is None or fixture.away_score is None

        if is_walkover:
            _score_walkover(db, gw, fixture)
        else:
            _score_fixture(db, gw, fixture)

    db.flush()

    # Score fantasy teams
    for ft in db.query(FantasyTeam).all():
        squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
        if not squad:
            continue

        chip = ft.active_chip
        captain_sp = next((sp for sp in squad if sp.is_captain), None)
        effective_captain = captain_sp

        total = 0
        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if not pgp or not pgp.did_play:
                continue

            contributes = (chip == "bench_boost") or sp.is_starting
            if not contributes:
                continue

            pts = pgp.total_points
            if sp == effective_captain:
                mult = 3 if chip == "triple_captain" else 2
                pts = pgp.total_points * mult

            total += pts
            sp.gw_points = pts

        is_wildcard = ft.active_chip == "wildcard"
        is_free_hit = ft.active_chip == "free_hit"
        starting_free = ft.free_transfers + ft.current_gw_transfers
        if ft.current_gw_transfers > 0 and not is_wildcard and not is_free_hit:
            transfer_hit = max(0, ft.current_gw_transfers - starting_free) * 4
        else:
            transfer_hit = 0
        total -= transfer_hit
        ft.total_points += total

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

    # Update ranks
    all_teams = db.query(FantasyTeam).order_by(FantasyTeam.total_points.desc()).all()
    for rank, team in enumerate(all_teams, 1):
        team.overall_rank = rank

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()
    logger.info(f"Scored gameweek {gw.number} ({len(played_fixtures)} fixtures)")


def _score_walkover(db, gw, fixture):
    """Award walkover points (2 pts) to winning team's players."""
    home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
    away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

    home_won = fixture.home_score is not None and fixture.away_score is None
    if fixture.home_score is None and fixture.away_score is not None:
        home_won = False

    winning_team = home_team if home_won else away_team
    is_home_winner = home_won
    opponent = fixture.away_team_name if is_home_winner else fixture.home_team_name

    if winning_team:
        for player in db.query(Player).filter(
            Player.team_id == winning_team.id,
            Player.is_active == True,
        ).all():
            existing = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == player.id,
                PlayerGameweekPoints.gameweek_id == gw.id,
            ).first()
            if existing:
                continue

            pgp = PlayerGameweekPoints(
                player_id=player.id,
                gameweek_id=gw.id,
                opponent_team=opponent,
                was_home=is_home_winner,
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


def _score_fixture(db, gw, fixture):
    """Score a normal fixture with results."""
    from app.scoring import calculate_player_points
    import random

    for team_id, goals_scored, goals_conceded, is_home in [
        (fixture.home_team_id, fixture.home_score or 0, fixture.away_score or 0, True),
        (fixture.away_team_id, fixture.away_score or 0, fixture.home_score or 0, False),
    ]:
        if team_id is None:
            continue

        for player in db.query(Player).filter(
            Player.team_id == team_id,
            Player.is_active == True,
        ).all():
            existing = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == player.id,
                PlayerGameweekPoints.gameweek_id == gw.id,
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
                gameweek_id=gw.id,
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
                bps_score=0,
            )
            db.add(pgp)


def apply_deadline():
    """Apply transfer deadline for current gameweek."""
    logger.info("Applying transfer deadline...")
    init_binds()
    from app.database import BoundSessionLocal
    db = BoundSessionLocal()
    try:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        if current_gw:
            current_gw.closed = True
            db.commit()
            logger.info(f"Gameweek {current_gw.number} closed (deadline applied)")
    except Exception as e:
        logger.error(f"Deadline error: {e}")
        db.rollback()
    finally:
        db.close()


def process_gameweek_end():
    """Process end of gameweek: score, transfer rollover, price updates."""
    logger.info("Processing gameweek end...")
    init_binds()
    from app.database import BoundSessionLocal
    db = BoundSessionLocal()
    try:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        if current_gw:
            if not current_gw.scored:
                _score_gameweek_direct(db, current_gw.id)

            _process_transfer_rollovers(db)
            _update_player_prices(db, current_gw.id)
            _revert_free_hits(db)

            logger.info(f"Gameweek {current_gw.number} processed")
    except Exception as e:
        logger.error(f"GW end processing error: {e}")
        db.rollback()
    finally:
        db.close()


def _score_gameweek_direct(db, gw_id: int):
    """Score gameweek points directly (no DI)."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw or gw.scored:
        return

    for fixture in gw.fixtures:
        if not fixture.played:
            continue

        home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
        away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

        is_walkover = fixture.home_score is None or fixture.away_score is None

        if is_walkover:
            continue

        home_cs = (fixture.away_score or 0) == 0
        away_cs = (fixture.home_score or 0) == 0

        for team, is_home, gs, gc, cs in [
            (home_team, True, fixture.home_score or 0, fixture.away_score or 0, home_cs),
            (away_team, False, fixture.away_score or 0, fixture.home_score or 0, away_cs),
        ]:
            if not team:
                continue
            opponents = fixture.away_team_name if is_home else fixture.home_team_name
            scorers_text = fixture.home_scorers if is_home else fixture.away_scorers
            scorer_names = json.loads(scorers_text) if scorers_text else []

            for player in db.query(Player).filter(Player.team_id == team.id, Player.is_active == True).all():
                existing = db.query(PlayerGameweekPoints).filter(
                    PlayerGameweekPoints.player_id == player.id,
                    PlayerGameweekPoints.gameweek_id == gw_id,
                ).first()
                if existing:
                    continue

                p_goals = 1 if player.name in scorer_names else 0
                minutes = 90 if p_goals > 0 else (60 if player.apps > 0 else 0)

                pts = scoring.calculate_player_points(
                    position=player.position,
                    goals_scored=p_goals,
                    clean_sheet=cs if player.position in ("GK", "DEF", "MID") else False,
                    goals_conceded=gc,
                    minutes_played=minutes,
                    saves=3 if player.position == "GK" and minutes > 0 else 0,
                )

                pgp = PlayerGameweekPoints(
                    player_id=player.id,
                    gameweek_id=gw_id,
                    opponent_team=opponents,
                    was_home=is_home,
                    minutes_played=minutes,
                    did_play=minutes > 0,
                    goals_scored=p_goals,
                    clean_sheet=cs,
                    goals_conceded=gc,
                    base_points=pts,
                    total_points=pts,
                )
                db.add(pgp)

                player.apps += 1
                player.goals += p_goals
                player.total_points_season += pts
                if cs and player.position in ("GK", "DEF", "MID"):
                    player.clean_sheets += 1

    # Team scores
    for ft in db.query(FantasyTeam).all():
        squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
        captain_sp = next((sp for sp in squad if sp.is_captain), None)
        vc_sp = next((sp for sp in squad if sp.is_vice_captain), None)

        effective_captain = captain_sp
        if captain_sp:
            cp_gp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == captain_sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if not cp_gp or not cp_gp.did_play:
                effective_captain = vc_sp

        chip = ft.active_chip
        total = 0

        for sp in squad:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == sp.player_id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if not pgp or not pgp.did_play:
                continue
            contributes = (chip == "bench_boost") or sp.is_starting
            if not contributes:
                continue

            pts = pgp.total_points
            if sp == effective_captain:
                mult = 3 if chip == "triple_captain" else 2
                pts = pgp.total_points * mult

            total += pts
            sp.gw_points = pts

        is_wildcard = ft.active_chip == "wildcard"
        is_free_hit = ft.active_chip == "free_hit"
        starting_free = ft.free_transfers + ft.current_gw_transfers
        if ft.current_gw_transfers > 0 and not is_wildcard and not is_free_hit:
            transfer_hit = max(0, ft.current_gw_transfers - starting_free) * 4
        else:
            transfer_hit = 0
        total -= transfer_hit
        ft.total_points += total

        existing_hist = db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.fantasy_team_id == ft.id,
            FantasyTeamHistory.gameweek_id == gw_id,
        ).first()
        if existing_hist:
            existing_hist.points = total
            existing_hist.total_points = ft.total_points
            existing_hist.chip_used = chip
            existing_hist.transfers_made = ft.current_gw_transfers
            existing_hist.transfers_cost = transfer_hit
        else:
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

    all_teams = db.query(FantasyTeam).order_by(FantasyTeam.total_points.desc()).all()
    for rank, team in enumerate(all_teams, 1):
        team.overall_rank = rank

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()


def _process_transfer_rollovers(db):
    """Process transfer rollovers for new gameweek."""
    for ft in db.query(FantasyTeam).all():
        if ft.active_chip == "wildcard":
            ft.free_transfers = 1
            ft.free_transfers_next_gw = 1
        else:
            starting_free = ft.free_transfers + ft.current_gw_transfers
            unused = max(0, starting_free - ft.current_gw_transfers)
            rollover = min(unused, scoring.MAX_ROLLOVER_TRANSFERS)
            ft.free_transfers = 1 + rollover
            ft.free_transfers_next_gw = ft.free_transfers

        ft.rollover_transfers = ft.free_transfers - 1
        ft.current_gw_transfers = 0
        ft.transfer_deadline_exceeded = False
        if ft.active_chip and ft.active_chip != "free_hit":
            ft.active_chip = None
    db.commit()


def _update_player_prices(db, gw_id: int):
    """Update player prices based on performance."""
    total_teams = db.query(FantasyTeam).count()
    for player in db.query(Player).filter(Player.is_active == True).all():
        squad_count = db.query(SquadPlayer).filter(SquadPlayer.player_id == player.id).count()
        pct = (squad_count / max(total_teams, 1)) * 100
        player.selected_by_percent = round(pct, 1)

        recent = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id
        ).order_by(PlayerGameweekPoints.gameweek_id.desc()).limit(5).all()
        if recent:
            player.form = scoring.calculate_form([p.total_points for p in recent])

        last_gw = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id,
            PlayerGameweekPoints.gameweek_id == gw_id,
        ).first()
        gw_points = last_gw.total_points if last_gw else 0

        old = player.price
        new = scoring.update_player_price(
            selected_by_change=0,
            gw_points=gw_points,
            current_price=player.price,
            position=player.position or "MID",
            total_points_season=player.total_points_season or 0,
            apps=player.apps or 0,
        )
        player.price_change = int(round((new - old) * 10))
        player.price = new

    db.commit()


def _revert_free_hits(db):
    """Revert Free Hit squads."""
    for ft in db.query(FantasyTeam).filter(FantasyTeam.active_chip == "free_hit").all():
        if ft.free_hit_backup:
            backup = json.loads(ft.free_hit_backup)
            for sp in db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all():
                db.delete(sp)
            for entry in backup:
                player = db.query(Player).filter(Player.id == entry["player_id"]).first()
                if player:
                    db.add(SquadPlayer(
                        fantasy_team_id=ft.id,
                        player_id=entry["player_id"],
                        position_slot=entry["position_slot"],
                        is_captain=entry["is_captain"],
                        is_vice_captain=entry["is_vice_captain"],
                        is_starting=entry["is_starting"],
                    ))
            ft.active_chip = None
            ft.free_hit_backup = None
    db.commit()


def sync_fixtures():
    """Sync fixtures from FullTime API.

    Fetches results and updates fixtures, schedules per-fixture sync jobs
    for upcoming unplayed matches.
    """
    logger.info("Syncing fixtures (bulk)...")
    from app.database import BoundSessionLocal
    init_binds()
    if BoundSessionLocal is None:
        raise RuntimeError("Database not initialized")
    db = BoundSessionLocal()
    try:
        from app.api_client import FullTimeAPIClient

        client = FullTimeAPIClient()

        updated = 0
        walkovers = 0
        for div_name, div_id in FullTimeAPIClient.DIVISIONS.items():
            try:
                results = client.get_results(div_id)
                logger.info(f"Division {div_name}: {len(results)} results")

                for r in results:
                    home_raw = r.get("homeTeam", "")
                    away_raw = r.get("awayTeam", "")
                    score_str = r.get("score", "")

                    home_score, away_score, ht_home, ht_away = client.parse_score(score_str)

                    fixture = db.query(Fixture).filter(
                        Fixture.home_team_name.like(f"%{home_raw}%"),
                        Fixture.away_team_name.like(f"%{away_raw}%"),
                    ).first()

                    if not fixture:
                        continue

                    is_walkover = home_score is None or away_score is None

                    if is_walkover:
                        if not fixture.played:
                            fixture.played = True
                            walkovers += 1
                            logger.info(f"  Walkover: {home_raw} vs {away_raw}")
                    else:
                        if fixture.home_score != home_score or fixture.away_score != away_score:
                            fixture.home_score = home_score
                            fixture.away_score = away_score
                            fixture.half_time_home = ht_home
                            fixture.half_time_away = ht_away
                            fixture.played = True
                            updated += 1
                            logger.info(f"  Updated: {home_raw} {home_score}-{away_score} {away_raw}")

                # Update league table
                table = client.get_league_table(div_id)
                if table:
                    for entry in table:
                        team_name = entry.get("team", "")
                        team = db.query(Team).filter(Team.name.like(f"%{team_name}%")).first()
                        if team:
                            team.current_position = entry.get("position")
                            team.games_played = entry.get("played", team.games_played)
                            team.games_won = entry.get("won", team.games_won)
                            team.games_drawn = entry.get("drawn", team.games_drawn)
                            team.games_lost = entry.get("lost", team.games_lost)
                            team.goals_for = entry.get("goalsFor", team.goals_for)
                            team.goals_against = entry.get("goalsAgainst", team.goals_against)
                            team.goal_difference = entry.get("goalDifference", team.goal_difference)
                            team.current_points = entry.get("points", team.current_points)

            except Exception as e:
                logger.error(f"Error syncing division {div_name}: {e}")
                continue

        db.commit()

        if updated or walkovers:
            logger.info(f"Synced: {updated} results, {walkovers} walkovers")
            _score_updated_gameweeks_bulk(db)

        # Schedule per-fixture sync jobs for upcoming matches
        schedule_per_fixture_sync(db)

    except Exception as e:
        logger.error(f"Fixture sync error: {e}")
        db.rollback()
    finally:
        db.close()


def _score_updated_gameweeks_bulk(db):
    """Score all gameweeks that have new results (bulk mode)."""
    gameweeks = db.query(Gameweek).all()
    for gw in gameweeks:
        played_fixtures = db.query(Fixture).filter(
            Fixture.gameweek_id == gw.id,
            Fixture.played == True,
        ).all()

        if played_fixtures:
            _score_updated_gameweek(db, gw.id)
