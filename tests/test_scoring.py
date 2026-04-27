"""Comprehensive tests for Fantasy Football IOM."""
import sys
import os
import pytest
import json
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, SessionLocal, init_db
from app.models import (
    League, Division, Team, Player, Gameweek, Fixture,
    User, FantasyTeam, SquadPlayer, PlayerGameweekPoints,
    FantasyTeamHistory, Transfer, MiniLeague, MiniLeagueMember, Season,
)
from app import scoring


# --- Scoring Tests ---

class TestFPLScoring:
    """Test FPL-accurate scoring engine."""

    def test_gk_save(self):
        pts = scoring.calculate_player_points(position="GK", saves=3, minutes_played=90)
        assert pts == 5  # 2 (60+ min) + 3 (saves)

    def test_gk_clean_sheet(self):
        pts = scoring.calculate_player_points(position="GK", clean_sheet=True, minutes_played=90)
        assert pts == 6  # 2 + 4

    def test_gk_goal(self):
        pts = scoring.calculate_player_points(position="GK", goals_scored=1, minutes_played=90)
        assert pts == 8  # 2 + 6

    def test_gk_penalty_save(self):
        pts = scoring.calculate_player_points(position="GK", penalties_saved=1, minutes_played=90)
        assert pts == 7  # 2 + 5

    def test_gk_penalty_miss(self):
        pts = scoring.calculate_player_points(position="GK", penalties_missed=1, minutes_played=90)
        assert pts == 0  # 2 - 2

    def test_gk_conceded_penalty(self):
        pts = scoring.calculate_player_points(position="GK", goals_conceded=5, minutes_played=90)
        assert pts == -1  # 2 - 3 (max penalty)

    def test_def_goal(self):
        pts = scoring.calculate_player_points(position="DEF", goals_scored=1, minutes_played=90)
        assert pts == 8  # 2 + 6

    def test_def_assist(self):
        pts = scoring.calculate_player_points(position="DEF", assists=1, minutes_played=90)
        assert pts == 5  # 2 + 3

    def test_def_clean_sheet(self):
        pts = scoring.calculate_player_points(position="DEF", clean_sheet=True, minutes_played=90)
        assert pts == 6  # 2 + 4

    def test_def_goals_conceded(self):
        pts = scoring.calculate_player_points(position="DEF", goals_conceded=3, minutes_played=90)
        assert pts == -1  # 2 - 3

    def test_mid_goal(self):
        pts = scoring.calculate_player_points(position="MID", goals_scored=1, minutes_played=90)
        assert pts == 7  # 2 + 5

    def test_mid_assist(self):
        pts = scoring.calculate_player_points(position="MID", assists=1, minutes_played=90)
        assert pts == 5  # 2 + 3

    def test_mid_clean_sheet(self):
        pts = scoring.calculate_player_points(position="MID", clean_sheet=True, minutes_played=90)
        assert pts == 5  # 2 + 3

    def test_fwd_goal(self):
        pts = scoring.calculate_player_points(position="FWD", goals_scored=1, minutes_played=90)
        assert pts == 6  # 2 + 4

    def test_fwd_assist(self):
        pts = scoring.calculate_player_points(position="FWD", assists=1, minutes_played=90)
        assert pts == 5  # 2 + 3

    def test_fwd_no_clean_sheet(self):
        pts = scoring.calculate_player_points(position="FWD", clean_sheet=True, minutes_played=90)
        assert pts == 2  # Only participation bonus

    def test_yellow_card(self):
        pts = scoring.calculate_player_points(position="MID", yellow_card=True, minutes_played=90)
        assert pts == 1  # 2 - 1

    def test_red_card(self):
        pts = scoring.calculate_player_points(position="MID", red_card=True, minutes_played=90)
        assert pts == -1  # 2 - 3

    def test_own_goal(self):
        pts = scoring.calculate_player_points(position="DEF", own_goal=True, minutes_played=90)
        assert pts == 0  # 2 - 2

    def test_penalty_goal_bonus(self):
        pts = scoring.calculate_player_points(
            position="FWD", goals_scored=1, minutes_played=90, was_penalty_goal=True
        )
        assert pts == 8  # 2 + 4 + 2

    def test_participation_bonus(self):
        pts = scoring.calculate_player_points(position="FWD", minutes_played=60)
        assert pts == 2
        pts_under = scoring.calculate_player_points(position="FWD", minutes_played=59)
        assert pts_under == 0

    def test_complex_def(self):
        pts = scoring.calculate_player_points(
            position="DEF", goals_scored=1, assists=1, clean_sheet=True,
            goals_conceded=0, minutes_played=90,
        )
        assert pts == 15  # 2 + 6 + 3 + 4

    def test_complex_mid(self):
        pts = scoring.calculate_player_points(
            position="MID", goals_scored=2, assists=1, clean_sheet=True,
            minutes_played=90, bonus_points=3,
        )
        assert pts == 21  # 2 + 10 + 3 + 3 + 3

    def test_full_game_gk(self):
        pts = scoring.calculate_player_points(
            position="GK", goals_scored=0, assists=0, clean_sheet=True,
            goals_conceded=0, saves=4, minutes_played=90, bonus_points=2,
        )
        assert pts == 12  # 2 (participation) + 4 (clean sheet) + 4 (saves) + 2 (bonus)


