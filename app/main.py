"""Fantasy Football Isle of Man - FastAPI Application."""
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
import logging

from app.database import init_db, engine, Base, get_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routes import (
    players, teams, users, gameweeks, leaderboard, transfers,
    mini_leagues, h2h, prices, gameweek_recap, transfers_tracking,
    fixtures, team_value, gameweek_history, captain_hints, admin,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    logger.info("Initializing Fantasy Football IOM...")
    init_db()
    start_scheduler()
    logger.info("Fantasy Football IOM started.")

    yield

    shutdown_scheduler()
    logger.info("Fantasy Football IOM shutdown.")


app = FastAPI(
    title="Fantasy Football Isle of Man",
    description="FPL-style fantasy football for Isle of Man Senior Men's Leagues",
    version="1.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# API routes
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(users.router)
app.include_router(gameweeks.router)
app.include_router(leaderboard.router)
app.include_router(transfers.router)
app.include_router(mini_leagues.router)
app.include_router(h2h.router)
app.include_router(prices.router, prefix="/api/prices", tags=["prices"])
app.include_router(gameweek_recap.router, prefix="/api/gameweeks", tags=["gameweek-recap"])
app.include_router(transfers_tracking.router, prefix="/api/transfers", tags=["transfers-tracking"])
app.include_router(fixtures.router, prefix="/api/fixtures", tags=["fixtures"])
app.include_router(team_value.router, prefix="/api/team-value", tags=["team-value"])
app.include_router(gameweek_history.router, prefix="/api/gameweek-history", tags=["gameweek-history"])
app.include_router(captain_hints.router, prefix="/api/captain-hints", tags=["captain-hints"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/api/dream-team/{gw_id}")
async def get_dream_team_endpoint(gw_id: int, db: Session = Depends(get_db)):
    """Standalone Dream Team endpoint for the frontend.

    Returns: {"players": [...], "total_points": N}
    """
    from app.models import DreamTeam, DreamTeamPlayer

    dream_team = db.query(DreamTeam).filter(DreamTeam.gameweek_id == gw_id).first()

    if not dream_team:
        return {"players": [], "total_points": 0, "message": "Dream Team not yet calculated"}

    members = db.query(DreamTeamPlayer).filter(
        DreamTeamPlayer.dream_team_id == dream_team.id
    ).all()

    return {
        "players": [
            {
                "player_id": m.player_id,
                "name": m.player.name if m.player else "Unknown",
                "team_name": m.player.team.name if m.player and m.player.team else "",
                "position": m.position,
                "points": m.points,
                "cost": m.player.price if m.player else 0,
                "formation_position": m.formation_position,
            }
            for m in sorted(members, key=lambda x: x.formation_position)
        ],
        "total_points": dream_team.total_points,
    }


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main application page."""
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
