"""Database connection and session management."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator, Optional

from harness.config import get_settings


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def get_engine(database_url: Optional[str] = None):
    """Create database engine."""
    url = database_url or get_settings().database_url
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        echo=get_settings().is_development,
    )

    # Enable foreign keys for SQLite
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine=None) -> sessionmaker:
    """Create a session factory."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Default session factory
_SessionLocal = None


def get_session_local() -> sessionmaker:
    """Get the default session factory, creating it if needed."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = create_session_factory()
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI to get a database session."""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from contextlib import contextmanager

@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for getting a database session.

    Usage:
        with get_session() as db:
            db.query(...)
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(engine=None):
    """Initialize the database, creating all tables."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(bind=engine)


def reset_db(engine=None):
    """Drop and recreate all tables. Use only in tests."""
    if engine is None:
        engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
