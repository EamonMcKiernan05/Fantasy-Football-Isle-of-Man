"""Shared pytest fixtures for Fantasy Football IOM tests."""
import sys
import os
import pytest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db


@pytest.fixture(scope="function")
def test_db():
    """Create a temporary SQLite database for each test."""
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    test_engine = create_engine(f"sqlite:///{temp_db.name}")
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    Base.metadata.create_all(test_engine)

    yield test_engine, TestSessionLocal()

    temp_db.close()
    os.unlink(temp_db.name)


@pytest.fixture(scope="function")
def client(test_db):
    """Create a test client for API testing."""
    from app.main import app
    from starlette.testclient import TestClient

    _, session = test_db

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()
