"""SQLAlchemy models for Fantasy Football Isle of Man.

Player-based FPL system - each manager picks individual players from IOM leagues.
Matches FPL 2025/26 rules as closely as possible.

FPL 2025/26 Key Rules:
- Squad: 15 players (2 GK, 5 DEF, 5 MID, 3 FWD), £100m budget
- Max 3 players per club
- 1 free transfer per GW, rollover max 4 (max 5 total with current GW)
- Max 20 transfers per GW (excluding chips)
- Wildcard: 2x/season (GW 1-19 and GW 20-38)
- Free Hit: 2x/season (GW 1-19 and GW 20-38)
- Bench Boost: 2x/season (GW 1-19 and GW 20-38)
- Triple Captain: 2x/season (GW 1-19 and GW 20-38)
- Player price: +£0.1m per 50% ownership increase, -£0.1m per 50% decrease
- Half-increase rule: selling price = purchase_price + floor((current_price - purchase_price) / 2)
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey,
    DateTime, Date, Text, UniqueConstraint, CheckConstraint,
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
    name = Column(String(200), nullable=False, index=True)
    short_name = Column(String(50))
    code = Column(String(10))  # FPL-style 3-letter team code
    division_id = Column(Integer, ForeignKey("divisions.id"))
    division = relationship("Division", back_populates="teams")

    # Season stats from FullTime API
    current_position = Column(Integer, nullable=True)
    current_points = Column(Integer, default=0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_drawn = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)
    goals_for = Column(Integer, default=0)
    goals_against = Column(Integer, default=0)
    goal_difference = Column(Integer, default=0)

    # FPL-style strength of schedule (1-5)
    strength_attack = Column(Integer, default=5)
    strength_home = Column(Integer, default=5)
    strength_away = Column(Integer, default=5)
    strength_defense = Column(Integer, default=5)

    players = relationship("Player", back_populates="team")


class Player(Base):
    """Individual player from IOM leagues.

    FPL-style player with position, price, and season stats.
    """
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    web_name = Column(String(100))  # URL-friendly name
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    team = relationship("Team", back_populates="players")

    # FPL-style position: GK, DEF, MID, FWD
    position = Column(String(3), nullable=False, index=True)

    # FPL-style price in millions (e.g. 5.0 = 5.0m, increments of 0.1m)
    price = Column(Float, default=5.0, nullable=False)
    price_start = Column(Float, default=5.0)  # Starting price for the season
    price_change = Column(Integer, default=0)  # Integer for 0.1m increments (positive/negative)
    price_change_event = Column(Integer, default=0)  # Price change last GW
    price_change_fall = Column(Integer, default=0)  # Negative change (integer)
    price_change_total = Column(Integer, default=0)  # Total change from start (integer)

    # Selection stats (FPL-style)
    selected_by_percent = Column(Float, default=0.0)  # % of managers owning
    form = Column(Float, default=0.0)  # Average points over last 5 GWs
    in_dreamteam = Column(Boolean, default=False)  # Was in any dream team this season

    # Season stats
    apps = Column(Integer, default=0)  # appearances
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    clean_sheets = Column(Integer, default=0)
    yellow_cards = Column(Integer, default=0)
    red_cards = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    minutes_played = Column(Integer, default=0)
    bonus = Column(Integer, default=0)  # Total bonus points
    goals_conceded = Column(Integer, default=0)
    own_goals = Column(Integer, default=0)
    penalties_saved = Column(Integer, default=0)
    penalties_missed = Column(Integer, default=0)
    influence = Column(Float, default=0.0)
    creativity = Column(Float, default=0.0)
    threat = Column(Float, default=0.0)
    ict_index = Column(Float, default=0.0)

    # Derived stats
    goals_per_game = Column(Float, default=0.0)
    total_points_season = Column(Integer, default=0)

    # Transfers in/out (FPL style)
    transfers_in = Column(Integer, default=0)  # Managers adding this player
    transfers_out = Column(Integer, default=0)  # Managers dropping this player

    # Status
    is_active = Column(Boolean, default=True)
    is_injured = Column(Boolean, default=False)
    injury_status = Column(String(50))  # e.g., "Out", "Doubt"
    injury_return = Column(Date)  # Expected return date
    now_playing = Column(Boolean, default=True)

    # Gameweek history
    gameweek_points = relationship("PlayerGameweekPoints", back_populates="player")
    squad_entries = relationship("SquadPlayer", back_populates="player")
    price_history = relationship("PlayerPriceHistory", back_populates="player")

    __table_args__ = (
        CheckConstraint("position IN ('GK', 'DEF', 'MID', 'FWD')", name="chk_position"),
    )


class Gameweek(Base):
    """A gameweek/round of fixtures."""
    __tablename__ = "gameweeks"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, nullable=False)
    season = Column(String(20), nullable=False)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    deadline = Column(DateTime, nullable=False)

    # FPL: gameweek is "closed" after deadline
    bonus_calculated = Column(Boolean, default=False)
    closed = Column(Boolean, default=False)
    scored = Column(Boolean, default=False)
    chip_processing_done = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    fixtures = relationship("Fixture", back_populates="gameweek")
    player_points = relationship("PlayerGameweekPoints")
    team_history = relationship("FantasyTeamHistory", back_populates="gameweek")

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
    home_team_name = Column(String(200), nullable=False, index=True)
    away_team_name = Column(String(200), nullable=False, index=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    competition = Column(String(200), nullable=True)
    division_name = Column(String(200), nullable=True)

    # Results
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    half_time_home = Column(Integer, nullable=True)
    half_time_away = Column(Integer, nullable=True)

    # Goalscorers (JSON)
    home_scorers = Column(Text, nullable=True)
    away_scorers = Column(Text, nullable=True)

    # FPL-style difficulty rating (1-5)
    home_difficulty = Column(Integer, default=3)
    away_difficulty = Column(Integer, default=3)

    played = Column(Boolean, default=False)


class User(Base):
    """A fantasy football manager."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    fantasy_team = relationship("FantasyTeam", back_populates="user", uselist=False)
    transfers_history = relationship("Transfer", back_populates="user")


