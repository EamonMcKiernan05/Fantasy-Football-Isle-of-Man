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
    """Verify a password against a stored bcrypt hash.

    Also supports legacy SHA-256 format (salt$hash) for backward compatibility
    during migration.
    """
    try:
        pwd_bytes = password.encode("utf-8")
        hash_bytes = stored_hash.encode("utf-8")

        # Try bcrypt first
        if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
            return bcrypt.checkpw(pwd_bytes, hash_bytes)

        # Fallback: legacy SHA-256 format (salt$hash)
        if "$" in stored_hash:
            import hashlib
            salt, hashed = stored_hash.split("$", 1)
            new_hash = hashlib.sha256((salt + password).encode()).hexdigest()
            return new_hash == hashed

        return False
    except (ValueError, IndexError, UnicodeDecodeError):
        return False
