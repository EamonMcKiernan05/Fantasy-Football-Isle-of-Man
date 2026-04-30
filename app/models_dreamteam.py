"""Dream Team model for Fantasy Football Isle of Man.

Top 10 scoring players each gameweek form the Dream Team (no position filter).
"""
from sqlalchemy import Column, Integer, Float, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class DreamTeam(Base):
    """Dream Team player selection for a gameweek.

    Top 10 scoring players each gameweek form the Dream Team.
    No position restrictions.
    """
    __tablename__ = "dream_teams"

    id = Column(Integer, primary_key=True, index=True)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    rank = Column(Integer, nullable=False)  # 1-10 ranking
    points = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    player = relationship("Player")
    gameweek = relationship("Gameweek", overlaps="player_points")

    __table_args__ = (
        UniqueConstraint("gameweek_id", "rank", name="uq_dreamteam_gw_rank"),
    )


class DreamTeamNomination(Base):
    """User's Dream Team nomination for prize draw.

    Managers can nominate one player from the Dream Team
    before the deadline to enter a prize draw.
    """
    __tablename__ = "dream_team_nominations"

    id = Column(Integer, primary_key=True, index=True)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    nominated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("gameweek_id", "fantasy_team_id", name="uq_dt_nomination_gw_team"),
    )
