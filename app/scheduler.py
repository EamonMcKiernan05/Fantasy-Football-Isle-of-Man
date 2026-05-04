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

    # Match day syncs: every 6 hours during active periods
    # Saturday 10am, 4pm, 10pm and Sunday 10am, 4pm, 10pm
    scheduler.add_job(
        sync_fixtures,
        CronTrigger(day_of_week="sat,sun", hour="10,16,22", minute=0),
        id="sync_fixtures_matchday",
        name="Sync fixtures during match days",
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

        is_walkover = fixture.home_score is None or fixture.away_score is None

        if is_walkover:
            # Walkover handled by _score_updated_gameweeks; skip here
            # to avoid double-scoring
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

        # Calculate transfer hit correctly: reconstruct starting free transfers
        # free_transfers is decremented per transfer, so starting_free = free_transfers + current_gw_transfers
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

    # Ranks
    all_teams = db.query(FantasyTeam).order_by(FantasyTeam.total_points.desc()).all()
    for rank, team in enumerate(all_teams, 1):
        team.overall_rank = rank

    gw.scored = True
    gw.bonus_calculated = True
    db.commit()


def _process_transfer_rollovers(db):
    """Process transfer rollovers for new gameweek.

    Free transfers can be negative (extra transfers beyond free allowance).
    After GW ends, reset to base 1 + rollover of unused.
    """
    for ft in db.query(FantasyTeam).all():
        if ft.active_chip == "wildcard":
            ft.free_transfers = 1
            ft.free_transfers_next_gw = 1
        else:
            # Free transfers can be negative (extra transfers beyond free)
            # Reconstruct starting free count
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
    """Sync fixtures from FullTime API daily.

    Fetches results and updates fixtures, then triggers scoring for
    any new results. Handles walkovers by awarding 2 points to players.
    """
    logger.info("Syncing fixtures...")
    db = SessionLocal()
    try:
        from app.api_client import FullTimeAPIClient

        client = FullTimeAPIClient()

        # Fetch results for all divisions
        updated = 0
        walkovers = 0
        for div_name, div_id in FullTimeAPIClient.DIVISIONS.items():
            try:
                results = client.get_results(div_id)
                logger.info(f"Division {div_name}: {len(results)} results")

                import re

                for r in results:
                    home_raw = r.get("homeTeam", "")
                    away_raw = r.get("awayTeam", "")
                    score_str = r.get("score", "")

                    home_score, away_score, ht_home, ht_away = client.parse_score(score_str)

                    # Find matching fixture
                    fixture = db.query(Fixture).filter(
                        Fixture.home_team_name.like(f"%{home_raw}%"),
                        Fixture.away_team_name.like(f"%{away_raw}%"),
                    ).first()

                    if not fixture:
                        continue

                    is_walkover = home_score is None or away_score is None

                    if is_walkover:
                        # Walkover: mark as played but no scores
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

                    # Parse scorers if available
                    # (scorers would be in a separate API call or parsed from the result)

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

            # Trigger scoring for affected gameweeks
            _score_updated_gameweeks(db)
        else:
            logger.info("No new results to sync")

    except Exception as e:
        logger.error(f"Fixture sync error: {e}")
        db.rollback()
    finally:
        db.close()


def _score_updated_gameweeks(db):
    """Score gameweeks that have new results.

    Finds gameweeks with played fixtures that haven't been scored yet
    and runs the scoring pipeline.
    """
    from app.scoring import calculate_player_points, calculate_bps, award_bonus_points
    import random

    # Find gameweeks with played but unscored fixtures
    gameweeks = db.query(Gameweek).all()
    for gw in gameweeks:
        played_fixtures = db.query(Fixture).filter(
            Fixture.gameweek_id == gw.id,
            Fixture.played == True,
        ).all()

        if not played_fixtures:
            continue

        # Generate player points for each played fixture
        for fixture in played_fixtures:
            is_walkover = fixture.home_score is None or fixture.away_score is None

            if is_walkover:
                # Walkover: award 2 points only to the winning team's players
                home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
                away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()

                # Determine winner: if one team has a score and the other doesn't,
                # the team with a score won. If both null, use home_score=2, away_score=0
                # to indicate home won by walkover (default assumption).
                home_won = True  # default: home team wins walkover
                if fixture.home_score is not None and fixture.away_score is None:
                    home_won = True  # Home has a score, away doesn't - home won
                elif fixture.home_score is None and fixture.away_score is not None:
                    home_won = False  # Away has a score, home doesn't - away won
                # If both are None, home_won stays True (default)

                winning_team = home_team if home_won else away_team
                is_home_winner = home_won
                opponent = fixture.away_team_name if is_home_winner else fixture.home_team_name

                if winning_team:
                    team_players = db.query(Player).filter(
                        Player.team_id == winning_team.id,
                        Player.is_active == True,
                    ).all()

                    for player in team_players:
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
            else:
                # Normal fixture
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
                    PlayerGameweekPoints.gameweek_id == gw.id,
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

            # Calculate transfer hit correctly: reconstruct starting free transfers
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
                gameweek_id=gw.id,
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
        logger.info(f"Scored gameweek {gw.number}")
