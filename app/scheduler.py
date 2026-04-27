"""APScheduler tasks for Fantasy Football Isle of Man.

FPL Schedule:
- Team deadline: Saturday 11:00 AM (no more transfers after this)
- Bonus points calculated: Saturday 9:00 PM
- Gameweek scoring: After all matches complete
- Transfer rollover: When new gameweek starts
- Player price updates: After gameweek scoring
"""
import json
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

from app.database import SessionLocal, Base, engine
from app.models import (
    Gameweek, Season, Player, PlayerGameweekPoints,
    FantasyTeam, SquadPlayer, FantasyTeamHistory, Team, Fixture,
)
from app import scoring

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


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

    # Saturday 9:00 PM - Calculate bonus points
    scheduler.add_job(
        calculate_bonus_points,
        CronTrigger(day_of_week="sat", hour=21, minute=0),
        id="calculate_bonus",
        name="Calculate bonus points",
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

    # Daily at 3 AM - Sync fixtures from FullTime API
    scheduler.add_job(
        sync_fixtures,
        CronTrigger(hour=3, minute=0),
        id="sync_fixtures",
        name="Sync fixtures from FullTime API",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Shutdown the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down.")


def apply_deadline():
    """Apply transfer deadline for current gameweek."""
    logger.info("Applying transfer deadline...")
    db = SessionLocal()
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


def calculate_bonus_points():
    """Calculate bonus points for completed fixtures."""
    logger.info("Calculating bonus points...")
    db = SessionLocal()
    try:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        if current_gw and not current_gw.bonus_calculated:
            fixtures = current_gw.fixtures
            for fixture in fixtures:
                if not fixture.played:
                    continue

                home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
                away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

                all_players_bps = []
                for team in [home_team, away_team]:
                    if not team:
                        continue
                    team_players = db.query(Player).filter(
                        Player.team_id == team.id,
                        Player.is_active == True,
                    ).all()

                    for player in team_players:
                        pgp = db.query(PlayerGameweekPoints).filter(
                            PlayerGameweekPoints.player_id == player.id,
                            PlayerGameweekPoints.gameweek_id == current_gw.id,
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

                if len(all_players_bps) >= 3:
                    bonus_map = scoring.award_bonus_points(all_players_bps)
                    for player_id, bonus in bonus_map.items():
                        pgp = db.query(PlayerGameweekPoints).filter(
                            PlayerGameweekPoints.player_id == player_id,
                            PlayerGameweekPoints.gameweek_id == current_gw.id,
                        ).first()
                        if pgp and bonus > 0:
                            pgp.bonus_points = bonus
                            pgp.total_points = pgp.base_points + bonus
                            player = db.query(Player).filter(Player.id == player_id).first()
                            if player:
                                player.bonus += bonus
                                player.total_points_season += bonus

            current_gw.bonus_calculated = True
            db.commit()
            logger.info(f"Bonus points calculated for GW {current_gw.number}")
    except Exception as e:
        logger.error(f"Bonus calculation error: {e}")
        db.rollback()
    finally:
        db.close()


def process_gameweek_end():
    """Process end of gameweek: score, transfer rollover, price updates."""
    logger.info("Processing gameweek end...")
    db = SessionLocal()
    try:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.desc()).first()

        if current_gw:
            if not current_gw.scored:
                _score_gameweek_direct(db, current_gw.id)

            # Transfer rollovers
            _process_transfer_rollovers(db)

            # Update player prices
            _update_player_prices(db, current_gw.id)

            # Revert Free Hits
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

        transfer_hit = max(0, ft.current_gw_transfers - ft.free_transfers) * 4
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

    # Ranks
    all_teams = db.query(FantasyTeam).order_by(FantasyTeam.total_points.desc()).all()
    for rank, team in enumerate(all_teams, 1):
        team.overall_rank = rank

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()


def _process_transfer_rollovers(db):
    """Process transfer rollovers for new gameweek."""
    for ft in db.query(FantasyTeam).all():
        unused = max(0, ft.free_transfers)
        rollover = min(unused + ft.rollover_transfers, 5)
        ft.rollover_transfers = rollover
        ft.free_transfers = min(1 + rollover, 6)
        ft.free_transfers_next_gw = ft.free_transfers
        ft.current_gw_transfers = 0
        ft.transfer_deadline_exceeded = False
    db.commit()


def _update_player_prices(db, gw_id: int):
    """Update player prices."""
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

        old = player.price
        new = scoring.update_player_price(pct, player.form, player.price)
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
    """Sync fixtures from FullTime API daily."""
    logger.info("Syncing fixtures...")
    try:
        from app import api_client
        client = api_client.FullTimeAPIClient()
        fixtures = client.get_all_fixtures()
        if fixtures:
            logger.info(f"Synced {len(fixtures)} fixtures")
    except Exception as e:
        logger.error(f"Fixture sync error: {e}")
