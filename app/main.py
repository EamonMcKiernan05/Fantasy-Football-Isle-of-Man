"""Fantasy Football Isle of Man - FastAPI Application."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import logging

from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routes import teams, users, gameweeks, leaderboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("Initializing Fantasy Football IOM...")
    init_db()
    start_scheduler()
    logger.info("Fantasy Football IOM started.")
    
    yield
    
    # Shutdown
    shutdown_scheduler()
    logger.info("Fantasy Football IOM shutdown.")


app = FastAPI(
    title="Fantasy Football Isle of Man",
    description="FPL-style fantasy football for Isle of Man Senior Men's Leagues",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register API routes
app.include_router(teams.router)
app.include_router(users.router)
app.include_router(gameweeks.router)
app.include_router(leaderboard.router)


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main application page."""
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
