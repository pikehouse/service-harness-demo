"""Pytest fixtures for the harness test suite."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from harness.database import Base, get_db
from harness.models import Ticket, SLO, Invariant, TicketEvent, TicketDependency
from harness.web.app import create_app


@pytest.fixture(scope="function")
def engine():
    """Create an in-memory SQLite engine for testing.

    Uses StaticPool to ensure the same connection is reused,
    which is necessary for SQLite in-memory databases to persist
    across multiple sessions.
    """
    # Import models to ensure they're registered with Base metadata
    from harness import models  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    # Create all tables
    Base.metadata.create_all(bind=engine)
    yield engine
    # Drop all tables after test
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(engine) -> Session:
    """Create a database session for testing."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(engine) -> TestClient:
    """Create a FastAPI test client with a test database."""
    app = create_app()

    # Create a session factory for the test
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
