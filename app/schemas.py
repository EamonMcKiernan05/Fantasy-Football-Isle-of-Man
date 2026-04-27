"""Pydantic schemas for Fantasy Football Isle of Man API."""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date


# User schemas
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=200)
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Player schemas
class PlayerResponse(BaseModel):
    id: int
    name: str
    team_id: int
    position: str
    price: float
    apps: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    total_points: int = 0
    gw_points: Optional[int] = None
    selected_by_percent: float = 0.0
    form: float = 0.0
    is_injured: bool = False

    class Config:
        from_attributes = True


class PlayerDetailResponse(BaseModel):
    id: int
    name: str
    web_name: Optional[str] = None
    team_id: int
    position: str
    price: float
    price_start: float = 5.0
    price_change: int = 0
    selected_by_percent: float = 0.0
    form: float = 0.0
    apps: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    saves: int = 0
    minutes_played: int = 0
    bonus: int = 0
    total_points: int = 0
    team_name: str = ""
    division: str = ""
    is_injured: bool = False
    injury_status: Optional[str] = None

    class Config:
        from_attributes = True


class PlayerHistoryEntry(BaseModel):
    gameweek: int
    points: int
    opponent: str = ""
    was_home: bool = False
    goals_scored: int = 0
    assists: int = 0
    bonus: int = 0
    minutes: int = 0


# Team schemas
class TeamResponse(BaseModel):
    id: int
    name: str
    short_name: Optional[str] = None
    division_id: Optional[int] = None
    current_position: Optional[int] = None
    current_points: int = 0
    games_played: int = 0
    games_won: int = 0
    games_drawn: int = 0
    games_lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0

    class Config:
        from_attributes = True


class DivisionResponse(BaseModel):
    id: int
    name: str
    teams: List[TeamResponse] = []


# Squad schemas
class SquadPlayerResponse(BaseModel):
    id: int
    player_id: int
    player: Any  # PlayerResponse
    position_slot: int
    is_captain: bool = False
    is_vice_captain: bool = False
    is_starting: bool = True
    total_points: int = 0
    gw_points: int = 0
    was_autosub: bool = False

    class Config:
        from_attributes = True


class ChipStatus(BaseModel):
    wildcard_first_half_used: bool = False
    wildcard_second_half_used: bool = False
    free_hit_used: bool = False
    bench_boost_used: bool = False
    triple_captain_used: bool = False
    active_chip: Optional[str] = None


class FantasyTeamResponse(BaseModel):
    id: int
    name: str
    total_points: int = 0
    overall_rank: Optional[int] = None
    free_transfers: int = 1
    free_transfers_next_gw: int = 1
    budget_remaining: float = 100.0
    chip_status: ChipStatus
    squad: List[SquadPlayerResponse] = []
    current_gw_transfers: int = 0
    transfer_deadline_exceeded: bool = False


# Transfer schemas
class TransferRequest(BaseModel):
    player_in_id: int
    player_out_id: int
    use_wildcard: bool = False


class TransferResponse(BaseModel):
    status: str
    player_in: dict
    player_out: dict
    points_hit: int = 0
    budget_remaining: float
    free_transfers: int
    is_wildcard: bool = False


# Captain/Chip schemas
class CaptainRequest(BaseModel):
    captain_id: int  # SquadPlayer ID
    vice_captain_id: Optional[int] = None


class ChipRequest(BaseModel):
    chip: str  # wildcard, free_hit, bench_boost, triple_captain


# Gameweek schemas
class FixtureResponse(BaseModel):
    id: int
    gameweek: int
    date: datetime
    home_team: str
    away_team: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    played: bool = False
    home_difficulty: int = 3
    away_difficulty: int = 3


class GameweekResponse(BaseModel):
    id: int
    number: int
    season: str
    start_date: date
    end_date: Optional[date] = None
    deadline: datetime
    closed: bool = False
    scored: bool = False
    fixtures: List[FixtureResponse] = []


# Leaderboard schemas
class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    team_name: str
    total_points: int
    gameweek_points: Optional[int] = None
    overall_rank: Optional[int] = None


class LeaderboardResponse(BaseModel):
    season: str
    total_teams: int
    entries: List[LeaderboardEntry] = []


# Mini-league schemas
class MiniLeagueCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    is_h2h: bool = False


class MiniLeagueJoin(BaseModel):
    code: str = Field(..., min_length=5, max_length=10)


class MiniLeagueResponse(BaseModel):
    id: int
    name: str
    code: str
    season: str
    is_h2h: bool = False
    members: List[LeaderboardEntry] = []
    total_members: int = 0


class MiniLeagueMemberResponse(BaseModel):
    fantasy_team_id: int
    username: str
    team_name: str
    total_points: int
    rank: Optional[int] = None


# Season schemas
class SeasonResponse(BaseModel):
    id: int
    name: str
    total_gameweeks: int
    first_half_cutoff: int = 19
    second_half_cutoff: int = 20
    started: bool = False
    finished: bool = False
