"""Password hashing utilities using bcrypt."""
import bcrypt


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Returns the bcrypt hash string (includes salt).
    """
    pwd_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored bcrypt hash."""
    try:
        pwd_bytes = password.encode("utf-8")
        hash_bytes = stored_hash.encode("utf-8")

        if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
            return bcrypt.checkpw(pwd_bytes, hash_bytes)

        return False
    except (ValueError, IndexError, UnicodeDecodeError):
        return False
