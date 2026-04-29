"""Integration tests for new FPL features - endpoints.

Tests for:
- Notifications endpoint
- H2H leagues
- Team details update
- Scoring progress
- Chip activation/cancellation
"""
import pytest
from datetime import datetime, date, timedelta

from app.models import User, FantasyTeam, Gameweek, Fixture, MiniLeague, MiniLeagueMember, Chip, PlayerGameweekPoints, FantasyTeamHistory


class TestNotificationsEndpoint:
    """Test notifications endpoint - returns dynamic notifications."""

    def test_get_notifications_empty(self, client, test_db):
        """Get notifications returns empty list when no data exists."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.get(f"/api/notifications/team/{team.id}")
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "total_count" in data

    def test_get_notifications_with_gw_history(self, client, test_db):
        """Notifications include GW result notifications."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=datetime(2025, 8, 7, 11, 30), closed=True, scored=True)
        session.add_all([team, gw])
        session.flush()

        history = FantasyTeamHistory(fantasy_team=team, gameweek=gw, points=65, total_points=65, rank=1)
        session.add(history)
        session.commit()

        response = client.get(f"/api/notifications/team/{team.id}")
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data

    def test_mark_all_notifications_read(self, client, test_db):
        """Mark all notifications as read."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.post(f"/api/notifications/team/{team.id}/mark-all-read")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "all_marked_read"

    def test_get_upcoming_deadlines(self, client, test_db):
        """Get upcoming deadlines."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.commit()

        response = client.get("/api/notifications/upcoming-deadlines")
        assert response.status_code == 200
        data = response.json()
        assert "upcoming_deadlines" in data


class TestGameweekRecapEndpoint:
    """Test gameweek recap endpoint."""

    def test_gameweek_recap_not_found(self, client, test_db):
        """GW recap returns 404 for non-existent gameweek."""
        response = client.get("/api/gameweeks/99999/recap")
        assert response.status_code == 404

    def test_current_gw_info(self, client, test_db):
        """Get current gameweek info."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.commit()

        response = client.get("/api/gameweek-history/current-gw-info")
        assert response.status_code == 200
        data = response.json()
        assert "gameweek_number" in data
        assert data["gameweek_number"] == 1


class TestH2HLeaguesEndpoint:
    """Test H2H leagues endpoint."""

    def test_h2h_leagues_empty(self, client, test_db):
        """List H2H leagues returns empty when none exist."""
        response = client.get("/api/h2h/leagues")
        assert response.status_code == 200
        data = response.json()
        assert "leagues" in data
        assert len(data["leagues"]) == 0

    def test_create_h2h_league(self, client, test_db):
        """Create an H2H league."""
        response = client.post(
            "/api/h2h/leagues?name=Test+H2H+League&format_type=knockout"
        )
        assert response.status_code == 200
        data = response.json()
        assert "league_id" in data
        assert data["name"] == "Test H2H League"
        assert data["format_type"] == "knockout"

    def test_h2h_bracket_not_found(self, client, test_db):
        """H2H bracket returns 404 for non-existent league."""
        response = client.get("/api/h2h-bracket/99999")
        assert response.status_code == 404


class TestTeamDetailsEndpoint:
    """Test team details edit endpoint."""

    def test_update_team_name(self, client, test_db):
        """Update team name."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.put(
            f"/api/users/{user.id}/team/update?team_name=New+Team+Name"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Team Name"

    def test_get_team_details(self, client, test_db):
        """Get team details."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.get(f"/api/users/{user.id}/team")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Team"


class TestScoringProgressEndpoint:
    """Test scoring progress in gameweek data."""

    def test_scoring_progress_in_gameweek(self, client, test_db):
        """Scoring progress returned in gameweek data."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.flush()

        # Create fixtures (2 played, 2 not)
        for i in range(4):
            fix = Fixture(gameweek=gw, home_team_name=f"Home {i}",
                          away_team_name=f"Away {i}", played=(i < 2),
                          date=future_deadline)
            session.add(fix)
        session.commit()

        # Get current gameweek which includes scoring_progress
        response = client.get("/api/gameweeks/current")
        assert response.status_code == 200
        data = response.json()
        assert "scoring_progress" in data
        assert data["scoring_progress"]["total_fixtures"] == 4
        assert data["scoring_progress"]["completed_fixtures"] == 2
        assert data["scoring_progress"]["percentage"] == 50.0


class TestChipEndpoint:
    """Test chip activation/cancellation endpoints."""

    def test_activate_chip(self, client, test_db):
        """Activate a chip."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=datetime.now() + timedelta(days=7), closed=False)
        session.add_all([team, gw])
        session.commit()

        response = client.post(
            f"/api/users/{user.id}/team/chip",
            json={"chip": "wildcard"}
        )
        assert response.status_code == 200

    def test_get_chips(self, client, test_db):
        """Get chip status for user."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.get(f"/api/users/{user.id}/team/chip")
        assert response.status_code == 200
        data = response.json()
        assert "current_half" in data
        assert "active_chip" in data
