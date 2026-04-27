"""Fantasy Football Isle of Man - FastAPI Application."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.database import init_db, engine, Base
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routes import players, teams, users, gameweeks, leaderboard, transfers, mini_leagues, h2h

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


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main application page."""
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