class FantasyTeam(Base):
    """A user's fantasy team (squad of individual players).

    FPL 2025/26 rules:
    - 15 players max, £100m budget
    - 1 free transfer per GW, rollover max 4 (max 5 total)
    - 2 wildcards per season (GW 1-19 and GW 20-38)
    - 2 free hits per season (GW 1-19 and GW 20-38)
    - 2 bench boosts per season (GW 1-19 and GW 20-38)
    - 2 triple captains per season (GW 1-19 and GW 20-38)
    - Max 20 transfers per GW (excluding chips)
    """
    __tablename__ = "fantasy_teams"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="fantasy_team")

    name = Column(String(100), nullable=False)
    season = Column(String(20), nullable=False)

    # FPL-style budget (100.0m total)
    budget = Column(Float, default=100.0)
    budget_remaining = Column(Float, default=100.0)

    total_points = Column(Integer, default=0)
    overall_rank = Column(Integer, nullable=True)
    league_rank = Column(Integer, nullable=True)

    # Transfers: 1 free per GW, max 4 rollover (5 total with current GW)
    free_transfers = Column(Integer, default=1)
    free_transfers_next_gw = Column(Integer, default=1)
    current_gw_transfers = Column(Integer, default=0)
    transfer_deadline_exceeded = Column(Boolean, default=False)
    rollover_transfers = Column(Integer, default=0)  # Rolled over from previous GW

    # FPL 2025/26: ALL chips are 2x per season (1 per half)
    # Wildcard: 2 per season (first half GW 1-19, second half GW 20-38)
    wildcard_first_half = Column(Boolean, default=False)
    wildcard_second_half = Column(Boolean, default=False)

    # Free Hit: 2 per season (first half GW 1-19, second half GW 20-38)
    free_hit_first_half = Column(Boolean, default=False)
    free_hit_second_half = Column(Boolean, default=False)

    # Bench Boost: 2 per season (first half GW 1-19, second half GW 20-38)
    bench_boost_first_half = Column(Boolean, default=False)
    bench_boost_second_half = Column(Boolean, default=False)

    # Triple Captain: 2 per season (first half GW 1-19, second half GW 20-38)
    triple_captain_first_half = Column(Boolean, default=False)
    triple_captain_second_half = Column(Boolean, default=False)

    # Active chip this gameweek (can be cancelled before deadline)
    active_chip = Column(String(20), nullable=True)

    # Free Hit: store original squad to revert next GW
    free_hit_backup = Column(Text, nullable=True)  # JSON backup of original squad
    free_hit_revert_gw = Column(Integer, nullable=True)  # GW number to revert to

    # Squad
    squad = relationship("SquadPlayer", back_populates="fantasy_team")
    history = relationship("FantasyTeamHistory", back_populates="fantasy_team")

    # Mini-league membership
    mini_league_memberships = relationship("MiniLeagueMember", back_populates="fantasy_team")
    chips = relationship("Chip", back_populates="team")

    __table_args__ = (
        UniqueConstraint("user_id", "season", name="uq_user_season_team"),
    )


