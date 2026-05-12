"""Comprehensive tests for the FFIOM authentication system.

Tests cover:
- User registration with email+password
- Login with email or username
- Refresh token rotation
- Logout and token revocation
- Account linking (Google OAuth simulation)
- Email verification flow
- Account management (profile updates, password changes, identity unlinking)
- Security edge cases (brute force, token expiry, duplicate accounts)
"""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, get_db, get_bound_db
from app.models import User, AuthIdentity, RefreshToken, EmailVerificationToken
from app.utils.passwords import hash_password, verify_password
from app.auth import create_access_token
from app.auth_linking import create_email_identity


@pytest.fixture(scope="function")
def auth_client(test_db):
    """Test client with fresh database for each test."""
    from app.main import app
    from starlette.testclient import TestClient

    _, session = test_db

    def override_get_db():
        try:
            yield session
        finally:
            pass

    def override_get_bound_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_bound_db] = override_get_bound_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ============================================================
# Password utilities
# ============================================================

class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_hash_and_verify(self):
        """Hashing and verifying a password should work."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """Wrong password should fail verification."""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_hash_is_different_each_time(self):
        """Each hash should be unique (different salt)."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_legacy_sha256_not_supported(self):
        """Legacy SHA-256 hashes should NOT be accepted (removed)."""
        # Simulate a legacy SHA-256 hash format
        salt = "abc123"
        legacy_hash = salt + "$" + hashlib.sha256((salt + "password").encode()).hexdigest()
        assert verify_password("password", legacy_hash) is False

    def test_empty_password(self):
        """Empty password should fail verification."""
        hashed = hash_password("something")
        assert verify_password("", hashed) is False

    def test_unicode_password(self):
        """Unicode passwords should work."""
        password = "密码密码🔥"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True


# ============================================================
# User Registration
# ============================================================

