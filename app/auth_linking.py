"""Account linking logic for Fantasy Football IOM.

Handles resolving OAuth identities to existing users or creating new accounts.
"""
import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import User, AuthIdentity


def resolve_or_create_user(
    db: Session,
    provider: str,
    provider_id: str,
    email: str,
    email_verified: bool,
    profile_data: Optional[Dict] = None,
) -> Tuple[User, str]:
    """Resolve an OAuth identity to an existing user or create a new one.

    Returns:
        (user, action) where action is one of:
        - "existing": User already had this identity, just logged in
        - "linked": New identity was linked to existing user by email
        - "created": Brand new user was created
        - "pending_link": Identity matches unverified email account (rare)
    """
    # Step 1: Check if this identity already exists (user logging in with same provider)
    existing_identity = db.query(AuthIdentity).filter(
        AuthIdentity.provider == provider,
        AuthIdentity.provider_id == provider_id,
    ).first()

    if existing_identity:
        user = db.query(User).filter(User.id == existing_identity.user_id).first()
        if user:
            return user, "existing"

    # Step 2: Check if any user has this email
    user_by_email = db.query(User).filter(User.email == email).first()

    if user_by_email:
        # Step 2a: If email is verified or this is Google (which verifies emails), auto-link
        if user_by_email.email_verified or email_verified:
            # Auto-verify if Google confirms the email
            if email_verified and not user_by_email.email_verified:
                user_by_email.email_verified = True

            # Create the new identity linked to this user
            identity = AuthIdentity(
                user_id=user_by_email.id,
                provider=provider,
                provider_id=provider_id,
                provider_email=email,
                provider_data=json.dumps(profile_data or {}),
                is_primary=(len(user_by_email.identities) == 0),
                created_at=datetime.utcnow(),
            )
            db.add(identity)
            db.flush()
            return user_by_email, "linked"

        # Step 2b: Email matches but not verified — pending link
        return user_by_email, "pending_link"

    # Step 3: No matching user — create new account
    # Derive username from profile data or email
    display_name = profile_data.get("name", "") if profile_data else ""
    username = _generate_username(display_name or email)

    # Ensure username uniqueness
    username_base = username
    counter = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{username_base}{counter}"
        counter += 1

    # Hash a random password for Google-only accounts (they won't use it, but the column is NOT NULL)
    from app.utils.passwords import hash_password
    random_password = f"google:{provider_id}:{secrets_token()}"
    password_hash = hash_password(random_password)

    new_user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        email_verified=email_verified,
        display_name=display_name or username,
        profile_picture_url=profile_data.get("picture", "") if profile_data else "",
        created_at=datetime.utcnow(),
    )
    db.add(new_user)
    db.flush()

    # Create the identity
    identity = AuthIdentity(
        user_id=new_user.id,
        provider=provider,
        provider_id=provider_id,
        provider_email=email,
        provider_data=json.dumps(profile_data or {}),
        is_primary=True,
        created_at=datetime.utcnow(),
    )
    db.add(identity)
    db.flush()

    return new_user, "created"


def create_email_identity(
    db: Session,
    user_id: int,
    email: str,
) -> AuthIdentity:
    """Create an email+password identity for a user (during registration)."""
    identity = AuthIdentity(
        user_id=user_id,
        provider="email",
        provider_id=email,
        provider_email=email,
        is_primary=True,
        created_at=datetime.utcnow(),
    )
    db.add(identity)
    db.flush()
    return identity


def _generate_username(name_or_email: str) -> str:
    """Generate a username from a display name or email."""
    if "@" in name_or_email:
        base = name_or_email.split("@")[0]
    else:
        base = name_or_email

    # Lowercase, replace spaces/special chars with underscores
    username = base.lower().strip()
    username = "".join(c if c.isalnum() or c == "_" else "_" for c in username)
    username = username.strip("_")

    if not username:
        username = "user"

    return username[:50]


def secrets_token() -> str:
    """Generate a short random token for password generation."""
    import secrets
    return secrets.token_hex(16)
