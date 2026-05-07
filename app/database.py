"""SQLAlchemy database setup for Fantasy Football Isle of Man."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/fantasy_iom.db")

# SQLite connection settings
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """Initialize database tables."""
    # Import all models to ensure they're registered
    from app import models  # noqa: F401

    # Create all tables
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# === SAFETY NET: Prevent accidental database wipes ===
# This overrides drop_all on the production engine to prevent data loss
_original_drop_all = Base.metadata.drop_all

def _safe_drop_all(*args, **kwargs):
    """Safety wrapper that prevents drop_all on production database."""
    import inspect
    # Check if this is being called from test code with test_engine
    caller = inspect.stack()[1]
    caller_file = caller.filename if caller else ''
    
    # Allow drop_all ONLY from test files using test_engine
    if 'test_' not in caller_file and 'test_engine' not in str(kwargs.get('bind', '')):
        raise RuntimeError(
            "SAFETY: drop_all() blocked on production database. "
            "Database wipes are NEVER allowed in production. "
            "If you need to reset the database, delete the data/fantasy_iom.db file manually."
        )
    _original_drop_all(*args, **kwargs)

Base.metadata.drop_all = _safe_drop_all