class SquadPlayer(Base):
    """A player in a user's fantasy squad."""
    __tablename__ = "squad_players"

    id = Column(Integer, primary_key=True, index=True)
    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    fantasy_team = relationship("FantasyTeam", back_populates="squad")

    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    player = relationship("Player", back_populates="squad_entries")

    # Position slot: 1=GK(start), 2-6=DEF(start), 7-11=MID(start), 12-14=FWD(start)
    # 15=GK(bench), 16-17=DEF(bench), 18-19=MID(bench), 20=FWD(bench)
    position_slot = Column(Integer, nullable=False)

    is_captain = Column(Boolean, default=False)
    is_vice_captain = Column(Boolean, default=False)
    is_starting = Column(Boolean, default=True)

    # FPL-style: purchase price for half-increase rule
    purchase_price = Column(Float, default=0.0)  # Price when bought by this manager
    selling_price = Column(Float, default=0.0)   # Selling price (current or half-increase)

    # Total points accumulated for this manager
    total_points = Column(Integer, default=0)

    # Gameweek points for current GW
    gw_points = Column(Integer, default=0)

    # Was this player an auto-sub?
    was_autosub = Column(Boolean, default=False)

    # Bench priority (FPL style: lower number = higher priority for auto-sub)
    bench_priority = Column(Integer, default=99)

    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("fantasy_team_id", "player_id", name="uq_team_player"),
        CheckConstraint("position_slot BETWEEN 1 AND 20", name="chk_position_slot"),
    )


class PlayerGameweekPoints(Base):
    """Points scored by a player in a specific gameweek.

    Core scoring table - recalculated each gameweek based on fixtures.
    """
    __tablename__ = "player_gameweek_points"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    player = relationship("Player", back_populates="gameweek_points")

    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    gameweek = relationship("Gameweek", overlaps="player_points")

    # Match context
    opponent_team = Column(String(200), nullable=True)
    was_home = Column(Boolean, default=False)
    minutes_played = Column(Integer, default=0)
    did_play = Column(Boolean, default=False)

    # Raw stats for this gameweek
    goals_scored = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    clean_sheet = Column(Boolean, default=False)
    goals_conceded = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    yellow_card = Column(Boolean, default=False)
    red_card = Column(Boolean, default=False)
    own_goal = Column(Boolean, default=False)
    penalties_saved = Column(Integer, default=0)
    penalties_missed = Column(Integer, default=0)
    bonus_points = Column(Integer, default=0)
    was_penalty_goal = Column(Boolean, default=False)

    # Scoring
    base_points = Column(Integer, default=0)
    total_points = Column(Integer, default=0)

    # BPS (Bonus Points System)
    bps_score = Column(Integer, default=0)

    # ICT components for this gameweek
    influence_gw = Column(Float, default=0.0)
    creativity_gw = Column(Float, default=0.0)
    threat_gw = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("player_id", "gameweek_id", name="uq_player_gw"),
    )


class FantasyTeamHistory(Base):
    """Weekly history for a fantasy team."""
    __tablename__ = "fantasy_team_history"

    id = Column(Integer, primary_key=True, index=True)
    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    fantasy_team = relationship("FantasyTeam", back_populates="history")

    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"))
    gameweek = relationship("Gameweek", back_populates="team_history")

    points = Column(Integer, default=0)
    point_rank = Column(Integer, nullable=True)
    point_rank_sort_index = Column(Integer, nullable=True)
    total_points = Column(Integer, default=0)  # Cumulative
    rank = Column(Integer, nullable=True)  # Overall rank after GW
    rank_sort_index = Column(Integer, nullable=True)
    transferred_in = Column(Integer, default=0)  # FPL H2H style
    transferred_out = Column(Integer, default=0)
    chip_used = Column(String(20), nullable=True)  # Chip activated this GW
    new_entries_count = Column(Integer, default=0)
    entered = Column(Boolean, default=True)

    transfers_made = Column(Integer, default=0)
    transfers_cost = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("fantasy_team_id", "gameweek_id", name="uq_team_gw_history"),
    )


class Transfer(Base):
    """Transfer record."""
    __tablename__ = "transfers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="transfers_history")

    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=True)

    player_in_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    player_in = relationship("Player", foreign_keys=[player_in_id])
    player_out_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    player_out = relationship("Player", foreign_keys=[player_out_id])

    points_scored_by_outgoing = Column(Integer, default=0)
    is_wildcard = Column(Boolean, default=False)
    is_free_hit = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class MiniLeague(Base):
    """Private mini-league (FPL style)."""
    __tablename__ = "mini_leagues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(10), unique=True, nullable=False, index=True)  # Invite code
    season = Column(String(20), nullable=False)
    is_h2h = Column(Boolean, default=False)  # Head-to-head mode
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin = relationship("User", foreign_keys=[admin_user_id])

    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("MiniLeagueMember", back_populates="mini_league")


