"""Password hashing utilities."""
import hashlib
import secrets


def hash_password(password: str) -> str:
    """Hash a password with a random salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, hashed = stored_hash.split("$", 1)
        new_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return new_hash == hashed
    except (ValueError, IndexError):
        return False
