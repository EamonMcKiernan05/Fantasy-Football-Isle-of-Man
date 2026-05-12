"""SQLAlchemy database setup for Fantasy Football Isle of Man.

Dual-database architecture:
- Main game DB: users, fantasy_teams, squad_players, transfers, chips, etc.
- FFIOM-DB (ATTACH): players, teams, gameweeks, fixtures (source of truth)

FFIOM-DB is the authoritative source for player/fixture data.
The game DB is used for user data, fantasy teams, scoring history.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from dotenv import load_dotenv

load_dotenv()

GAME_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/fantasy_iom.db")
FFIOM_DB_PATH = os.getenv(
    "FFIOM_DB_PATH",
    "/home/eamon/FFIOM-DB/data/fantasy_iom.db",
)

# SQLite connection settings
connect_args = {"check_same_thread": False} if "sqlite" in GAME_DB_URL else {}

engine = create_engine(
    GAME_DB_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _attach_ffiom(dbapi_conn, connection_record):
    """Attach FFIOM-DB as 'ffiom' to every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute(f"ATTACH DATABASE '{FFIOM_DB_PATH}' AS ffiom")
    cursor.close()


# Attach FFIOM-DB to every game DB connection
event.listen(engine, "connect", _attach_ffiom)


def init_db():
    """Initialize database tables."""
    # Import all models to ensure they're registered
    from app import models  # noqa: F401

    # Create all tables
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting a database session.

    This session is bound to the game DB but also has FFIOM-DB attached
    as 'ffiom'. Player/Team/Gameweek/Fixture queries should use
    get_ffiom_db() instead.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# === FFIOM-DB session (source of truth for player/fixture data) ===
# We create a separate connection to FFIOM-DB for dedicated queries.
ffiom_engine = create_engine(
    f"sqlite:///{FFIOM_DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)
FfiomSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=ffiom_engine
)


def get_ffiom_db():
    """Dependency for getting a session to FFIOM-DB (source of truth).

    Use this for reading player data, team data, gameweeks, fixtures.
    """
    db = FfiomSessionLocal()
    try:
        yield db
    finally:
        db.close()


# === Cross-database session ===
# This session uses the game DB engine (which has FFIOM-DB attached via
# the 'connect' event) and routes specific models to the attached
# FFIOM-DB using SQLAlchemy 'binds'.

def _configure_binds(session_class):
    """Configure model-to-engine binds after models are imported.

    Call this once at app startup after importing all models.
    Models routed to FFIOM-DB: Player, Team, Gameweek, Fixture
    All other models stay on the game DB.
    """
    from app import models  # noqa: F401

    binds = {
        models.Player: ffiom_engine,
        models.Team: ffiom_engine,
        models.Gameweek: ffiom_engine,
        models.Fixture: ffiom_engine,
    }

    # Create a new session class with binds
    BoundSession = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, binds=binds
    )
    return BoundSession


# Lazy-initialized bound session (set after models import)
BoundSessionLocal = None


def init_binds():
    """Initialize the bound session after models are imported.

    Call this once during app startup.
    """
    global BoundSessionLocal
    if BoundSessionLocal is None:
        BoundSessionLocal = _configure_binds(SessionLocal)


def get_bound_db():
    """Dependency for getting a session with FFIOM-DB binds configured.

    This session routes Player/Team/Gameweek/Fixture models to FFIOM-DB
    and all other models to the game DB. This is the recommended session
    for most API endpoints.
    """
    if BoundSessionLocal is None:
        init_binds()
    db = BoundSessionLocal()
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
    if 'test_' not in caller_file and 'test_engine' not in str(kwargs.get('bind', '')) and 'alembic' not in caller_file.lower():
        raise RuntimeError(
            "SAFETY: drop_all() blocked on production database. "
            "Database wipes are NEVER allowed in production. "
            "If you need to reset the database, delete the data/fantasy_iom.db file manually."
        )
    _original_drop_all(*args, **kwargs)


Base.metadata.drop_all = _safe_drop_all
