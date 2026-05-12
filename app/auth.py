"""JWT authentication utilities for Fantasy Football IOM."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.database import get_db, get_bound_db
from app.models import User, RefreshToken

# JWT configuration
SECRET_KEY = os.environ.get("APP_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15  # Short-lived access token
REFRESH_TOKEN_EXPIRE_DAYS = 7  # Refresh token lifetime


def create_access_token(user_id: int, username: str) -> str:
    """Create a JWT access token for a user."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token. Returns payload dict."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# --- Refresh token functions ---


def _hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_token(
    user_id: int,
    user_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    db: Optional[Session] = None,
) -> str:
    """Create a refresh token and store its hash in the database.

    Returns the raw token string (sent to client).
    If db is not provided, creates its own session.
    """
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        raw_token = secrets.token_urlsafe(64)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        rt = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_ip=user_ip,
            user_agent=user_agent,
        )
        db.add(rt)
        db.commit()
        return raw_token
    finally:
        if should_close:
            db.close()


def verify_refresh_token(raw_token: str, db: Optional[Session] = None) -> Optional[User]:
    """Verify a refresh token and return the associated user.

    Returns None if the token is invalid, expired, or revoked.
    """
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        token_hash = _hash_token(raw_token)
        rt = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        ).first()

        if not rt:
            return None

        user = db.query(User).filter(User.id == rt.user_id).first()
        return user
    finally:
        if should_close:
            db.close()


def revoke_refresh_token(raw_token: str, db: Optional[Session] = None) -> bool:
    """Revoke a single refresh token by its raw value."""
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        token_hash = _hash_token(raw_token)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if rt:
            rt.revoked = True
            db.commit()
            return True
        return False
    finally:
        if should_close:
            db.close()


def revoke_all_user_tokens(user_id: int, db: Optional[Session] = None) -> int:
    """Revoke all refresh tokens for a user. Returns count of revoked tokens."""
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        tokens = db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        ).all()
        for t in tokens:
            t.revoked = True
        db.commit()
        return len(tokens)
    finally:
        if should_close:
            db.close()


# --- Current user resolution ---


def get_current_user_from_token(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_bound_db),
) -> User:
    """Extract and validate user from JWT Authorization header.

    Supports both 'Bearer <token>' and legacy 'bearer-{user_id}-{username}' format.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = authorization.replace("Bearer ", "")

    # Try JWT first
    if "." in token:  # JWT tokens have dots
        payload = verify_token(token)
        user_id = int(payload["sub"])
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    # Legacy format: bearer-{user_id}-{username}
    parts = token.split("-", 2)
    if len(parts) >= 3 and parts[0] == "bearer":
        user_id = int(parts[1])
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token format",
    )
