"""Google OAuth2 integration for Fantasy Football IOM.

Implements authorization code flow with PKCE.
"""
import os
import secrets
from typing import Dict, Optional, Tuple

import jwt
import requests

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_USERINFO_URI = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPES = "openid email profile"


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        (code_verifier, code_challenge)
    """
    code_verifier = secrets.token_urlsafe(64)
    import hashlib
    code_challenge = hashlib.sha256(code_verifier.encode()).digest().decode()
    # URL-safe base64 without padding
    code_challenge = code_challenge.replace("+", "-").replace("/", "_").replace("=", "")
    return code_verifier, code_challenge


def get_google_auth_url(code_challenge: str, state: Optional[str] = None) -> str:
    """Generate the Google OAuth consent URL.

    Args:
        code_challenge: PKCE code challenge
        state: Optional state parameter for CSRF protection

    Returns:
        The full Google OAuth authorization URL
    """
    from urllib.parse import urlencode

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    if state:
        params["state"] = state

    return f"{GOOGLE_AUTH_URI}?{urlencode(params)}"


def exchange_code_for_tokens(code: str, code_verifier: str) -> Dict:
    """Exchange an authorization code for access and ID tokens.

    Args:
        code: Authorization code from Google callback
        code_verifier: The original PKCE code verifier

    Returns:
        Dict with access_token, id_token, token_type, expires_in, scope
    """
    from urllib.parse import urlencode

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "code_verifier": code_verifier,
    }

    resp = requests.post(GOOGLE_TOKEN_URI, data=urlencode(params), headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def verify_google_id_token(id_token: str) -> Dict:
    """Verify and decode a Google ID token.

    Performs:
    - JWT signature verification using Google's public keys
    - Audience check (must be our client ID)
    - Expiry check
    - Issuer check

    Returns:
        Decoded token payload dict with sub, email, email_verified, name, picture, etc.

    Raises:
        ValueError: If token is invalid
    """
    # Fetch Google's public keys
    try:
        jwks_resp = requests.get(GOOGLE_JWKS_URI, timeout=10)
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()
    except Exception as e:
        raise ValueError(f"Failed to fetch Google public keys: {e}")

    # Get the kid from the unverified header
    unverified_header = jwt.get_unverified_header(id_token)
    kid = unverified_header.get("kid")

    if not kid:
        raise ValueError("ID token missing kid")

    # Find the matching key
    public_key = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            public_key = key
            break

    if not public_key:
        raise ValueError("No matching public key found")

    # Construct RSA public key
    from cryptography.x509 import load_pem_x509_certificate
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    import base64
    n = _base64url_decode(public_key["n"])
    e = _base64url_decode(public_key["e"])

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.backends import default_backend

    rsa_numbers = RSAPublicNumbers(e=int.from_bytes(e, "big"), n=int.from_bytes(n, "big"))
    rsa_public_key = rsa_numbers.public_key(default_backend())

    # Verify and decode the token
    try:
        decoded = jwt.decode(
            id_token,
            rsa_public_key,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            issuer="https://accounts.google.com",
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("ID token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid ID token: {e}")

    return decoded


def _base64url_decode(data: str) -> bytes:
    """Decode a base64url-encoded string."""
    import base64
    # Add padding if needed
    data += "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(data.encode())


def get_google_userinfo(access_token: str) -> Dict:
    """Fetch user info from Google's userinfo endpoint.

    Args:
        access_token: Google OAuth access token

    Returns:
        Dict with user info (sub, email, name, picture, etc.)
    """
    resp = requests.get(
        GOOGLE_USERINFO_URI,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