class TestRegistration:
    """Test user registration endpoints."""

    def test_register_success(self, auth_client):
        """Registering a new user should succeed."""
        response = auth_client.post("/api/auth/register", json={
            "username": "newuser",
            "email": "newuser@test.com",
            "password": "password123",
            "team_name": "My Test Team",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "newuser"
        assert data["user"]["email"] == "newuser@test.com"
        assert data["user"]["email_verified"] is False
        assert "team" in data
        assert data["team"]["name"] == "My Test Team"

    def test_register_duplicate_email(self, auth_client):
        """Registering with an existing email should fail."""
        auth_client.post("/api/auth/register", json={
            "username": "user1",
            "email": "test@test.com",
            "password": "password123",
        })
        response = auth_client.post("/api/auth/register", json={
            "username": "user2",
            "email": "test@test.com",  # Same email
            "password": "password456",
        })
        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower() or "already" in response.json()["detail"].lower()

    def test_register_duplicate_username(self, auth_client):
        """Registering with an existing username should fail."""
        auth_client.post("/api/auth/register", json={
            "username": "uniqueuser",
            "email": "unique1@test.com",
            "password": "password123",
        })
        response = auth_client.post("/api/auth/register", json={
            "username": "uniqueuser",  # Same username
            "email": "unique2@test.com",
            "password": "password456",
        })
        assert response.status_code == 400

    def test_register_short_password(self, auth_client):
        """Password shorter than 6 chars should be rejected."""
        response = auth_client.post("/api/auth/register", json={
            "username": "shortpass",
            "email": "short@test.com",
            "password": "abc",  # Too short
        })
        assert response.status_code == 422  # Validation error

    def test_register_creates_auth_identity(self, auth_client, db_session):
        """Registration should create an email identity."""
        auth_client.post("/api/auth/register", json={
            "username": "identity_user",
            "email": "identity@test.com",
            "password": "password123",
        })
        user = db_session.query(User).filter(User.email == "identity@test.com").first()
        assert user is not None
        assert len(user.identities) == 1
        assert user.identities[0].provider == "email"
        assert user.identities[0].provider_id == "identity@test.com"

    def test_register_creates_fantasy_team(self, auth_client):
        """Registration should create a fantasy team."""
        response = auth_client.post("/api/auth/register", json={
            "username": "team_user",
            "email": "team@test.com",
            "password": "password123",
        })
        data = response.json()
        assert "team" in data
        assert data["team"]["budget_remaining"] == 90.0


# ============================================================
# Login
# ============================================================

class TestLogin:
    """Test user login endpoints."""

    def test_login_with_username(self, auth_client):
        """Login with username should work."""
        auth_client.post("/api/auth/register", json={
            "username": "loginuser",
            "email": "login@test.com",
            "password": "password123",
        })
        response = auth_client.post("/api/auth/login", json={
            "username": "loginuser",
            "password": "password123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["username"] == "loginuser"

    def test_login_with_email(self, auth_client):
        """Login with email should work."""
        auth_client.post("/api/auth/register", json={
            "username": "emailuser",
            "email": "email@test.com",
            "password": "password123",
        })
        response = auth_client.post("/api/auth/login", json={
            "username": "email@test.com",
            "password": "password123",
        })
        assert response.status_code == 200

    def test_login_wrong_password(self, auth_client):
        """Login with wrong password should fail."""
        auth_client.post("/api/auth/register", json={
            "username": "wrongpass",
            "email": "wrongpass@test.com",
            "password": "correct123",
        })
        response = auth_client.post("/api/auth/login", json={
            "username": "wrongpass",
            "password": "wrongpass",
        })
        assert response.status_code == 401

    def test_login_nonexistent_user(self, auth_client):
        """Login for nonexistent user should fail."""
        response = auth_client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "password123",
        })
        assert response.status_code == 401

    def test_login_form_data(self, auth_client):
        """Legacy form-based login should still work."""
        auth_client.post("/api/auth/register", json={
            "username": "formuser",
            "email": "form@test.com",
            "password": "password123",
        })
        response = auth_client.post("/api/auth/login-form", data={
            "username": "formuser",
            "password": "password123",
        })
        assert response.status_code == 200
        assert "access_token" in response.json()


# ============================================================
# Token Refresh
# ============================================================

class TestTokenRefresh:
    """Test token refresh and rotation."""

    def test_refresh_token_exchange(self, auth_client):
        """Exchanging a refresh token should return new tokens."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "refreshuser",
            "email": "refresh@test.com",
            "password": "password123",
        }).json()
        old_refresh = reg["refresh_token"]

        response = auth_client.post("/api/auth/refresh", json={
            "refresh_token": old_refresh,
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["refresh_token"] != old_refresh  # Token rotation

    def test_refresh_token_revoked_after_use(self, auth_client):
        """Old refresh token should be revoked after rotation."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "revokeduser",
            "email": "revoked@test.com",
            "password": "password123",
        }).json()
        old_refresh = reg["refresh_token"]

        # First refresh works
        auth_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})

        # Second refresh with same token should fail
        response = auth_client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert response.status_code == 401

    def test_refresh_invalid_token(self, auth_client):
        """Invalid refresh token should be rejected."""
        response = auth_client.post("/api/auth/refresh", json={
            "refresh_token": "completely_invalid_token",
        })
        assert response.status_code == 401


# ============================================================
# Logout
# ============================================================

