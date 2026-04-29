"""Gameweek recap routes for Fantasy Football Isle of Man."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Gameweek, PlayerGameweekPoints, Player, Fixture, FantasyTeamHistory

router = APIRouter(prefix="/api/gameweeks", tags=["gameweek-recap"])


@router.get("/{gw_id}/recap")
def get_gameweek_recap(gw_id: int, db: Session = Depends(get_db)):
    """Get a detailed recap of a completed gameweek."""
    gw = db.query(Gameweek).filter(Gameweek.id == gw_id).first()
    if not gw:
        raise HTTPException(status_code=404, detail="Gameweek not found")

    player_points = db.query(PlayerGameweekPoints).filter(
        PlayerGameweekPoints.gameweek_id == gw_id,
        PlayerGameweekPoints.did_play == True,
    ).all()

    # Get player details
    player_ids = [pp.player_id for pp in player_points]
    players = {p.id: p for p in db.query(Player).filter(Player.id.in_(player_ids)).all()} if player_ids else {}

    # Top scorers (limit 5)
    top_scorers = sorted(player_points, key=lambda p: p.total_points, reverse=True)[:5]

    # Average score
    avg_score = round(sum(p.total_points for p in player_points) / max(len(player_points), 1), 1)

    # Highest scoring fixture
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()

    highest_fixture = None
    highest_fixture_total = 0
    for f in fixtures:
        fixture_pts = sum(
            p.total_points for p in player_points
            if p.opponent_team in (f.home_team_name, f.away_team_name)
        )
        if fixture_pts > highest_fixture_total:
            highest_fixture_total = fixture_pts
            highest_fixture = {
                "home": f.home_team_name,
                "away": f.away_team_name,
                "score": f"{f.home_score}-{f.away_score}",
                "total_points": fixture_pts,
            }

    # Most assists
    top_assists = sorted(player_points, key=lambda p: p.assists, reverse=True)[:3]

    # Most saves (GKs)
    top_saves = sorted(
        [p for p in player_points if p.saves and p.saves > 0],
        key=lambda p: p.saves,
        reverse=True,
    )[:3]

    # History stats
    histories = db.query(FantasyTeamHistory).filter(
        FantasyTeamHistory.gameweek_id == gw_id
    ).all()

    team_stats = {
        "teams_scored": len(histories),
        "avg_team_score": round(sum(h.points for h in histories) / max(len(histories), 1), 1),
        "highest_team_score": max((h.points for h in histories), default=0),
        "chips_played": sum(1 for h in histories if h.chip_used),
    }

    def _player_info(pp):
        player = players.get(pp.player_id)
        return {
            "player_id": pp.player_id,
            "player_name": player.name if player else "Unknown",
            "team_name": player.team.name if player and player.team else "",
            "position": player.position if player else "",
        }

    return {
        "gameweek": {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "start_date": gw.start_date.isoformat() if gw.start_date else None,
            "end_date": gw.end_date.isoformat() if gw.end_date else None,
            "closed": gw.closed,
            "scored": gw.scored,
        },
        "summary": {
            "total_players_scored": len(player_points),
            "average_score": avg_score,
            "highest_fixture": highest_fixture,
        },
        "top_scorers": [
            {
                **_player_info(p),
                "points": p.total_points,
                "goals": p.goals_scored,
                "assists": p.assists,
                "bonus": p.bonus_points,
            }
            for p in top_scorers
        ],
        "top_assists": [
            {
                **_player_info(p),
                "assists": p.assists,
            }
            for p in top_assists
        ],
        "top_saves": [
            {
                **_player_info(p),
                "saves": p.saves,
            }
            for p in top_saves
        ],
        "team_stats": team_stats,
    }
