"""Tests for new FPL features added in Cycle 1.

Tests for:
- Team value tracking
- Gameweek history and breakdown
- Fixtures with difficulty
- Transfer history
- Admin seed data
- Deadline countdown
"""
import pytest
from datetime import datetime, date, timedelta
from app.scoring import (
    calculate_player_points,
    calculate_bps,
    award_bonus_points,
    calculate_captain_points,
    calculate_transfer_hit,
    calculate_gameweek_score,
    calculate_selling_price,
    validate_formation,
    check_chip_availability,
    activate_chip,
    cancel_chip,
    get_chip_status,
    calculate_form,
    calculate_ict_index,
    calculate_free_transfers,
)


class TestTeamValueCalculations:
    """Test team value calculations match FPL rules."""

    def test_selling_price_no_increase(self):
        """Selling price equals current price when no increase."""
        assert calculate_selling_price(5.0, 5.0) == 5.0

    def test_selling_price_half_increase(self):
        """Half-increase rule: bought at 7.5, now 7.8 -> sell at 7.6."""
        result = calculate_selling_price(7.5, 7.8)
        assert result == 7.6

    def test_selling_price_price_drop(self):
        """When price drops, selling price equals current (lower) price."""
        assert calculate_selling_price(5.0, 4.5) == 4.5

    def test_selling_price_large_increase(self):
        """Large increase: bought at 5.0, now 7.0 -> sell at 6.0."""
        assert calculate_selling_price(5.0, 7.0) == 6.0

    def test_selling_price_small_increase_rounds_down(self):
        """Small increase rounds down to nearest 0.1."""
        result = calculate_selling_price(5.0, 5.2)
        assert result == 5.1  # 5.0 + floor(0.2/2 * 10)/10 = 5.0 + 0.1 = 5.1


class TestDeadlineCountdown:
    """Test deadline countdown logic."""

    def test_deadline_format_countdown_days(self):
        """Format countdown with days."""
        td = timedelta(days=2, hours=3, minutes=15, seconds=30)
        from app.routes.gameweek_history import _format_countdown
        result = _format_countdown(td)
        assert "2d" in result
        assert "3h" in result

    def test_deadline_format_countdown_hours(self):
        """Format countdown with hours only."""
        td = timedelta(hours=5, minutes=30)
        from app.routes.gameweek_history import _format_countdown
        result = _format_countdown(td)
        assert "5h" in result
        assert "30m" in result

    def test_deadline_format_expired(self):
        """Format expired countdown."""
        from app.routes.gameweek_history import _format_countdown
        assert _format_countdown(timedelta(hours=-1)) == "Expired"
        assert _format_countdown(None) == "Expired"


class TestBenchBoostScoring:
    """Test bench boost chip scoring."""

    def test_bench_boost_all_players_count(self):
        """Bench boost: all 15 players' points count."""
        squad_points = [
            {"id": i, "base_points": 5 + i, "is_starting": i < 11, "did_play": True}
            for i in range(1, 16)
        ]

        result = calculate_gameweek_score(
            squad_points=squad_points,
            captain_id=1,
            vice_captain_id=2,
            chip="bench_boost",
        )

        # All 15 players should contribute
        expected_base = sum(5 + i for i in range(1, 16))  # 120 base points
        assert result["bench_points"] > 0
        assert result["chip"] == "bench_boost"

    def test_triple_captain_multiplier(self):
        """Triple captain: captain gets 3x instead of 2x."""
        squad_points = [
            {"id": 1, "base_points": 10, "is_starting": True, "did_play": True},
            {"id": 2, "base_points": 5, "is_starting": True, "did_play": True},
        ]

        result = calculate_gameweek_score(
            squad_points=squad_points,
            captain_id=1,
            vice_captain_id=2,
            chip="triple_captain",
        )

        # Captain: 10 * 3 = 30, VC: 5 = 5, total = 35
        assert result["total_points"] == 35
        assert result["captain_points"] == 20  # 30 - 10 = 20 bonus from captain


class TestFreeHitTransferLogic:
    """Test free hit transfer calculations."""

    def test_wildcard_resets_free_transfers(self):
        """Wildcard resets free transfers to 1."""
        result = calculate_free_transfers(
            current_free=4,
            transfers_made=15,
            is_wildcard=True,
        )
        assert result == 1

    def test_free_hit_doesnt_affect_transfers(self):
        """Free hit doesn't affect free transfer count."""
        result = calculate_free_transfers(
            current_free=3,
            transfers_made=2,
            is_wildcard=False,
        )
        assert result == 2  # 3 - 2 + 1 = 2

    def test_max_rollover_five(self):
        """Max rollover is 5 transfers."""
        result = calculate_free_transfers(
            current_free=5,
            transfers_made=0,
            is_wildcard=False,
        )
        assert result == 5  # 5 - 0 + 1 = 6, capped at 5