class TestBPSSystem:
    """Test Bonus Points System."""

    def test_bps_goal_fwd(self):
        bps = scoring.calculate_bps(position="FWD", goals_scored=1, minutes_played=90)
        assert bps > 0

    def test_bps_goal_mid(self):
        bps = scoring.calculate_bps(position="MID", goals_scored=1, minutes_played=90)
        assert bps > 0

    def test_bps_clean_sheet_gk(self):
        bps = scoring.calculate_bps(position="GK", clean_sheet=True, minutes_played=90)
        assert bps > 0

    def test_bps_saves(self):
        bps = scoring.calculate_bps(position="GK", saves=5, minutes_played=90)
        assert bps >= 10

    def test_bps_negative(self):
        bps = scoring.calculate_bps(position="DEF", yellow_card=True, red_card=True, goals_conceded=3, minutes_played=90)
        assert bps < 10

    def test_award_bonus_top3(self):
        players = [
            {"player_id": 1, "bps": 50},
            {"player_id": 2, "bps": 40},
            {"player_id": 3, "bps": 30},
            {"player_id": 4, "bps": 20},
            {"player_id": 5, "bps": 10},
        ]
        bonus = scoring.award_bonus_points(players)
        assert bonus[1] == 3
        assert bonus[2] == 2
        assert bonus[3] == 1
        assert 4 not in bonus
        assert 5 not in bonus


class TestCaptainSystem:
    """Test captain multiplier."""

    def test_captain_double(self):
        pts = scoring.calculate_captain_points(10, True)
        assert pts == 20

    def test_captain_triple(self):
        pts = scoring.calculate_captain_points(10, True, chip="triple_captain")
        assert pts == 30

    def test_non_captain(self):
        pts = scoring.calculate_captain_points(10, False)
        assert pts == 10

    def test_non_captain_triple(self):
        pts = scoring.calculate_captain_points(10, False, chip="triple_captain")
        assert pts == 10


class TestTransferHits:
    """Test transfer hit calculation."""

    def test_free_transfer(self):
        hit = scoring.calculate_transfer_hit(1, 1)
        assert hit == 0

    def test_extra_transfer(self):
        hit = scoring.calculate_transfer_hit(3, 1)
        assert hit == 8  # 2 extra * 4

    def test_wildcard(self):
        hit = scoring.calculate_transfer_hit(10, 0, is_wildcard=True)
        assert hit == 0

    def test_no_hit_within_free(self):
        hit = scoring.calculate_transfer_hit(2, 3)
        assert hit == 0


class TestGameweekScore:
    """Test full gameweek score calculation."""

    def test_basic_team_score(self):
        squad = [
            {"id": 1, "base_points": 6, "is_starting": True, "did_play": True},
            {"id": 2, "base_points": 5, "is_starting": True, "did_play": True},
            {"id": 3, "base_points": 0, "is_starting": False, "did_play": True},
        ]
        result = scoring.calculate_gameweek_score(
            squad_points=squad,
            captain_id=1,
            vice_captain_id=2,
        )
        assert result["total_points"] == 17


