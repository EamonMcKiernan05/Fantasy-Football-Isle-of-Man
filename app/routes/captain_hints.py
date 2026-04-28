"""Captain hints API - FPL style recommendations based on form, fixtures, and stats."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List

from app.database import get_db
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Gameweek, Fixture,
    PlayerGameweekPoints, Team,
)

router = APIRouter(prefix="/api/captain", tags=["captain"])


@router.get("/hints/{user_id}")
def get_captain_hints(
    user_id: int,
    gw_id: Optional[int] = Query(None, description="Gameweek ID to get hints for"),
    db: Session = Depends(get_db),
):
    """Get captain hints based on form, fixtures, and player stats.
    
    FPL-style captain recommendation algorithm:
    1. Player form (last 5 GWs average)
    2. Fixture difficulty (next 5 fixtures)
    3. ICT index (Influence + Creativity + Threat)
    4. Ownership percentage (popular picks)
    5. Price (value consideration)
    
    Returns ranked list of squad players with captain suitability score.
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    squad = db.query(SquadPlayer).join(Player).filter(
        SquadPlayer.fantasy_team_id == ft.id,
        Player.is_active == True,
    ).all()
    
    # Get current or target gameweek
    if gw_id:
        current_gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    else:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False,
        ).order_by(Gameweek.number.desc()).first()
    
    if not current_gw:
        return {"hints": [], "message": "No active gameweek"}
    
    # Get fixtures for current GW to assess difficulty
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == current_gw.id,
    ).all()
    
    # Build team difficulty map for this GW
    team_difficulty = {}
    for fx in fixtures:
        if fx.home_team_id:
            team_difficulty[fx.home_team_id] = {
                "difficulty": fx.home_difficulty,
                "is_home": True,
            }
        if fx.away_team_id:
            team_difficulty[fx.away_team_id] = {
                "difficulty": fx.away_difficulty,
                "is_home": False,
            }
    
    # Calculate captain score for each player
    hints = []
    for sp in squad:
        player = sp.player
        if not player:
            continue
        
        # Form score (0-100 scale)
        form_score = min(100, (player.form or 0) * 5)  # Scale form to 0-100
        
        # ICT score (0-100 scale)
        ict_score = min(100, (player.ict_index or 0) / 10)  # Scale ICT to 0-100
        
        # Fixture difficulty score (0-100, higher = easier = better)
        diff_info = team_difficulty.get(player.team_id, {})
        fixture_difficulty = diff_info.get("difficulty", 3)
        is_home = diff_info.get("is_home", True)
        # Lower difficulty = easier = higher score
        fixture_score = (6 - fixture_difficulty) * 20  # 1->100, 2->80, ..., 5->20
        if is_home:
            fixture_score = min(100, fixture_score + 10)  # Home advantage
        
        # Ownership score (0-100 scale)
        ownership_score = min(100, (player.selected_by_percent or 0))
        
        # Total points score (0-100 scale, capped at 150 pts = 100)
        points_score = min(100, (player.total_points_season or 0) / 1.5)
        
        # Weighted captain score
        captain_score = (
            form_score * 0.35 +      # Form is most important
            fixture_score * 0.25 +   # Fixture difficulty
            ict_score * 0.20 +       # ICT index
            ownership_score * 0.10 + # Popularity
            points_score * 0.10,     # Total points
        )
        
        hints.append({
            "player_id": player.id,
            "player_name": player.name,
            "team": player.team.name if player.team else "Unknown",
            "position": player.position,
            "price": player.price,
            "form": round(player.form or 0, 1),
            "ict_index": round(player.ict_index or 0, 1),
            "total_points": player.total_points_season or 0,
            "selected_by_percent": round(player.selected_by_percent or 0, 1),
            "fixture_difficulty": fixture_difficulty,
            "is_home": is_home,
            "has_fixture": player.team_id in team_difficulty,
            "captain_score": round(captain_score, 1),
            "is_current_captain": sp.is_captain,
            "is_current_vice_captain": sp.is_vice_captain,
        })
    
    # Sort by captain score descending
    hints.sort(key=lambda x: x["captain_score"], reverse=True)
    
    return {
        "gameweek": current_gw.number,
        "hints": hints,
        "top_pick": hints[0] if hints else None,
        "current_captain": next(
            (h for h in hints if h["is_current_captain"]),
            None,
        ),
    }


@router.get("/compare/{user_id}")
def compare_captain_options(
    user_id: int,
    player_ids: str = Query(..., description="Comma-separated player IDs to compare"),
    db: Session = Depends(get_db),
):
    """Compare multiple players as captain options side by side.
    
    Returns detailed comparison with:
    - Last 5 GW points
    - Fixture difficulty
    - ICT index breakdown
    - Price/value analysis
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    
    ids = [int(pid.strip()) for pid in player_ids.split(",") if pid.strip()]
    
    players = db.query(Player).filter(
        Player.id.in_(ids),
    ).all()
    
    # Verify all players are in squad
    squad_player_ids = {sp.player_id for sp in ft.squad}
    for p in players:
        if p.id not in squad_player_ids:
            raise HTTPException(
                status_code=400,
                detail=f"{p.name} is not in your squad",
            )
    
    # Get current GW fixtures
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False,
    ).order_by(Gameweek.number.desc()).first()
    
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == current_gw.id if current_gw else None,
    ).all()
    
    comparison = []
    for player in players:
        # Get recent GW points
        recent_points = db.query(PlayerGameweekPoints).filter(
            PlayerGameweekPoints.player_id == player.id,
        ).order_by(PlayerGameweekPoints.gameweek_id.desc()).limit(5).all()
        
        recent_gw_points = [
            {"gw": pg.gameweek_id, "points": pg.total_points}
            for pg in reversed(recent_points)
        ]
        
        # Get fixture difficulty
        diff_info = None
        if current_gw:
            for fx in fixtures:
                if fx.home_team_id == player.team_id:
                    diff_info = {
                        "difficulty": fx.home_difficulty,
                        "is_home": True,
                        "opponent": fx.away_team_name,
                    }
                elif fx.away_team_id == player.team_id:
                    diff_info = {
                        "difficulty": fx.away_difficulty,
                        "is_home": False,
                        "opponent": fx.home_team_name,
                    }
        
        # Calculate captain value score
        form_score = min(100, (player.form or 0) * 5)
        ict_score = min(100, (player.ict_index or 0) / 10)
        fixture_score = (6 - (diff_info["difficulty"] if diff_info else 3)) * 20 if diff_info else 50
        
        value_score = form_score * 0.4 + ict_score * 0.3 + fixture_score * 0.3
        
        comparison.append({
            "player_id": player.id,
            "name": player.name,
            "team": player.team.name if player.team else "Unknown",
            "position": player.position,
            "price": player.price,
            "form": round(player.form or 0, 1),
            "ict_index": round(player.ict_index or 0, 1),
            "influence": round(player.influence or 0, 1),
            "creativity": round(player.creativity or 0, 1),
            "threat": round(player.threat or 0, 1),
            "total_points": player.total_points_season or 0,
            "selected_by_percent": round(player.selected_by_percent or 0, 1),
            "recent_gw_points": recent_gw_points,
            "current_fixture": diff_info,
            "value_score": round(value_score, 1),
            "is_captain": any(
                sp.is_captain for sp in ft.squad if sp.player_id == player.id
            ),
        })
    
    comparison.sort(key=lambda x: x["value_score"], reverse=True)
    
    return {
        "gameweek": current_gw.number if current_gw else None,
        "comparison": comparison,
        "recommendation": comparison[0] if comparison else None,
    }