class MiniLeagueMember(Base):
    """Membership in a mini-league."""
    __tablename__ = "mini_league_members"

    id = Column(Integer, primary_key=True, index=True)
    mini_league_id = Column(Integer, ForeignKey("mini_leagues.id"), nullable=False)
    mini_league = relationship("MiniLeague", back_populates="members")

    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    fantasy_team = relationship("FantasyTeam", back_populates="mini_league_memberships")

    rank = Column(Integer, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("mini_league_id", "fantasy_team_id", name="uq_ml_member"),
    )


class Season(Base):
    """Season configuration."""
    __tablename__ = "seasons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(20), unique=True, nullable=False)  # e.g., "2025-26"
    total_gameweeks = Column(Integer, default=38)
    first_half_cutoff = Column(Integer, default=19)  # Wildcard phase boundary
    second_half_cutoff = Column(Integer, default=20)

    started = Column(Boolean, default=False)
    finished = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class H2hLeague(Base):
    """Head-to-Head league container."""
    __tablename__ = "h2h_leagues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    season = Column(String(20), nullable=False)
    format_type = Column(String(20), default="round_robin")  # round_robin, knockout
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started = Column(Boolean, default=False)
    group_stage_rounds = Column(Integer, default=0)
    knockout_stage = Column(Boolean, default=False)
    invite_code = Column(String(10), unique=True, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    participants = relationship("H2hParticipant", back_populates="h2h_league")
    matches = relationship("H2hMatch", back_populates="h2h_league")


class H2hParticipant(Base):
    """A fantasy team participating in an H2H league."""
    __tablename__ = "h2h_participants"

    id = Column(Integer, primary_key=True, index=True)
    h2h_league_id = Column(Integer, ForeignKey("h2h_leagues.id"), nullable=False)
    h2h_league = relationship("H2hLeague", back_populates="participants")

    fantasy_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    fantasy_team = relationship("FantasyTeam")

    # H2H record
    h2h_points = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    draws = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    byes = Column(Integer, default=0)
    goal_difference = Column(Integer, default=0)  # Total GW points diff across matches

    __table_args__ = (
        UniqueConstraint("h2h_league_id", "fantasy_team_id", name="uq_h2h_participant"),
    )


class H2hMatch(Base):
    """An H2H matchup between two fantasy teams."""
    __tablename__ = "h2h_matches"

    id = Column(Integer, primary_key=True, index=True)
    h2h_league_id = Column(Integer, ForeignKey("h2h_leagues.id"), nullable=False)
    h2h_league = relationship("H2hLeague", back_populates="matches")

    gameweek_number = Column(Integer, nullable=False)
    participant_a_id = Column(Integer, ForeignKey("h2h_participants.id"), nullable=False)
    participant_b_id = Column(Integer, ForeignKey("h2h_participants.id"), nullable=False)

    participant_a = relationship("H2hParticipant", foreign_keys=[participant_a_id])
    participant_b = relationship("H2hParticipant", foreign_keys=[participant_b_id])

    # Match result
    score_a = Column(Integer, nullable=True)
    score_b = Column(Integer, nullable=True)
    status = Column(String(20), default="pending")  # pending, finished, bye, cancelled
    result = Column(String(10), nullable=True)  # win_a, win_b, draw, bye_a, bye_b

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "h2h_league_id", "gameweek_number", "participant_a_id", "participant_b_id",
            name="uq_h2h_match",
        ),
    )


class Chip(Base):
    """FPL 2025/26: All chips available 2x per season (1 per half)."""
    __tablename__ = "chips"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    chip_type = Column(String(20), nullable=False)  # wildcard, free_hit, bench_boost, triple_captain
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    status = Column(String(20), default="active")  # active, deactivated, used
    timestamp = Column(DateTime, default=datetime.utcnow)

    team = relationship("FantasyTeam", back_populates="chips")
    gameweek = relationship("Gameweek", overlaps="player_points")


class PlayerPriceHistory(Base):
    """Track price changes for each player per gameweek."""
    __tablename__ = "player_price_history"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    old_price = Column(Float, nullable=False)
    new_price = Column(Float, nullable=False)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="price_history")
    gameweek = relationship("Gameweek", overlaps="player_points")


class GameweekStats(Base):
    """Per-player stats for each gameweek - FPL scoring data."""
    __tablename__ = "gameweek_stats"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    gameweek_id = Column(Integer, ForeignKey("gameweeks.id"), nullable=False)
    points = Column(Integer, default=0)
    goals = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    clean_sheets = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    bps = Column(Integer, default=0)  # Bonus Points System
    minutes_played = Column(Integer, default=0)
    was_captain = Column(Boolean, default=False)
    yellow_cards = Column(Integer, default=0)
    red_cards = Column(Integer, default=0)
    penalty_missed = Column(Boolean, default=False)
    own_goals = Column(Integer, default=0)
    influence = Column(Float, default=0.0)
    creativity = Column(Float, default=0.0)
    threat = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player")
    gameweek = relationship("Gameweek", overlaps="player_points")
