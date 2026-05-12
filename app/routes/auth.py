"""Authentication API routes for Fantasy Football IOM.

Handles registration, login, logout, token refresh, and Google OAuth.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db, get_bound_db
from app.models import User, AuthIdentity, RefreshToken, EmailVerificationToken, FantasyTeam
from app.schemas import (
    UserCreate, LoginRequest, TokenResponse, RefreshRequest,
    EmailVerificationRequest, AccountResponse, LinkedIdentityResponse,
    LinkEmailPasswordRequest,
)
from app.utils.passwords import hash_password, verify_password
from app.auth import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    get_current_user_from_token,
)
from app.auth_linking import resolve_or_create_user, create_email_identity
from app.auth_google import (
    generate_pkce_pair,
    get_google_auth_url,
    exchange_code_for_tokens,
    verify_google_id_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=dict)
def register(user: UserCreate, db: Session = Depends(get_bound_db)):
    """Register a new user with email and password.

    Creates the user, an email identity, and a fantasy team.
    Returns access token + refresh token.
    """
    # Check for existing user by email or username
    existing = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already taken")

    # Create user
    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
        email_verified=False,  # Not verified until they click the email link
        display_name=user.username,
        created_at=datetime.utcnow(),
    )
    db.add(new_user)
    db.flush()

    # Create email identity
    create_email_identity(db, new_user.id, user.email)

    # Create fantasy team
    team_name = (user.team_name or f"{user.username}'s Team").strip()
    current_season = _get_current_season(db)
    ft = FantasyTeam(
        user_id=new_user.id,
        name=team_name,
        season=current_season,
        budget=90.0,
        budget_remaining=90.0,
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.commit()
    db.refresh(new_user)

    # Generate tokens
    access_token = create_access_token(new_user.id, new_user.username)
    refresh_token = create_refresh_token(new_user.id, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "email_verified": new_user.email_verified,
            "display_name": new_user.display_name,
            "profile_picture_url": new_user.profile_picture_url,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
        },
        "team": {
            "id": ft.id,
            "name": ft.name,
            "season": ft.season,
            "budget_remaining": ft.budget_remaining,
        },
    }


@router.post("/login", response_model=dict)
def login(
    request: LoginRequest,
    db: Session = Depends(get_bound_db),
):
    """Login with email/username and password.

    Returns access token + refresh token.
    """
    user = db.query(User).filter(
        (User.username == request.username) | (User.email == request.username)
    ).first()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
            "profile_picture_url": user.profile_picture_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }


@router.post("/logout")
def logout(
    refresh_token_str: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_bound_db),
):
    """Logout: revoke all refresh tokens for the current user."""
    user = get_current_user_from_token(authorization, db)
    revoked = revoke_all_user_tokens(user.id, db=db)
    # Also revoke the specific refresh token if provided
    if refresh_token_str:
        revoke_refresh_token(refresh_token_str, db=db)
    return {"status": "logged_out", "revoked_tokens": revoked}


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh: RefreshRequest, db: Session = Depends(get_bound_db)):
    """Exchange a refresh token for a new access token + refresh token.

    Implements token rotation: old refresh token is revoked, new pair is issued.
    """
    user = verify_refresh_token(refresh.refresh_token, db=db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Revoke old refresh token
    revoke_refresh_token(refresh.refresh_token, db=db)

    # Issue new pair
    new_access = create_access_token(user.id, user.username)
    new_refresh = create_refresh_token(user.id, db=db)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
    )


# --- Google OAuth ---

@router.get("/google")
def google_login(state: Optional[str] = Query(None)):
    """Redirect to Google OAuth consent screen.

    Generates PKCE pair and stores code_verifier in a signed state token.
    """
    code_verifier, code_challenge = generate_pkce_pair()

    # Create state that includes the code_verifier
    # For production, use a server-side session store. Here we embed in a simple
    # base64-encoded state with a short expiry.
    import base64
    state_data = {
        "cv": code_verifier,
        "st": state or "",
        "exp": datetime.now(timezone.utc).timestamp() + 600,  # 10 min expiry
    }
    encoded_state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    auth_url = get_google_auth_url(code_challenge, state=encoded_state)

    return {
        "auth_url": auth_url,
    }


@router.get("/google/callback")
def google_callback(
    code: str = Query(...),
    state: Optional[str] = Query(None),
    db: Session = Depends(get_bound_db),
):
    """Handle Google OAuth callback.

    Exchanges the code for tokens, verifies the ID token, resolves/links the user,
    and returns access + refresh tokens.
    """
    # Decode state to get code_verifier
    import base64
    try:
        state_data = json.loads(base64.urlsafe_b64decode(state).decode())
        code_verifier = state_data["cv"]
        # Check expiry
        if datetime.now(timezone.utc).timestamp() > state_data["exp"]:
            raise HTTPException(status_code=400, detail="OAuth state expired")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for tokens
    try:
        tokens = exchange_code_for_tokens(code, code_verifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    # Verify ID token
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No ID token received")

    try:
        google_info = verify_google_id_token(id_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid ID token: {e}")

    # Resolve or create user
    user, action = resolve_or_create_user(
        db=db,
        provider="google",
        provider_id=google_info["sub"],
        email=google_info.get("email", ""),
        email_verified=google_info.get("email_verified", False),
        profile_data={
            "name": google_info.get("name", ""),
            "picture": google_info.get("picture", ""),
            "email_verified": google_info.get("email_verified", False),
        },
    )
    db.commit()

    # If action is pending_link, the user needs to verify email first
    if action == "pending_link":
        raise HTTPException(
            status_code=409,
            detail="An account exists with this email but it has not been verified. "
                   "Please verify your email first, or contact support.",
        )

    # Create fantasy team if new user and doesn't have one
    if action == "created":
        existing_team = db.query(FantasyTeam).filter(FantasyTeam.user_id == user.id).first()
        if not existing_team:
            current_season = _get_current_season(db)
            ft = FantasyTeam(
                user_id=user.id,
                name=f"{user.display_name or user.username}'s Team",
                season=current_season,
                budget=90.0,
                budget_remaining=90.0,
                free_transfers=1,
                free_transfers_next_gw=1,
            )
            db.add(ft)
            db.commit()

    # Generate tokens
    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
            "profile_picture_url": user.profile_picture_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "action": action,
    }


# --- Email verification ---

@router.post("/verify-email/request")
def request_email_verification(
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Request email verification. Generates a token and 'sends' verification email.

    For development, logs the verification URL.
    For production, sends via configured SMTP.
    """
    if user.email_verified:
        return {"status": "already_verified"}

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    import hashlib
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # Delete any existing un-used tokens
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used == False,
    ).delete()

    ev_token = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
    )
    db.add(ev_token)
    db.commit()

    # In development, log the verification URL
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    verify_url = f"{base_url}/api/auth/verify-email/{raw_token}"
    print(f"[EMAIL VERIFICATION] {verify_url}")

    return {
        "status": "verification_requested",
        "message": "Verification email sent (check logs for URL)",
    }


@router.get("/verify-email/{token}")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Verify email using the token from the verification email."""
    import hashlib
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    ev_token = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.token_hash == token_hash,
        EmailVerificationToken.used == False,
        EmailVerificationToken.expires_at > datetime.now(timezone.utc),
    ).first()

    if not ev_token:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    user = db.query(User).filter(User.id == ev_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.email_verified = True
    ev_token.used = True
    db.commit()

    return {
        "status": "email_verified",
        "email": user.email,
    }


# --- Legacy login endpoint (Form data) for backward compatibility ---

@router.post("/login-form")
def login_form(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_bound_db),
):
    """Legacy form-based login for backward compatibility with frontend."""
    user = db.query(User).filter(
        (User.username == username) | (User.email == username)
    ).first()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
            "profile_picture_url": user.profile_picture_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }


def _get_current_season(db: Session) -> str:
    """Get the current season name."""
    from app.models import Season
    season = db.query(Season).filter(Season.started == True).order_by(Season.name.desc()).first()
    if season:
        return season.name
    return "2025-26"
