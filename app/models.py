"""SQLAlchemy models for Fantasy Football Isle of Man."""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey,
    DateTime, Date, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class League(Base):
    """IOM League from FullTime API."""
    __tablename__ = "leagues"
    
    id = Column(Integer, primary_key=True, index=True)
    ft_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    divisions = relationship("Division", back_populates="league")


class Division(Base):
    """Division within a league."""
    __tablename__ = "divisions"
    
    id = Column(Integer, primary_key=True, index=True)
    ft_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    league = relationship("League", back_populates="divisions")
    teams = relationship("Team", back_populates="division")


class Team(Base):
    """Real football team from IOM leagues."""
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    division_id = Column(Integer, ForeignKey("divisions.id"))
    division = relationship("Division", back_populates="teams")
    
    # Team info
    short_name = Column(String(50))
    
    # Current season stats (updated from API)
    current_position = Column(Integer, nullable=True)
    current_points = Column(Integer, default=0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_drawn = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)
    goal_difference = Column(Integer, default=0)


class Gameweek(Base):
    """A gameweek/round of fixtures."""
    __tablename__ = "gameweeks"
    
    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False)
    season = Column(String(20), nullable=False)  # e.g. "2025-26"
    
    start_date = Column(Date, nullable=False)
    deadline = Column(DateTime, nullable=False)
    bonus_calculated = Column(Boolean, default=False)
    closed = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    fixtures = relationship("Fixture", back_populates="gameweek")
    player_fixtures = relationship("PlayerFixture", back_populates="gameweek")
    
    __table_args__ = (
        UniqueConstraint("number", "season", name="uq_gameweek_number_season"),
    )


class Fixture(Base):
    """A real match from the IOM leagues."""
    __tablename__ = "fixtures"
    
    id = Column(Integer, primary_key=True, index=True)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"))
    gameweek = relationship("Gameweek", back_populates="fixtures")
    
    date = Column(DateTime, nullable=False)
    home_team = Column(String(200), nullable=False)
    away_team = Column(String(200), nullable=False)
    competition = Column(String(200), nullable=True)
    
    # Results (populated after match)
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    half_time_home = Column(Integer, nullable=True)
    half_time_away = Column(Integer, nullable=True)
    
    played = Column(Boolean, default=False)


class User(Base):
    """A fantasy football manager."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Fantasy team
    fantasy_team = relationship("FantasyTeam", back_populates="user", uselist=False)
    transfers_used = Column(Integer, default=0)


class FantasyTeam(Base):
    """A user's fantasy team (squad of real IOM teams)."""
    __tablename__ = "fantasy_teams"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="fantasy_team")
    
    name = Column(String(100), nullable=False)
    season = Column(String(20), nullable=False)
    total_points = Column(Integer, default=0)
    rank = Column(Integer, nullable=True)
    
    # Squad
    squad = relationship("SquadPlayer", back_populates="fantasy_team")
    history = relationship("FantasyTeamHistory", back_populates="fantasy_team")


class SquadPlayer(Base):
    """A team in the user's fantasy squad."""
    __tablename__ = "squad_players"
    
    id = Column(Integer, primary_key=True, index=True)
    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"))
    fantasy_team = relationship("FantasyTeam", back_populates="squad")
    
    team_id = Column(Integer, ForeignKey("teams.id"))
    team = relationship("Team")
    
    position = Column(String(20), nullable=False)  # GK, DEF, MID, FWD (based on team type)
    is_captain = Column(Boolean, default=False)
    is_vice_captain = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    # Total points from this team in fantasy
    total_points = Column(Integer, default=0)


class PlayerFixture(Base):
    """Points scored by a squad team in a gameweek."""
    __tablename__ = "player_fixtures"
    
    id = Column(Integer, primary_key=True, index=True)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"))
    gameweek = relationship("Gameweek", back_populates="player_fixtures")
    
    squad_player_id = Column(Integer, ForeignKey("squad_players.id"))
    squad_player = relationship("SquadPlayer")
    
    # The real fixture this player was involved in
    fixture_id = Column(Integer, ForeignKey("fixtures.id"), nullable=True)
    fixture = relationship("Fixture")
    
    # Points breakdown
    points = Column(Integer, default=0)
    bonus_points = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    
    # Detailed stats
    minutes = Column(Integer, default=90)  # Teams always play 90
    goals_scored = Column(Integer, default=0)
    clean_sheet = Column(Boolean, default=False)
    goals_conceded = Column(Integer, default=0)
    
    was_home = Column(Boolean, default=True)
    opponent = Column(String(200))


class FantasyTeamHistory(Base):
    """Gameweek-by-gameweek history for a fantasy team."""
    __tablename__ = "fantasy_team_history"
    
    id = Column(Integer, primary_key=True, index=True)
    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"))
    fantasy_team = relationship("FantasyTeam", back_populates="history")
    
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"))
    gameweek = relationship("Gameweek")
    
    points = Column(Integer, default=0)
    rank = Column(Integer, nullable=True)
    transferred_in = Column(Integer, default=0)
    transferred_out = Column(Integer, default=0)


class Transfer(Base):
    """A transfer made by a user."""
    __tablename__ = "transfers"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"))
    
    team_in_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team_in = relationship("Team", foreign_keys=[team_in_id])
    
    team_out_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team_out = relationship("Team", foreign_keys=[team_out_id])
    
    points_scored = Column(Integer, nullable=True)  # Points the outgoing team had scored
    made_before_deadline = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
