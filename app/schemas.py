"""Pydantic schemas for request/response validation."""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime, date


# --- Team schemas ---
class TeamBase(BaseModel):
    name: str
    division_id: Optional[int] = None


class TeamResponse(TeamBase):
    id: int
    short_name: Optional[str] = None
    current_position: Optional[int] = None
    current_points: Optional[int] = None
    games_played: Optional[int] = None
    
    class Config:
        from_attributes = True


# --- Division schemas ---
class DivisionBase(BaseModel):
    name: str


class DivisionResponse(DivisionBase):
    id: int
    ft_id: str
    teams: List[TeamResponse] = []
    
    class Config:
        from_attributes = True


# --- User schemas ---
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    
    class Config:
        from_attributes = True


# --- Gameweek schemas ---
class GameweekResponse(BaseModel):
    id: int
    number: int
    season: str
    start_date: date
    deadline: datetime
    bonus_calculated: bool
    closed: bool
    
    class Config:
        from_attributes = True


class GameweekWithFixtures(GameweekResponse):
    fixtures: List["FixtureResponse"] = []


class FixtureResponse(BaseModel):
    id: int
    date: datetime
    home_team: str
    away_team: str
    competition: Optional[str] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    played: bool = False
    
    class Config:
        from_attributes = True


# --- Fantasy Team schemas ---
class SquadPlayerResponse(BaseModel):
    id: int
    team_id: int
    team: TeamResponse
    position: str
    is_captain: bool
    is_vice_captain: bool
    is_active: bool
    total_points: int
    
    class Config:
        from_attributes = True


class FantasyTeamResponse(BaseModel):
    id: int
    name: str
    total_points: int
    rank: Optional[int] = None
    squad: List[SquadPlayerResponse] = []
    
    class Config:
        from_attributes = True


# --- Transfer schemas ---
class TransferRequest(BaseModel):
    team_in_id: int
    team_out_id: int


class CaptainRequest(BaseModel):
    captain_id: int
    vice_captain_id: Optional[int] = None


# --- Gameweek Score schemas ---
class TeamScore(BaseModel):
    team_id: int
    team_name: str
    points: int
    detail: Optional[dict] = None
    captain: bool = False
    fixture_id: Optional[int] = None
    opponent: Optional[str] = None
    is_home: Optional[bool] = None


class GameweekScoreResponse(BaseModel):
    gameweek: int
    total_points: int
    team_scores: List[TeamScore] = []


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    team_name: str
    total_points: int


class LeaderboardResponse(BaseModel):
    season: str
    entries: List[LeaderboardEntry] = []


# --- API Status ---
class StatusResponse(BaseModel):
    status: str
    current_gameweek: Optional[int] = None
    deadline: Optional[datetime] = None
    seasons: List[str] = []


# Fix forward reference
GameweekWithFixtures.model_rebuild()
