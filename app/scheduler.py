"""Scheduler for gameweek deadlines and bonus point calculations.

Uses APScheduler to run:
1. Deadline check at 11:00 AM Saturday - closes transfers
2. Bonus points calculation at 9:00 PM Saturday - calculates and applies bonus points
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import Gameweek, User, Fixture, SquadPlayer, PlayerFixture, FantasyTeam, FantasyTeamHistory
from app import scoring

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def get_current_gameweek() -> Gameweek:
    """Get the current (not yet closed) gameweek."""
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(
            Gameweek.closed == False,
            Gameweek.bonus_calculated == False,
        ).order_by(Gameweek.start_date).first()
        return gw
    finally:
        db.close()


def enforce_deadline():
    """Close transfers for the current gameweek at 11:00 AM Saturday."""
    logger.info("Enforcing gameweek deadline...")
    gw = get_current_gameweek()
    
    if not gw:
        logger.info("No active gameweek to close deadline for.")
        return
    
    db = SessionLocal()
    try:
        gw.closed = True
        db.commit()
        logger.info(f"Gameweek {gw.number} deadline enforced.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error enforcing deadline: {e}")
    finally:
        db.close()


def calculate_bonus_points():
    """Calculate and apply bonus points at 9:00 PM Saturday."""
    logger.info("Calculating bonus points...")
    gw = get_current_gameweek()
    
    if not gw:
        logger.info("No active gameweek to calculate bonus points for.")
        return
    
    db = SessionLocal()
    try:
        # Get all player fixtures for this gameweek
        player_fixtures = db.query(PlayerFixture).filter(
            PlayerFixture.gameweek_id == gw.id,
            PlayerFixture.bonus_points == 0,  # Not yet calculated
        ).all()
        
        if not player_fixtures:
            logger.info("No player fixtures to calculate bonus points for.")
            gw.bonus_calculated = True
            db.commit()
            return
        
        # Calculate bonus points
        bonus_map = scoring.calculate_bonus_points(player_fixtures)
        
        for pf in player_fixtures:
            bonus = bonus_map.get(pf.id, 0)
            pf.bonus_points = bonus
            pf.total_points = pf.points + bonus
        
        # Update fantasy team history totals
        for fth in db.query(FantasyTeamHistory).filter(
            FantasyTeamHistory.gameweek_id == gw.id
        ).all():
            new_total = sum(
                pf.total_points
                for pf in player_fixtures
                if pf.squad_player.fantasy_team_id == fth.fantasy_team_id
            )
            fth.points = new_total
        
        # Update fantasy team totals
        for ft in db.query(FantasyTeam).all():
            total = sum(
                fth.points
                for fth in ft.history
            )
            ft.total_points = total
        
        gw.bonus_calculated = True
        db.commit()
        logger.info(f"Bonus points calculated for Gameweek {gw.number}.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error calculating bonus points: {e}")
    finally:
        db.close()


def process_gameweek_results():
    """Process completed fixtures and calculate scores for the current gameweek."""
    logger.info("Processing gameweek results...")
    gw = get_current_gameweek()
    
    if not gw:
        logger.info("No active gameweek to process.")
        return
    
    db = SessionLocal()
    try:
        # Get all fixtures for this gameweek
        fixtures = db.query(Fixture).filter(
            Fixture.gameweek_id == gw.id,
            Fixture.played == True,
        ).all()
        
        if not fixtures:
            logger.info("No completed fixtures to process.")
            return
        
        # Get all squad players
        squad_players = db.query(SquadPlayer).all()
        
        # Build fixture lookup
        fixture_lookup = {}
        for fixture in fixtures:
            fixture_lookup[fixture.home_team] = {
                "result": "W" if fixture.home_score > fixture.away_score else (
                    "D" if fixture.home_score == fixture.away_score else "L"
                ),
                "goals_scored": fixture.home_score,
                "goals_conceded": fixture.away_score,
                "opponent": fixture.away_team,
                "is_home": True,
                "fixture_id": fixture.id,
            }
            fixture_lookup[fixture.away_team] = {
                "result": "W" if fixture.away_score > fixture.home_score else (
                    "D" if fixture.away_score == fixture.home_score else "L"
                ),
                "goals_scored": fixture.away_score,
                "goals_conceded": fixture.home_score,
                "opponent": fixture.home_team,
                "is_home": False,
                "fixture_id": fixture.id,
            }
        
        # Process each squad player
        for sp in squad_players:
            team_name = sp.team.name
            if team_name not in fixture_lookup:
                # Team didn't play this gameweek
                continue
            
            result = fixture_lookup[team_name]
            
            # Check if we already processed this
            existing = db.query(PlayerFixture).filter(
                PlayerFixture.gameweek_id == gw.id,
                PlayerFixture.squad_player_id == sp.id,
            ).first()
            
            if existing:
                continue
            
            # Calculate points
            is_captain = sp.is_captain
            points = scoring.calculate_team_points(
                goals_scored=result["goals_scored"],
                goals_conceded=result["goals_conceded"],
                result=result["result"],
                is_captain=is_captain,
            )
            
            # Create player fixture record
            pf = PlayerFixture(
                gameweek_id=gw.id,
                squad_player_id=sp.id,
                fixture_id=result["fixture_id"],
                points=points["base_total"],
                bonus_points=0,  # To be calculated later
                total_points=points["total"],
                minutes=90,
                goals_scored=result["goals_scored"],
                clean_sheet=(result["goals_conceded"] == 0),
                goals_conceded=result["goals_conceded"],
                was_home=result["is_home"],
                opponent=result["opponent"],
            )
            db.add(pf)
            
            # Update squad player total
            sp.total_points += points["total"]
        
        # Update fantasy team history
        player_fixtures = db.query(PlayerFixture).filter(
            PlayerFixture.gameweek_id == gw.id,
        ).all()
        
        for ft in db.query(FantasyTeam).all():
            total = sum(
                pf.total_points
                for pf in player_fixtures
                if pf.squad_player.fantasy_team_id == ft.id
            )
            
            fth = FantasyTeamHistory(
                fantasy_team_id=ft.id,
                gameweek_id=gw.id,
                points=total,
            )
            db.add(fth)
            ft.total_points += total
        
        db.commit()
        logger.info(f"Processed results for Gameweek {gw.number}.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing gameweek results: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler."""
    # Deadline check: Every Saturday at 11:00 AM
    scheduler.add_job(
        enforce_deadline,
        "cron",
        day_of_week="sat",
        hour=11,
        minute=0,
        id="deadline_check",
        name="Enforce gameweek deadline",
        replace_existing=True,
    )
    
    # Bonus points: Every Saturday at 9:00 PM
    scheduler.add_job(
        calculate_bonus_points,
        "cron",
        day_of_week="sat",
        hour=21,
        minute=0,
        id="bonus_points",
        name="Calculate bonus points",
        replace_existing=True,
    )
    
    # Process results: Every 6 hours (to catch API updates)
    scheduler.add_job(
        process_gameweek_results,
        "interval",
        hours=6,
        id="process_results",
        name="Process gameweek results",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("Scheduler started.")


def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler shutdown.")