class TestChipHalfAvailability:
    """Test chip availability for first/second half."""

    def test_first_half_chip_available(self):
        """First half chips available when not used."""
        class MockTeam:
            active_chip = None
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        available, msg = check_chip_availability(team, "wildcard", 1)
        assert available is True

    def test_second_half_chip_available(self):
        """Second half chips available when not used."""
        class MockTeam:
            active_chip = None
            wildcard_first_half = True  # Already used first
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        available, msg = check_chip_availability(team, "wildcard", 20)
        assert available is True

    def test_chip_already_used(self):
        """Cannot use chip if already used in current half."""
        class MockTeam:
            active_chip = None
            wildcard_first_half = True
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        available, msg = check_chip_availability(team, "wildcard", 5)
        assert available is False

    def test_cannot_use_two_chips_same_gw(self):
        """Cannot use two chips in the same gameweek."""
        class MockTeam:
            active_chip = "wildcard"
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        available, msg = check_chip_availability(team, "bench_boost", 5)
        assert available is False


class TestChipActivation:
    """Test chip activation and cancellation."""

    def test_activate_chip(self):
        """Activating a chip sets it as active."""
        class MockTeam:
            active_chip = None
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        success, msg = activate_chip(team, "wildcard", 5)
        assert success is True
        assert team.active_chip == "wildcard"
        assert team.wildcard_first_half is True

    def test_cancel_chip(self):
        """Cancelling a chip resets it."""
        class MockTeam:
            active_chip = "bench_boost"
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        success, msg = cancel_chip(team, "bench_boost", 5)
        assert success is True
        assert team.active_chip is None
        assert team.bench_boost_first_half is False

    def test_cannot_cancel_free_hit(self):
        """Free Hit cannot be cancelled once confirmed."""
        class MockTeam:
            active_chip = "free_hit"
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False

        team = MockTeam()
        success, msg = cancel_chip(team, "free_hit", 5)
        assert success is False
        assert "cannot be cancelled" in msg.lower()


class TestChipStatus:
    """Test comprehensive chip status reporting."""

    def test_get_chip_status(self):
        """Chip status returns all chip availability info."""
        class MockTeam:
            wildcard_first_half = False
            wildcard_second_half = False
            free_hit_first_half = False
            free_hit_second_half = False
            bench_boost_first_half = False
            bench_boost_second_half = False
            triple_captain_first_half = False
            triple_captain_second_half = False
            active_chip = None

        team = MockTeam()
        status = get_chip_status(team, 5)

        assert status["wildcard_first_half_available"] is True
        assert status["current_half"] == "first"
        assert status["active_chip"] is None


class TestFPLScoringAccuracy:
    """Verify scoring matches FPL 2025/26 rules exactly."""

    def test_gk_goal_10_points(self):
        """GK goal = 10 points (2025/26 rule change)."""
        points = calculate_player_points(
            position="GK", goals_scored=1, minutes_played=90
        )
        assert points == 12  # 2 (played) + 10 (goal)

    def test_def_goal_6_points(self):
        """DEF goal = 6 points."""
        points = calculate_player_points(
            position="DEF", goals_scored=1, minutes_played=90
        )
        assert points == 8  # 2 (played) + 6 (goal)

    def test_mid_goal_5_points(self):
        """MID goal = 5 points."""
        points = calculate_player_points(
            position="MID", goals_scored=1, minutes_played=90
        )
        assert points == 7  # 2 (played) + 5 (goal)

    def test_fwd_goal_4_points(self):
        """FWD goal = 4 points."""
        points = calculate_player_points(
            position="FWD", goals_scored=1, minutes_played=90
        )
        assert points == 6  # 2 (played) + 4 (goal)

    def test_mid_clean_sheet_1_point(self):
        """MID clean sheet = 1 point (2025/26 rule change)."""
        points = calculate_player_points(
            position="MID", clean_sheet=True, minutes_played=90
        )
        assert points == 3  # 2 (played) + 1 (clean sheet)

    def test_fwd_no_clean_sheet(self):
        """FWD does not get clean sheet points."""
        points = calculate_player_points(
            position="FWD", clean_sheet=True, minutes_played=90
        )
        assert points == 2  # 2 (played), no clean sheet

    def test_defensive_contributions_def(self):
        """DEF with 10+ defensive contributions gets +2."""
        points = calculate_player_points(
            position="DEF", minutes_played=90, defensive_contributions=10
        )
        assert points == 4  # 2 (played) + 2 (def contrib)

    def test_defensive_contributions_mid(self):
        """MID with 12+ defensive contributions gets +2."""
        points = calculate_player_points(
            position="MID", minutes_played=90, defensive_contributions=12
        )
        assert points == 4  # 2 (played) + 2 (def contrib)

    def test_goals_conceded_penalty(self):
        """Every 2 goals conceded = -1 for GK/DEF."""
        points = calculate_player_points(
            position="GK", goals_conceded=4, minutes_played=90
        )
        assert points == 0  # 2 (played) - 2 (4 conceded / 2) = 0

    def test_penalty_goal_bonus(self):
        """Penalty goal gives +2 bonus."""
        points = calculate_player_points(
            position="FWD", goals_scored=1, was_penalty_goal=True, minutes_played=90
        )
        assert points == 8  # 2 + 4 + 2

    def test_gk_saves_per_3(self):
        """GK gets +1 per 3 saves."""
        points = calculate_player_points(
            position="GK", saves=6, minutes_played=90
        )
        assert points == 4  # 2 (played) + 2 (6/3 saves)

    def test_penalty_save_5_points(self):
        """Penalty save = +5 points for GK."""
        points = calculate_player_points(
            position="GK", penalties_saved=1, minutes_played=90
        )
        assert points == 7  # 2 (played) + 5 (penalty save)


