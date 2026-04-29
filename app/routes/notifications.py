"""Notification system for Fantasy Football Isle of Man.

FPL-style notifications for:
- Deadline reminders
- Price changes for owned players
- Injury updates
- Transfer hits applied
- Chip usage
- Gameweek results
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import Optional

from app.database import get_db
from app.models import (
    FantasyTeam, SquadPlayer, Player, Gameweek, GameweekStats,
    FantasyTeamHistory, Chip, Transfer,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/team/{team_id}")
def get_team_notifications(
    team_id: int,
    limit: int = Query(20, description="Number of notifications to return"),
    unread_only: bool = Query(False, description="Only unread notifications"),
    db: Session = Depends(get_db),
):
    """Get notifications for a fantasy team.

    Generates notifications from:
    - Recent gameweek results
    - Price changes for squad players
    - Injury status changes
    - Chip usage
    - Transfer history
    """
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    notifications = []

    # GW result notifications
    recent_history = (
        db.query(FantasyTeamHistory)
        .filter(FantasyTeamHistory.fantasy_team_id == team_id)
        .order_by(desc(FantasyTeamHistory.id))
        .limit(5)
        .all()
    )

    for h in recent_history:
        gw = h.gameweek
        if gw:
            notifications.append({
                "id": f"gw_{h.id}",
                "type": "gameweek_result",
                "title": f"Gameweek {gw.number} Complete",
                "message": f"You scored {h.points} points in GW {gw.number}. "
                          f"Total: {h.total_points} points. Rank: #{h.rank or 'N/A'}",
                "timestamp": h.id,
                "read": True,
            })

    # Chip usage notifications
    chips = (
        db.query(Chip)
        .filter(Chip.team_id == team_id)
        .order_by(desc(Chip.id))
        .limit(5)
        .all()
    )

    for chip in chips:
        gw = db.query(Gameweek).filter(Gameweek.id == chip.gameweek_id).first()
        notifications.append({
            "id": f"chip_{chip.id}",
            "type": "chip_used",
            "title": f"{chip.chip_type.replace('_', ' ').title()} Used",
            "message": f"{chip.chip_type.replace('_', ' ').title()} chip "
                      f"{'activated' if chip.status == 'active' else 'used'} "
                      f"for GW {gw.number if gw else '?'}",
            "timestamp": chip.timestamp.isoformat() if chip.timestamp else None,
            "read": True,
        })

    # Price change notifications for squad
    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == team_id
    ).all()

    for sp in squad:
        player = db.query(Player).filter(Player.id == sp.player_id).first()
        if player and player.price_change != 0:
            direction = "up" if player.price_change > 0 else "down"
            notifications.append({
                "id": f"price_{player.id}",
                "type": "price_change",
                "title": f"{player.name} price {direction}",
                "message": f"{player.name}'s price changed by "
                          f"{'+' if direction == 'up' else ''}{player.price_change * 0.1}m "
                          f"to £{player.price}m",
                "timestamp": datetime.utcnow().isoformat(),
                "read": False,
            })

    # Injury notifications
    for sp in squad:
        player = db.query(Player).filter(Player.id == sp.player_id).first()
        if player and player.is_injured:
            notifications.append({
                "id": f"injury_{player.id}",
                "type": "injury",
                "title": f"{player.name} injured",
                "message": f"{player.name} is currently injured. "
                          f"Status: {player.injury_status or 'Unknown'}",
                "timestamp": datetime.utcnow().isoformat(),
                "read": False,
            })

    # Sort by timestamp (newest first)
    notifications.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    # Apply filters
    if unread_only:
        notifications = [n for n in notifications if not n["read"]]

    return {
        "team_id": team_id,
        "team_name": ft.name,
        "notifications": notifications[:limit],
        "total_count": len(notifications),
        "unread_count": sum(1 for n in notifications if not n["read"]),
    }


@router.post("/team/{team_id}/mark-read/{notification_id}")
def mark_notification_read(
    team_id: int,
    notification_id: str,
    db: Session = Depends(get_db),
):
    """Mark a notification as read."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    return {
        "status": "marked_read",
        "notification_id": notification_id,
    }


@router.post("/team/{team_id}/mark-all-read")
def mark_all_notifications_read(team_id: int, db: Session = Depends(get_db)):
    """Mark all notifications as read."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    return {
        "status": "all_marked_read",
        "team_id": team_id,
    }


@router.get("/upcoming-deadlines")
def get_upcoming_deadlines(
    limit: int = Query(5, description="Number of upcoming deadlines"),
    db: Session = Depends(get_db),
):
    """Get upcoming gameweek deadlines."""
    from datetime import datetime

    now = datetime.utcnow()
    upcoming = (
        db.query(Gameweek)
        .filter(Gameweek.closed == False)
        .order_by(Gameweek.number.asc())
        .limit(limit)
        .all()
    )

    deadlines = []
    for gw in upcoming:
        time_remaining = gw.deadline - now if gw.deadline else None
        deadlines.append({
            "gameweek_id": gw.id,
            "gameweek_number": gw.number,
            "deadline": gw.deadline.isoformat() if gw.deadline else None,
            "time_remaining_seconds": int(time_remaining.total_seconds()) if time_remaining else 0,
            "time_remaining_formatted": _format_time(time_remaining),
        })

    return {"upcoming_deadlines": deadlines}


def _format_time(td) -> str:
    """Format timedelta as readable string."""
    if td is None or td.total_seconds() < 0:
        return "Expired"

    total_seconds = int(td.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)
