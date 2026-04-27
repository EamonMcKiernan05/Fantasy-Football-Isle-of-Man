"""Gameweek recap API routes - FPL-style summary pages."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.database import get_db
from app.models import (
    Player, Gameweek, GameweekStats, FantasyTeam, SquadPlayer,
    Chip, PlayerPriceHistory, H2hMatch
)
from app.schemas import GameweekRecapResponse, PlayerComparisonResponse

router = APIRouter()


@router.get("/{gameweek_id}/recap", response_model=GameweekRecapResponse)
def get_gameweek_recap(
    gameweek_id: int,
    db: Session = Depends(get_db)
):
    """Get a comprehensive recap of a completed gameweek.

    FPL-style summary including:
    - Top scorers
    - Captain with most points
    - Average points
    - Best transfers
    - Price changes
    - H2H results
    - Most owned players
    """
    gameweek = db.query(Gameweek).filter(Gameweek.id == gameweek_id).first()
    if not gameweek:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    # Top scorers
    stats = db.query(GameweekStats).filter(
        GameweekStats.gameweek_id == gameweek_id
    ).order_by(desc(GameweekStats.points)).limit(20).all()

    top_scorers = []
    for stat in stats:
        player = db.query(Player).filter(Player.player_id == stat.player_id).first()
        if player:
            top_scorers.append({
                "player_id": player.player_id,
                "player_name": f"{player.first_name} {player.last_name}",
                "team": player.team,
                "position": player.position,
                "points": stat.points,
                "goals": stat.goals or 0,
                "assists": stat.assists or 0,
                "clean_sheets": stat.clean_sheets or 0,
                "saves": stat.saves or 0,
                "bonus": stat.bps or 0,
                "was_captain": stat.was_captain or False,
                "minutes": stat.minutes_played or 0
            })

    # Captain points leaders
    captain_stats = db.query(GameweekStats).filter(
        GameweekStats.gameweek_id == gameweek_id,
        GameweekStats.was_captain == True
    ).order_by(desc(GameweekStats.points)).limit(10).all()

    captain_leaders = []
    for stat in captain_stats:
        player = db.query(Player).filter(Player.player_id == stat.player_id).first()
        if player:
            captain_leaders.append({
                "player_id": player.player_id,
                "player_name": f"{player.first_name} {player.last_name}",
                "team": player.team,
                "points": stat.points
            })

    # Average points
    avg_points = db.query(func.avg(GameweekStats.points)).filter(
        GameweekStats.gameweek_id == gameweek_id
    ).scalar() or 0

    # Most owned players
    total_teams = db.query(FantasyTeam).count()
    ownership = db.query(SquadPlayer).join(Player).group_by(
        SquadPlayer.player_id
    ).with_entities(
        SquadPlayer.player_id,
        Player.first_name,
        Player.last_name,
        Player.team,
        Player.position,
        func.count(SquadPlayer.team_id).label("team_count")
    ).order_by(desc("team_count")).limit(20).all()

    most_owned = []
    for row in ownership:
        pct = (row.team_count / total_teams * 100) if total_teams > 0 else 0
        most_owned.append({
            "player_id": row.player_id,
            "player_name": f"{row.first_name} {row.last_name}",
            "team": row.team,
            "position": row.position,
            "ownership_count": row.team_count,
            "ownership_pct": round(pct, 1)
        })

    # Price changes this GW
    price_changes = db.query(PlayerPriceHistory).join(Player).filter(
        PlayerPriceHistory.gameweek_id == gameweek_id
    ).order_by(
        (PlayerPriceHistory.new_price - PlayerPriceHistory.old_price).desc()
    ).limit(20).all()

    price_changes_data = []
    for pc in price_changes:
        change = pc.new_price - pc.old_price
        if abs(change) >= 0.1:
            price_changes_data.append({
                "player_id": pc.player_id,
                "player_name": f"{pc.player.first_name} {pc.player.last_name}",
                "team": pc.player.team,
                "old_price": pc.old_price,
                "new_price": pc.new_price,
                "change": change
            })

    # H2H matches this GW
    h2h_matches = db.query(H2hMatch).filter(
        H2hMatch.gameweek_id == gameweek_id,
        H2hMatch.completed == True
    ).all()

    h2h_results = []
    for match in h2h_matches:
        home_team = db.query(FantasyTeam).filter(FantasyTeam.id == match.team1_id).first()
        away_team = db.query(FantasyTeam).filter(FantasyTeam.id == match.team2_id).first()
        if home_team and away_team:
            h2h_results.append({
                "match_id": match.id,
                "team1": home_team.team_name,
                "team1_points": match.team1_points,
                "team2": away_team.team_name,
                "team2_points": match.team2_points,
                "winner": "draw" if match.team1_points == match.team2_points else (
                    "team1" if match.team1_points > match.team2_points else "team2"
                )
            })

    # Chips used this GW
    chips_used = db.query(Chip).filter(Chip.gameweek_id == gameweek_id).all()
    chips_data = []
    for chip in chips_used:
        team = db.query(FantasyTeam).filter(FantasyTeam.id == chip.team_id).first()
        if team:
            chips_data.append({
                "team": team.team_name,
                "chip_type": chip.chip_type,
                "gameweek_id": chip.gameweek_id
            })

    # Gameweek leaderboard (top teams this GW)
    gw_scores = db.query(GameweekStats).join(Player, Player.player_id == GameweekStats.player_id)\
        .join(SquadPlayer, SquadPlayer.player_id == GameweekStats.player_id)\
        .filter(
            GameweekStats.gameweek_id == gameweek_id,
            SquadPlayer.is_active == True
        ).group_by(SquadPlayer.team_id).with_entities(
            SquadPlayer.team_id,
            func.sum(GameweekStats.points).label("total_points")
        ).order_by(desc("total_points")).limit(10).all()

    leaderboard = []
    for row in gw_scores:
        team = db.query(FantasyTeam).filter(FantasyTeam.id == row.team_id).first()
        if team:
            leaderboard.append({
                "team_name": team.team_name,
                "owner": team.user.username if team.user else "Unknown",
                "points": row.total_points
            })

    return GameweekRecapResponse(
        gameweek_id=gameweek_id,
        gameweek_name=gameweek.name,
        status=gameweek.status,
        top_scorers=top_scorers,
        captain_leaders=captain_leaders,
        average_points=round(avg_points, 1),
        most_owned=most_owned,
        price_changes=price_changes_data,
        h2h_results=h2h_results,
        chips_used=chips_data,
        leaderboard=leaderboard
    )


@router.get("/player-comparison", response_model=List[PlayerComparisonResponse])
def compare_players(
    player_ids: str = Query(..., description="Comma-separated player IDs to compare (2-5)"),
    gameweeks: int = Query(5, description="Number of gameweeks to compare"),
    db: Session = Depends(get_db)
):
    """Compare multiple players side by side.

    FPL-style comparison showing:
    - Recent form (last N gameweeks)
    - Season totals
    - Ownership percentage
    - Price change trend
    - Expected points
    """
    ids = [int(pid.strip()) for pid in player_ids.split(",") if pid.strip()]
    if len(ids) < 2 or len(ids) > 5:
        raise HTTPException(status_code=400, detail="Compare 2-5 players")

    # Get current gameweek
    current_gw = db.query(Gameweek).order_by(desc(Gameweek.id)).first()
    if not current_gw:
        raise HTTPException(status_code=404, detail="No gameweeks found")

    results = []
    for player_id in ids:
        player = db.query(Player).filter(Player.player_id == player_id).first()
        if not player:
            continue

        # Recent form
        stats = db.query(GameweekStats).filter(
            GameweekStats.player_id == player_id,
            GameweekStats.gameweek_id > current_gw.id - gameweeks
        ).order_by(GameweekStats.gameweek_id).all()

        form_points = [s.points for s in stats]

        # Season totals
        season_stats = db.query(func.sum(GameweekStats.points), func.sum(GameweekStats.goals),
                                func.sum(GameweekStats.assists), func.count()).filter(
            GameweekStats.player_id == player_id
        ).first()

        # Ownership
        total_teams = db.query(FantasyTeam).count()
        owned_by = db.query(SquadPlayer).filter(
            SquadPlayer.player_id == player_id,
            SquadPlayer.is_active == True
        ).count()

        # Price history
        price_hist = db.query(PlayerPriceHistory).filter(
            PlayerPriceHistory.player_id == player_id
        ).order_by(desc(PlayerPriceHistory.timestamp)).limit(5).all()

        results.append(PlayerComparisonResponse(
            player_id=player_id,
            player_name=f"{player.first_name} {player.last_name}",
            team=player.team,
            position=player.position,
            price=player.price,
            total_points=season_stats[0] or 0,
            goals=season_stats[1] or 0,
            assists=season_stats[2] or 0,
            games_played=season_stats[3] or 0,
            form=round(sum(form_points) / len(form_points), 1) if form_points else 0,
            recent_points=form_points,
            ownership_pct=round((owned_by / total_teams * 100), 1) if total_teams > 0 else 0,
            price_history=[
                {"gameweek_id": h.gameweek_id, "old_price": h.old_price, "new_price": h.new_price}
                for h in reversed(price_hist)
            ]
        ))

    return results