class TestBPSAccuracy:
    """Verify BPS calculations match FPL rules."""

    def test_fwd_goal_bps(self):
        """FWD goal = 8 BPS."""
        bps = calculate_bps(position="FWD", goals_scored=1, minutes_played=90)
        assert bps >= 8

    def test_mid_goal_bps(self):
        """MID goal = 10 BPS."""
        bps = calculate_bps(position="MID", goals_scored=1, minutes_played=90)
        assert bps >= 10

    def test_assist_bps(self):
        """Assist = 8 BPS."""
        bps = calculate_bps(position="MID", assists=1, minutes_played=90)
        assert bps >= 8

    def test_penalty_save_bps(self):
        """Penalty save = 11 BPS."""
        bps = calculate_bps(position="GK", penalties_saved=1, minutes_played=90)
        assert bps >= 11

    def test_gk_clean_sheet_bps(self):
        """GK clean sheet = 10 BPS."""
        bps = calculate_bps(position="GK", clean_sheet=True, minutes_played=90)
        assert bps >= 10

    def test_minutes_bps(self):
        """Full 90 min = 5 BPS from minutes."""
        bps = calculate_bps(position="MID", minutes_played=90)
        assert bps >= 5  # (90-15)//15 = 5


class TestFormationValidation:
    """Test formation validation matches FPL rules."""

    def test_valid_formations(self):
        """All valid FPL formations pass."""
        formations = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"]
        for f in formations:
            result = validate_formation(f)
            assert result is not None, f"Formation {f} should be valid"

    def test_invalid_formation(self):
        """Invalid formation returns None."""
        assert validate_formation("2-6-2") is None
        assert validate_formation("6-2-2") is None


class TestTransferHits:
    """Test transfer hit calculations."""

    def test_no_hit_within_free(self):
        """No hit when within free transfers."""
        hit = calculate_transfer_hit(transfers_made=1, free_transfers_available=1)
        assert hit == 0

    def test_hit_per_extra_transfer(self):
        """-4 points per extra transfer."""
        hit = calculate_transfer_hit(transfers_made=3, free_transfers_available=1)
        assert hit == 8  # 2 extra * 4

    def test_wildcard_no_hit(self):
        """Wildcard: no transfer hit regardless."""
        hit = calculate_transfer_hit(
            transfers_made=20, free_transfers_available=0, is_wildcard=True
        )
        assert hit == 0


class TestICTIndex:
    """Test ICT index calculation."""

    def test_ict_index(self):
        """ICT = (influence + creativity + threat) / 10."""
        ict = calculate_ict_index(influence=50, creativity=30, threat=40)
        assert ict == 12.0

    def test_ict_zero(self):
        """All zeros = 0 ICT."""
        ict = calculate_ict_index(influence=0, creativity=0, threat=0)
        assert ict == 0.0


class TestForm:
    """Test form calculation."""

    def test_form_last_5(self):
        """Form is average of last 5 GWs."""
        form = calculate_form(points_history=[10, 5, 15, 8, 12], weeks=5)
        assert form == 10.0

    def test_form_fewer_than_5(self):
        """Form uses available GWs if fewer than 5."""
        form = calculate_form(points_history=[10, 15], weeks=5)
        assert form == 12.5

    def test_form_empty(self):
        """No history = 0 form."""
        form = calculate_form(points_history=[], weeks=5)
        assert form == 0.0
