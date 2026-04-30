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
    notifications, h2h_bracket,
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
app.include_router(prices.router)
app.include_router(gameweek_recap.router)
app.include_router(transfers_tracking.router)
app.include_router(fixtures.router)
app.include_router(team_value.router)
app.include_router(gameweek_history.router)
app.include_router(captain_hints.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(h2h_bracket.router)


@app.get("/api/dream-team/{gw_id}")
async def get_dream_team_endpoint(gw_id: int, db: Session = Depends(get_db)):
    """Standalone Dream Team endpoint for the frontend.

    If a stored DreamTeam exists for the GW, returns it. Otherwise, computes
    a best-XI on the fly from PlayerGameweekPoints in a 4-4-2 formation
    (1 GK, 4 DEF, 4 MID, 2 FWD = 11 players) so the page is never empty
    once GWs have stats.

    Returns: {"players": [...], "total_points": N, "captain": {...}}
    """
    from app.models import (
        DreamTeam, DreamTeamPlayer, PlayerGameweekPoints, Player, Gameweek,
    )

    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        return {"players": [], "total_points": 0, "message": "Gameweek not found"}

    dream_team = db.query(DreamTeam).filter(DreamTeam.gameweek_id == gw_id).first()
    if dream_team:
        members = db.query(DreamTeamPlayer).filter(
            DreamTeamPlayer.dream_team_id == dream_team.id
        ).all()
        captain = max(members, key=lambda m: m.points) if members else None
        return {
            "gameweek": gw.number,
            "players": [
                {
                    "player_id": m.player_id,
                    "name": m.player.name if m.player else "Unknown",
                    "team_name": m.player.team.name if m.player and m.player.team else "",
                    "position": m.position,
                    "points": m.points,
                    "cost": m.player.price if m.player else 0,
                    "formation_position": m.formation_position,
                    "is_captain": captain is not None and m.id == captain.id,
                }
                for m in sorted(members, key=lambda x: x.formation_position)
            ],
            "total_points": dream_team.total_points,
        }

    # Compute on the fly: top 1 GK, top 4 DEF, top 4 MID, top 2 FWD
    rows = (
        db.query(PlayerGameweekPoints, Player)
        .join(Player, Player.id == PlayerGameweekPoints.player_id)
        .filter(PlayerGameweekPoints.gameweek_id == gw_id)
        .all()
    )
    if not rows:
        return {"players": [], "total_points": 0, "message": "No stats yet for this gameweek"}

    by_pos = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for pgp, p in rows:
        if p.position in by_pos:
            by_pos[p.position].append((pgp.total_points or 0, p))

    for pos in by_pos:
        by_pos[pos].sort(key=lambda r: r[0], reverse=True)

    selection = []
    selection += [(p, "GK", pts) for pts, p in by_pos["GK"][:1]]
    selection += [(p, "DEF", pts) for pts, p in by_pos["DEF"][:4]]
    selection += [(p, "MID", pts) for pts, p in by_pos["MID"][:4]]
    selection += [(p, "FWD", pts) for pts, p in by_pos["FWD"][:2]]

    if not selection:
        return {"players": [], "total_points": 0}

    captain_idx = max(range(len(selection)), key=lambda i: selection[i][2])
    formation_pos = 1
    out_players = []
    for idx, (p, pos, pts) in enumerate(selection):
        out_players.append({
            "player_id": p.id,
            "name": p.name,
            "team_name": p.team.name if p.team else "",
            "position": pos,
            "points": pts,
            "cost": p.price,
            "formation_position": formation_pos,
            "is_captain": idx == captain_idx,
        })
        formation_pos += 1

    return {
        "gameweek": gw.number,
        "players": out_players,
        "total_points": sum(p["points"] for p in out_players),
    }


@app.get("/api/stats/gameweek/{gw_id}")
async def get_gw_stats(gw_id: int, db: Session = Depends(get_db)):
    """Per-gameweek summary stats: average score, highest score, top players."""
    from app.models import (
        FantasyTeamHistory, Gameweek, PlayerGameweekPoints, Player,
    )
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        return {"error": "gameweek not found"}

    histories = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.gameweek_id == gw_id
    ).all()
    avg = round(sum(h.points for h in histories) / len(histories), 1) if histories else 0
    high = max((h.points for h in histories), default=0)

    # Top 5 player performers
    rows = (
        db.query(PlayerGameweekPoints, Player)
        .join(Player, Player.id == PlayerGameweekPoints.player_id)
        .filter(PlayerGameweekPoints.gameweek_id == gw_id)
        .order_by(PlayerGameweekPoints.total_points.desc())
        .limit(5)
        .all()
    )

    return {
        "gameweek_id": gw_id,
        "gameweek_number": gw.number,
        "deadline": gw.deadline.isoformat() if gw.deadline else None,
        "closed": gw.closed,
        "scored": gw.scored,
        "average_score": avg,
        "highest_score": high,
        "managers_played": len(histories),
        "top_players": [
            {
                "player_id": p.id,
                "name": p.name,
                "team_name": p.team.name if p.team else "",
                "position": p.position,
                "points": pgp.total_points or 0,
                "goals": pgp.goals_scored or 0,
                "assists": pgp.assists or 0,
            }
            for pgp, p in rows
        ],
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
