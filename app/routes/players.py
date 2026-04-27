"""Player browsing API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, date, timedelta

from app.database import get_db
from app.models import Player, Team, Division, Gameweek, Fixture, PlayerGameweekPoints
from app.schemas import PlayerResponse, PlayerDetailResponse, PlayerHistoryEntry
from app import api_client

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("/", response_model=List[PlayerResponse])
def list_players(
    position: Optional[str] = Query(None, description="Filter by position: GK, DEF, MID, FWD"),
    division_id: Optional[int] = Query(None, description="Filter by division ID"),
    team_id: Optional[int] = Query(None, description="Filter by team ID"),
    search: Optional[str] = Query(None, description="Search by player name"),
    min_price: Optional[float] = Query(None, description="Minimum price"),
    max_price: Optional[float] = Query(None, description="Maximum price"),
    order_by: str = Query("goals", description="Sort by: goals, points, price, apps"),
    db: Session = Depends(get_db),
):
    """List all players with optional filters."""
    query = db.query(Player).filter(Player.is_active == True)

    if position:
        query = query.filter(Player.position == position)
    if team_id:
        query = query.filter(Player.team_id == team_id)
    if division_id:
        query = query.filter(Player.team.has(division_id == division_id))
    if search:
        query = query.filter(Player.name.ilike(f"%{search}%"))
    if min_price:
        query = query.filter(Player.price >= min_price)
    if max_price:
        query = query.filter(Player.price <= max_price)

    # Sort
    order_map = {
        "goals": Player.goals.desc(),
        "points": Player.goals.desc(),  # Use goals as proxy
        "price": Player.price.desc(),
        "apps": Player.apps.desc(),
        "name": Player.name.asc(),
    }
    query = query.order_by(order_map.get(order_by, Player.goals.desc()))

    players = query.limit(200).all()

    # Add current gameweek points
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.desc()).first()

    result = []
    for p in players:
        gw_pts = None
        if current_gw:
            pgp = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == p.id,
                PlayerGameweekPoints.gameweek_id == current_gw.id,
            ).first()
            gw_pts = pgp.total_points if pgp else None

        result.append(PlayerResponse(
            id=p.id,
            name=p.name,
            team_id=p.team_id,
            position=p.position,
            price=p.price,
            apps=p.apps,
            goals=p.goals,
            assists=p.assists,
            clean_sheets=p.clean_sheets,
            total_points=p.goals * 4,  # Approximate total
            gw_points=gw_pts,
        ))

    return result


@router.get("/{player_id}", response_model=PlayerDetailResponse)
def get_player(player_id: int, db: Session = Depends(get_db)):
    """Get player details."""
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    team = player.team
    return PlayerDetailResponse(
        id=player.id,
        name=player.name,
        team_id=player.team_id,
        position=player.position,
        price=player.price,
        apps=player.apps,
        goals=player.goals,
        assists=player.assists,
        clean_sheets=player.clean_sheets,
        yellow_cards=player.yellow_cards,
        red_cards=player.red_cards,
        saves=player.saves,
        minutes_played=player.minutes_played,
        total_points=player.goals * 4,
        team_name=team.name if team else "",
        division=team.division.name if team and team.division else "",
    )


@router.get("/{player_id}/history")
def get_player_history(player_id: int, db: Session = Depends(get_db)):
    """Get player's gameweek history."""
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    points = db.query(PlayerGameweekPoints).filter(
        PlayerGameweekPoints.player_id == player_id,
    ).order_by(PlayerGameweekPoints.gameweek_id.asc()).all()

    history = []
    for pgp in points:
        gw = db.query(Gameweek).filter(Gameweek.id == pgp.gameweek_id).first()
        history.append(PlayerHistoryEntry(
            gameweek=gw.number if gw else 0,
            points=pgp.total_points,
            opponent=pgp.opponent_team or "",
            was_home=pgp.was_home,
            goals_scored=pgp.goals_scored,
            assists=pgp.assists,
            bonus=pgp.bonus_points,
        ))

    return {"player_id": player_id, "player_name": player.name, "history": history}


@router.get("/top")
def get_top_players(
    gameweek_id: Optional[int] = Query(None, description="Gameweek ID for top scorers"),
    limit: int = Query(20, description="Number of players to return"),
    db: Session = Depends(get_db),
):
    """Get top scoring players."""
    if gameweek_id:
        # Top scorers for a specific gameweek
        subquery = (
            db.query(
                PlayerGameweekPoints.player_id,
                func.sum(PlayerGameweekPoints.total_points).label("total_pts"),
            )
            .filter(PlayerGameweekPoints.gameweek_id == gameweek_id)
            .group_by(PlayerGameweekPoints.player_id)
            .order_by(func.sum(PlayerGameweekPoints.total_points).desc())
            .limit(limit)
            .subquery()
        )
        player_ids = [row.player_id for row in db.query(subquery).all()]
        players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    else:
        # Season top scorers
        players = (
            db.query(Player)
            .filter(Player.is_active == True)
            .order_by(Player.goals.desc())
            .limit(limit)
            .all()
        )

    return [
        {
            "id": p.id,
            "name": p.name,
            "team": p.team.name if p.team else "",
            "position": p.position,
            "goals": p.goals,
            "apps": p.apps,
        }
        for p in players
    ]


@router.post("/sync")
def sync_players(db: Session = Depends(get_db)):
    """Sync players from manxfantasyfootball.com."""
    scraper = api_client.ManxFantasyFootballScraper()
    raw_players = scraper.scrape_all_leagues()

    if not raw_players:
        return {"status": "error", "message": "No player data scraped"}

    # Ensure teams exist
    team_cache = {}
    for team_name in set(p["team"] for p in raw_players if p["team"]):
        team = db.query(Team).filter(Team.name == team_name).first()
        if not team:
            # Find or create division
            divisions = db.query(Division).all()
            div = divisions[0] if divisions else None
            team = Team(
                name=team_name,
                short_name=team_name.replace(" First", "").replace(" Combination", ""),
                division_id=div.id if div else None,
            )
            db.add(team)
            db.flush()
        team_cache[team_name] = team

    # Update or create players
    updated = 0
    created = 0
    for raw in raw_players:
        team = team_cache.get(raw["team"])
        if not team:
            continue

        player = db.query(Player).filter(
            Player.name == raw["name"],
            Player.team_id == team.id,
        ).first()

        if not player:
            position = api_client.estimate_player_position(
                raw["name"], raw["goals"], raw["apps"], raw["team"]
            )
            price = api_client.estimate_player_price(
                raw["goals"], raw["apps"], raw["league"], raw["rank"]
            )
            assists = api_client.estimate_assists(raw["goals"], position)

            player = Player(
                name=raw["name"],
                team_id=team.id,
                position=position,
                price=price,
                apps=raw["apps"],
                goals=raw["goals"],
                assists=assists,
                goals_per_game=raw["goals"] / max(raw["apps"], 1),
            )
            db.add(player)
            created += 1
        else:
            # Update stats
            player.apps = raw["apps"]
            player.goals = raw["goals"]
            player.goals_per_game = raw["goals"] / max(raw["apps"], 1)
            updated += 1

    db.commit()
    return {
        "status": "success",
        "players_scraped": len(raw_players),
        "created": created,
        "updated": updated,
        "teams_found": len(team_cache),
    }