class TestPriceChanges:
    """Test player price calculations."""

    def test_price_increase(self):
        new_price = scoring.update_player_price(60, 5.0, 5.0)
        assert new_price > 5.0

    def test_price_decrease(self):
        new_price = scoring.update_player_price(-60, 2.0, 5.0)
        assert new_price <= 5.0

    def test_price_min(self):
        new_price = scoring.update_player_price(-100, 0, 1.0)
        assert new_price >= 1.0

    def test_price_max(self):
        new_price = scoring.update_player_price(100, 10, 15.0)
        assert new_price <= 15.0


class TestForm:
    """Test form calculation."""

    def test_form_calculation(self):
        form = scoring.calculate_form([5, 8, 3, 7, 6])
        assert form == 5.8

    def test_form_few_games(self):
        form = scoring.calculate_form([5, 8])
        assert form == 6.5


# --- Formation and Auto-Sub Tests ---

class TestFormations:
    """Test formation validation."""

    def test_valid_formations(self):
        for f in scoring.VALID_FORMATIONS:
            result = scoring.validate_formation(f["name"])
            assert result is not None
            assert result["def"] + result["mid"] + result["fwd"] == 10  # 10 + 1 GK = 11

    def test_invalid_formation(self):
        assert scoring.validate_formation("6-2-2") is None
        assert scoring.validate_formation("2-8-0") is None
        assert scoring.validate_formation("") is None

    def test_all_formations_have_11(self):
        for f in scoring.VALID_FORMATIONS:
            assert f["def"] + f["mid"] + f["fwd"] == 10  # Plus 1 GK = 11

    def test_validate_starting_xi_valid(self):
        """Test that a valid 4-3-3 XI passes validation."""
        formation = scoring.validate_formation("4-3-3")
        squad = []
        # 1 GK
        squad.append({"is_starting": True, "player": {"position": "GK"}})
        # 4 DEF
        for _ in range(4):
            squad.append({"is_starting": True, "player": {"position": "DEF"}})
        # 3 MID
        for _ in range(3):
            squad.append({"is_starting": True, "player": {"position": "MID"}})
        # 3 FWD
        for _ in range(3):
            squad.append({"is_starting": True, "player": {"position": "FWD"}})
        # Bench players
        squad.append({"is_starting": False, "player": {"position": "GK"}})
        squad.append({"is_starting": False, "player": {"position": "DEF"}})
        squad.append({"is_starting": False, "player": {"position": "DEF"}})
        squad.append({"is_starting": False, "player": {"position": "MID"}})
        squad.append({"is_starting": False, "player": {"position": "MID"}})
        squad.append({"is_starting": False, "player": {"position": "FWD"}})

        assert scoring.validate_starting_xi(squad, formation) is True

    def test_validate_starting_xi_wrong_count(self):
        formation = scoring.validate_formation("4-3-3")
        squad = []
        squad.append({"is_starting": True, "player": {"position": "GK"}})
        for _ in range(5):  # 5 DEF instead of 4
            squad.append({"is_starting": True, "player": {"position": "DEF"}})
        for _ in range(3):
            squad.append({"is_starting": True, "player": {"position": "MID"}})
        for _ in range(3):
            squad.append({"is_starting": True, "player": {"position": "FWD"}})

        assert scoring.validate_starting_xi(squad, formation) is False

    def test_validate_starting_xi_no_gk(self):
        formation = scoring.validate_formation("4-3-3")
        squad = []
        # No GK
        for _ in range(4):
            squad.append({"is_starting": True, "player": {"position": "DEF"}})
        for _ in range(3):
            squad.append({"is_starting": True, "player": {"position": "MID"}})
        for _ in range(4):
            squad.append({"is_starting": True, "player": {"position": "FWD"}})

        assert scoring.validate_starting_xi(squad, formation) is False


