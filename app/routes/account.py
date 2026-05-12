"""Account management API routes for Fantasy Football IOM.

Handles profile updates, identity linking/unlinking, and password changes.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.database import get_bound_db
from app.models import User, AuthIdentity, RefreshToken
from app.schemas import (
    AccountResponse,
    LinkedIdentityResponse,
    UpdateProfileRequest,
    ChangePasswordRequest,
    LinkEmailPasswordRequest,
)
from app.auth import (
    get_current_user_from_token,
    revoke_all_user_tokens,
)
from app.utils.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("", response_model=dict)
def get_account(
    user: User = Depends(get_current_user_from_token),
):
    """Get current user's account details and linked identities."""
    identities = _serialize_identities(user.identities)

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
            "profile_picture_url": user.profile_picture_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "identities": identities,
    }


@router.put("", response_model=dict)
def update_profile(
    updates: UpdateProfileRequest,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Update user profile (display name)."""
    if updates.display_name is not None:
        user.display_name = updates.display_name.strip()

    db.commit()
    db.refresh(user)

    return {
        "status": "updated",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
            "profile_picture_url": user.profile_picture_url,
        },
    }


@router.post("/password", response_model=dict)
def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Change password. Requires current password for verification.

    Revokes all refresh tokens after password change for security.
    """
    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Validate new password
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    # Update password
    user.password_hash = hash_password(request.new_password)
    db.commit()

    # Revoke all refresh tokens (force re-authentication everywhere)
    revoke_all_user_tokens(user.id, db=db)

    return {
        "status": "password_changed",
        "message": "Password changed successfully. All sessions have been revoked.",
    }


@router.post("/identities/email/link", response_model=dict)
def link_email_password(
    request: LinkEmailPasswordRequest,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Link email+password login to a Google-only account.

    Sets a password on an account that previously only had OAuth identity.
    """
    # Check if email identity already exists
    existing_email_identity = db.query(AuthIdentity).filter(
        AuthIdentity.user_id == user.id,
        AuthIdentity.provider == "email",
    ).first()

    if existing_email_identity:
        raise HTTPException(status_code=409, detail="Email+password login is already linked")

    # Update the user's password hash
    user.password_hash = hash_password(request.password)

    # Create email identity
    from datetime import datetime
    email_identity = AuthIdentity(
        user_id=user.id,
        provider="email",
        provider_id=user.email,
        provider_email=user.email,
        is_primary=False,
        created_at=datetime.utcnow(),
    )
    db.add(email_identity)
    db.commit()

    return {
        "status": "linked",
        "message": "Email+password login is now linked to your account.",
    }


@router.delete("/identities/{identity_id}")
def unlink_identity(
    identity_id: int,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Unlink an identity from the current user.

    Cannot unlink the last remaining identity.
    Cannot unlink the primary identity if other identities exist.
    """
    identity = db.query(AuthIdentity).filter(
        AuthIdentity.id == identity_id,
        AuthIdentity.user_id == user.id,
    ).first()

    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")

    # Check that user has at least one other identity
    other_count = db.query(AuthIdentity).filter(
        AuthIdentity.user_id == user.id,
        AuthIdentity.id != identity_id,
    ).count()

    if other_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot unlink the last identity. User must have at least one sign-in method.",
        )

    db.delete(identity)
    db.commit()

    return {
        "status": "unlinked",
        "provider": identity.provider,
        "message": f"{identity.provider.capitalize()} identity unlinked.",
    }


def _serialize_identities(identities: List[AuthIdentity]) -> list:
    """Serialize a list of AuthIdentity objects."""
    result = []
    for identity in identities:
        data = {}
        if identity.provider_data:
            import json
            try:
                data = json.loads(identity.provider_data)
            except (json.JSONDecodeError, TypeError):
                pass

        result.append({
            "id": identity.id,
            "provider": identity.provider,
            "provider_id": identity.provider_id,
            "provider_email": identity.provider_email,
            "is_primary": identity.is_primary,
            "created_at": identity.created_at.isoformat() if identity.created_at else None,
            "data": data,
        })
    return result