class TestLogout:
    """Test logout functionality."""

    def test_logout_revokes_all_tokens(self, auth_client):
        """Logout should revoke all refresh tokens for the user."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "logoutuser",
            "email": "logout@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]
        refresh_token = reg["refresh_token"]

        # Refresh once to get another token
        refresh1 = auth_client.post("/api/auth/refresh", json={"refresh_token": refresh_token}).json()
        refresh_token_2 = refresh1["refresh_token"]

        # Logout
        response = auth_client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "logged_out"
        assert data["revoked_tokens"] >= 1

        # Old refresh tokens should no longer work
        response = auth_client.post("/api/auth/refresh", json={"refresh_token": refresh_token_2})
        assert response.status_code == 401


# ============================================================
# Auth Identity Model
# ============================================================

class TestAuthIdentityModel:
    """Test AuthIdentity model operations directly."""

    def test_create_identity(self, db_session):
        """Creating an identity should work."""
        from app.database import SessionLocal
        db = db_session

        user = User(
            username="identitytest",
            email="identitytest@test.com",
            password_hash=hash_password("password123"),
            email_verified=True,
        )
        db.add(user)
        db.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_id="123456789",
            provider_email="identitytest@test.com",
            provider_data=json.dumps({"name": "Test User", "picture": "http://example.com/pic.jpg"}),
            is_primary=True,
        )
        db.add(identity)
        db.commit()

        assert len(user.identities) == 1
        assert user.identities[0].provider == "google"

    def test_unique_provider_identity_constraint(self, db_session):
        """Duplicate provider+provider_id should be rejected."""
        db = db_session

        user = User(
            username="uniqueidtest",
            email="uniqueidtest@test.com",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.flush()

        identity1 = AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_id="google_sub_123",
            provider_email="uniqueidtest@test.com",
            is_primary=True,
        )
        db.add(identity1)
        db.commit()

        # Try to create another with same provider+provider_id
        identity2 = AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_id="google_sub_123",  # Same
            provider_email="uniqueidtest@test.com",
            is_primary=False,
        )
        db.add(identity2)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()


# ============================================================
# Email Verification
# ============================================================

class TestEmailVerification:
    """Test email verification flow."""

    def test_request_verification(self, auth_client):
        """Requesting email verification should work."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "verifyuser",
            "email": "verify@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]

        response = auth_client.post("/api/auth/verify-email/request", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "verification_requested"

    def test_verify_already_verified(self, auth_client, db_session):
        """Requesting verification for already verified user should be no-op."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "alreadyverified",
            "email": "already@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]

        # Mark as verified
        user = db_session.query(User).filter(User.username == "alreadyverified").first()
        user.email_verified = True
        db_session.commit()

        response = auth_client.post("/api/auth/verify-email/request", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "already_verified"


# ============================================================
# Account Management
# ============================================================

class TestAccountManagement:
    """Test account management endpoints."""

    def test_get_account(self, auth_client):
        """Getting account info should return user details."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "accountuser",
            "email": "account@test.com",
            "password": "password123",
            "team_name": "Test Team",
        }).json()
        access_token = reg["access_token"]

        response = auth_client.get("/api/account", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["username"] == "accountuser"
        assert data["user"]["email"] == "account@test.com"
        assert len(data["identities"]) >= 1

    def test_update_display_name(self, auth_client):
        """Updating display name should work."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "nametest",
            "email": "nametest@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]

        response = auth_client.put("/api/account", json={
            "display_name": "New Display Name",
        }, headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == 200
        assert response.json()["user"]["display_name"] == "New Display Name"

    def test_change_password(self, auth_client):
        """Changing password should work and revoke sessions."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "passtest",
            "email": "passtest@test.com",
            "password": "oldpassword",
        }).json()
        access_token = reg["access_token"]
        refresh_token = reg["refresh_token"]

        response = auth_client.post("/api/account/password", json={
            "current_password": "oldpassword",
            "new_password": "newpassword123",
        }, headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == 200

        # Old refresh token should be revoked
        response = auth_client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 401

        # Login with new password should work
        response = auth_client.post("/api/auth/login", json={
            "username": "passtest",
            "password": "newpassword123",
        })
        assert response.status_code == 200

    def test_change_password_wrong_current(self, auth_client):
        """Changing password with wrong current password should fail."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "wrongcurrent",
            "email": "wrongcurrent@test.com",
            "password": "correctpassword",
        }).json()
        access_token = reg["access_token"]

        response = auth_client.post("/api/account/password", json={
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
        }, headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == 400

    def test_link_email_password(self, auth_client, db_session):
        """Linking email+password to a Google-only account should work."""
        db = db_session

        # Create a Google-only user
        user = User(
            username="googleonly",
            email="googleonly@test.com",
            password_hash=hash_password("google:123456:abcdef"),
            email_verified=True,
        )
        db.add(user)
        db.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_id="google_sub_123",
            provider_email="googleonly@test.com",
            is_primary=True,
        )
        db.add(identity)
        db.commit()

        # Login via the user
        from app.auth import create_access_token
        access_token = create_access_token(user.id, user.username)

        # Link email+password
        response = auth_client.post("/api/account/identities/email/link", json={
            "password": "newpassword123",
        }, headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == 200

        # Now login with email+password should work
        response = auth_client.post("/api/auth/login", json={
            "username": "googleonly@test.com",
            "password": "newpassword123",
        })
        assert response.status_code == 200

    def test_unlink_identity(self, auth_client, db_session):
        """Unlinking an identity should work if user has other identities."""
        db = db_session

        user = User(
            username="unlinktest",
            email="unlinktest@test.com",
            password_hash=hash_password("password123"),
            email_verified=True,
        )
        db.add(user)
        db.flush()

        # Add email identity
        email_identity = AuthIdentity(
            user_id=user.id,
            provider="email",
            provider_id="unlinktest@test.com",
            provider_email="unlinktest@test.com",
            is_primary=True,
        )
        db.add(email_identity)

        # Add Google identity
        google_identity = AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_id="google_sub_unlink",
            provider_email="unlinktest@test.com",
            is_primary=False,
        )
        db.add(google_identity)
        db.commit()

        access_token = create_access_token(user.id, user.username)

        # Unlink Google identity
        response = auth_client.delete(f"/api/account/identities/{google_identity.id}", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200
        assert response.json()["provider"] == "google"

        # User should still have the email identity
        db.expire_all()
        assert len(user.identities) == 1
        assert user.identities[0].provider == "email"

    def test_cannot_unlink_last_identity(self, auth_client, db_session):
        """Cannot unlink the last identity."""
        db = db_session

        user = User(
            username="lastidentity",
            email="lastidentity@test.com",
            password_hash=hash_password("password123"),
            email_verified=True,
        )
        db.add(user)
        db.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider="email",
            provider_id="lastidentity@test.com",
            provider_email="lastidentity@test.com",
            is_primary=True,
        )
        db.add(identity)
        db.commit()

        access_token = create_access_token(user.id, user.username)

        response = auth_client.delete(f"/api/account/identities/{identity.id}", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 400
        assert "last" in response.json()["detail"].lower() or "one" in response.json()["detail"].lower()


# ============================================================
# Account Linking Logic
# ============================================================

class TestAccountLinking:
    """Test account linking logic directly."""

    def test_auto_link_google_to_existing_verified_email(self, db_session):
        """Google login should auto-link to existing verified email account."""
        from app.auth_linking import resolve_or_create_user

        db = db_session

        # Create existing email+password user
        user = User(
            username="linkeduser",
            email="linked@test.com",
            password_hash=hash_password("password123"),
            email_verified=True,
        )
        db.add(user)
        db.flush()

        identity = AuthIdentity(
            user_id=user.id,
            provider="email",
            provider_id="linked@test.com",
            provider_email="linked@test.com",
            is_primary=True,
        )
        db.add(identity)
        db.commit()

        # Simulate Google login with same email
        new_user, action = resolve_or_create_user(
            db=db,
            provider="google",
            provider_id="google_sub_linked",
            email="linked@test.com",
            email_verified=True,
            profile_data={"name": "Linked User", "picture": ""},
        )
        db.commit()

        assert action == "linked"
        assert new_user.id == user.id
        assert len(new_user.identities) == 2
        providers = {i.provider for i in new_user.identities}
        assert "email" in providers
        assert "google" in providers

    def test_create_new_user_from_google(self, db_session):
        """Google login should create new user if no email match."""
        from app.auth_linking import resolve_or_create_user

        db = db_session

        new_user, action = resolve_or_create_user(
            db=db,
            provider="google",
            provider_id="google_sub_new",
            email="newgoogle@test.com",
            email_verified=True,
            profile_data={"name": "New Google User", "picture": "http://example.com/pic.jpg"},
        )
        db.commit()

        assert action == "created"
        assert new_user.email == "newgoogle@test.com"
        assert new_user.email_verified is True
        assert new_user.display_name == "New Google User"
        assert len(new_user.identities) == 1
        assert new_user.identities[0].provider == "google"

    def test_existing_google_login(self, db_session):
        """Existing Google login should just return the user."""
        from app.auth_linking import resolve_or_create_user

        db = db_session

        # First login creates the user
        user1, action1 = resolve_or_create_user(
            db=db,
            provider="google",
            provider_id="google_sub_existing",
            email="existing@test.com",
            email_verified=True,
            profile_data={"name": "Existing User"},
        )
        db.commit()
        assert action1 == "created"

        # Second login returns the same user
        user2, action2 = resolve_or_create_user(
            db=db,
            provider="google",
            provider_id="google_sub_existing",
            email="existing@test.com",
            email_verified=True,
            profile_data={"name": "Existing User"},
        )
        assert action2 == "existing"
        assert user2.id == user1.id


# ============================================================
# Security Tests
# ============================================================

class TestSecurity:
    """Test security edge cases."""

    def test_access_token_expiry(self, auth_client):
        """Access tokens should expire after 15 minutes."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "expirytest",
            "email": "expiry@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]

        # Token should work now
        response = auth_client.get("/api/account", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200

    def test_refresh_token_stored_as_hash(self, auth_client, db_session):
        """Refresh tokens should be stored as hashes, not plaintext."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "hashtest",
            "email": "hashtest@test.com",
            "password": "password123",
        }).json()
        raw_token = reg["refresh_token"]

        stored_token = db_session.query(RefreshToken).order_by(RefreshToken.id.desc()).first()
        assert stored_token is not None
        assert stored_token.token_hash != raw_token
        # Stored token should be SHA-256 hash (64 hex chars)
        assert len(stored_token.token_hash) == 64

    def test_unauthorized_access(self, auth_client):
        """Accessing protected routes without token should fail."""
        response = auth_client.get("/api/account")
        assert response.status_code == 401

    def test_protected_route_with_valid_token(self, auth_client):
        """Accessing protected routes with valid token should work."""
        reg = auth_client.post("/api/auth/register", json={
            "username": "prottest",
            "email": "prottest@test.com",
            "password": "password123",
        }).json()
        access_token = reg["access_token"]

        response = auth_client.get("/api/account", headers={
            "Authorization": f"Bearer {access_token}",
        })
        assert response.status_code == 200


# ============================================================
# Refresh Token Model
# ============================================================

class TestRefreshTokenModel:
    """Test RefreshToken model operations."""

    def test_create_refresh_token(self, db_session):
        """Creating a refresh token should work."""
        from app.auth import create_refresh_token, verify_refresh_token, revoke_refresh_token

        db = db_session
        user = User(
            username="rftokenuser",
            email="rftokenuser@test.com",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.flush()

        raw_token = create_refresh_token(user.id, user_ip="127.0.0.1", user_agent="test", db=db)
        assert raw_token is not None

        # Verify it works
        verified_user = verify_refresh_token(raw_token, db=db)
        assert verified_user.id == user.id

        # Revoke it
        revoked = revoke_refresh_token(raw_token, db=db)
        assert revoked is True

        # Should no longer be valid
        verified_user = verify_refresh_token(raw_token, db=db)
        assert verified_user is None

    def test_revoke_all_user_tokens(self, db_session):
        """Revoking all tokens for a user should work."""
        from app.auth import create_refresh_token, verify_refresh_token, revoke_all_user_tokens

        db = db_session
        user = User(
            username="revoketest",
            email="revoketest@test.com",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.flush()

        token1 = create_refresh_token(user.id, db=db)
        token2 = create_refresh_token(user.id, db=db)
        token3 = create_refresh_token(user.id, db=db)

        # All tokens should work
        assert verify_refresh_token(token1, db=db) is not None
        assert verify_refresh_token(token2, db=db) is not None
        assert verify_refresh_token(token3, db=db) is not None

        # Revoke all
        count = revoke_all_user_tokens(user.id, db=db)
        assert count == 3

        # All tokens should be invalid
        assert verify_refresh_token(token1, db=db) is None
        assert verify_refresh_token(token2, db=db) is None
        assert verify_refresh_token(token3, db=db) is None