class TestAutoSub:
    """Test FPL-style auto-sub logic."""

    def _make_squad(self):
        """Create a standard 15-player squad for 4-3-3 (11 starters + 4 bench)."""
        squad = []
        players = [
            ("GK", 1, True), ("GK", 15, False),
            ("DEF", 2, True), ("DEF", 3, True), ("DEF", 4, True), ("DEF", 5, True),
            ("DEF", 16, False),
            ("MID", 6, True), ("MID", 7, True), ("MID", 8, True),
            ("MID", 9, False),
            ("FWD", 11, True), ("FWD", 12, True), ("FWD", 13, True), ("FWD", 14, False),
        ]
        for pos, pid, is_starting in players:
            squad.append({
                "player_id": pid,
                "player": {"position": pos},
                "is_starting": is_starting,
            })
        return squad

    def test_no_subs_needed(self):
        squad = self._make_squad()
        formation = scoring.validate_formation("4-3-3")
        result = scoring.auto_sub_squad(squad, [], formation)
        starters = [sp for sp in result if sp["is_starting"]]
        assert len(starters) == 11
        # No autosub flags set
        for sp in result:
            assert sp.get("was_autosubbed") is not True

    def test_fwd_out_mid_in(self):
        squad = self._make_squad()
        formation = scoring.validate_formation("4-3-3")
        result = scoring.auto_sub_squad(squad, [11], formation)
        subbed_out = next(sp for sp in result if sp["player_id"] == 11)
        assert subbed_out["is_starting"] is False
        assert subbed_out.get("was_autosubbed") is True

    def test_gk_out_gk_in(self):
        squad = self._make_squad()
        formation = scoring.validate_formation("4-3-3")
        result = scoring.auto_sub_squad(squad, [1], formation)
        subbed_out = next(sp for sp in result if sp["player_id"] == 1)
        subbed_in = next(sp for sp in result if sp["player_id"] == 15)
        assert subbed_out["is_starting"] is False
        assert subbed_in["is_starting"] is True

    def test_def_flex_mid(self):
        squad = self._make_squad()
        formation = scoring.validate_formation("4-3-3")
        result = scoring.auto_sub_squad(squad, [2], formation)
        subbed_out = next(sp for sp in result if sp["player_id"] == 2)
        assert subbed_out["is_starting"] is False

    def test_multiple_subs(self):
        squad = self._make_squad()
        formation = scoring.validate_formation("4-3-3")
        result = scoring.auto_sub_squad(squad, [11, 8, 2], formation)
        for pid in [11, 8, 2]:
            sp = next(sp for sp in result if sp["player_id"] == pid)
            assert sp["is_starting"] is False, f"Player {pid} should be benched"


class TestFreeTransfers:
    """Test free transfer calculation."""

    def test_wildcard_resets(self):
        assert scoring.calculate_free_transfers(0, 5, is_wildcard=True) == 2

    def test_rollover(self):
        # Start with 2 free, make 0, get 1, cap at 2
        assert scoring.calculate_free_transfers(2, 0) == 2

    def test_use_one_get_one(self):
        # Start with 2, use 1, get 1, still 2
        assert scoring.calculate_free_transfers(2, 1) == 2

    def test_use_all(self):
        # Start with 2, use 3 (1 hit), get 1
        assert scoring.calculate_free_transfers(2, 3) == 1


# --- Database Model Tests ---

class TestModels:
    """Test database models."""

    def setup_method(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def test_create_user(self):
        db = SessionLocal()
        user = User(username="test", email="test@test.com", password_hash="hash")
        db.add(user)
        db.commit()
        assert user.id is not None
        db.close()

    def test_create_team(self):
        db = SessionLocal()
        league = League(ft_id="9057188", name="IOM Senior")
        db.add(league)
        db.flush()
        division = Division(ft_id="123", name="Premier", league_id=league.id)
        db.add(division)
        db.flush()
        team = Team(name="Laxey FC", division_id=division.id)
        db.add(team)
        db.commit()
        assert team.id is not None
        assert team.name == "Laxey FC"
        db.close()

    def test_create_player(self):
        db = SessionLocal()
        league = League(ft_id="9057188", name="IOM Senior")
        db.add(league)
        db.flush()
        division = Division(ft_id="123", name="Premier", league_id=league.id)
        db.add(division)
        db.flush()
        team = Team(name="Laxey FC", division_id=division.id)
        db.add(team)
        db.flush()
        player = Player(name="John Smith", team_id=team.id, position="FWD", price=5.5)
        db.add(player)
        db.commit()
        assert player.id is not None
        assert player.position == "FWD"
        assert player.price == 5.5
        db.close()

    def test_fantasy_team_chips(self):
        db = SessionLocal()
        user = User(username="test", email="test@test.com", password_hash="hash")
        db.add(user)
        db.flush()
        ft = FantasyTeam(user_id=user.id, name="Test FC", season="2025-26")
        db.add(ft)
        db.commit()
        assert ft.wildcard_first_half is False
        assert ft.wildcard_second_half is False
        assert ft.free_hit_used is False
        assert ft.bench_boost_used is False
        assert ft.triple_captain_used is False
        assert ft.free_transfers == 1
        assert ft.budget_remaining == 100.0
        db.close()

    def test_mini_league(self):
        db = SessionLocal()
        user = User(username="admin", email="admin@test.com", password_hash="hash")
        db.add(user)
        db.flush()
        ml = MiniLeague(name="Office League", code="ABC12345", season="2025-26", admin_user_id=user.id)
        db.add(ml)
        db.commit()
        assert ml.id is not None
        assert ml.code == "ABC12345"
        db.close()

    def test_squad_player_constraints(self):
        db = SessionLocal()
        user = User(username="test", email="test@test.com", password_hash="hash")
        db.add(user)
        db.flush()
        ft = FantasyTeam(user_id=user.id, name="Test", season="2025-26")
        db.add(ft)
        db.flush()
        sp = SquadPlayer(fantasy_team_id=ft.id, player_id=1, position_slot=1, is_captain=True)
        db.add(sp)
        db.flush()
        assert sp.position_slot == 1
        db.close()


# --- API Integration Tests (with proper temp file DB fixture) ---

@pytest.fixture(scope="function")
def test_db():
    """Create temp file-based SQLite database for tests (avoids in-memory per-conn issue)."""
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    test_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSessionLocal()
    yield test_engine, db
    db.close()
    test_engine.dispose()
    os.unlink(path)


@pytest.fixture(scope="function")
def client(test_db):
    """Test client with overridden DB dependency."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    _, session = test_db

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestAPIEndpoints:
    """Test API endpoints."""

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_register_user(self, client):
        response = client.post("/api/users/register", json={
            "username": "testuser",
            "email": "test@test.com",
            "password": "password123",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert "id" in data

    def test_register_duplicate_username(self, client):
        client.post("/api/users/register", json={
            "username": "testuser",
            "email": "test@test.com",
            "password": "password123",
        })
        response = client.post("/api/users/register", json={
            "username": "testuser",
            "email": "test2@test.com",
            "password": "password123",
        })
        assert response.status_code == 400

    def test_login(self, client):
        client.post("/api/users/register", json={
            "username": "testuser",
            "email": "test@test.com",
            "password": "password123",
        })
        response = client.post("/api/users/login", data={
            "username": "testuser",
            "password": "password123",
        })
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"

    def test_leaderboard_empty(self, client):
        response = client.get("/api/leaderboard/")
        assert response.status_code == 200
        assert response.json()["entries"] == []

    def test_gameweeks_empty(self, client):
        response = client.get("/api/gameweeks/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_players_empty(self, client):
        response = client.get("/api/players/")
        assert response.status_code == 200
        assert response.json() == []

    def test_mini_leagues_create(self, client, test_db):
        from app.models import FantasyTeam

        _, db = test_db

        # Create user
        user_resp = client.post("/api/users/register", json={
            "username": "leagueadmin",
            "email": "admin@test.com",
            "password": "password123",
        })
        user_id = user_resp.json()["id"]

        # Create fantasy team directly in DB (skip player selection for test)
        ft = FantasyTeam(user_id=user_id, name="Test FC", season="2025-26")
        db.add(ft)
        db.commit()

        # Create league
        import time
        response = client.post(
            f"/api/leagues/?user_id={user_id}",
            json={"name": f"Test League {time.time()}", "is_h2h": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert "code" in data
        assert len(data["code"]) == 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
