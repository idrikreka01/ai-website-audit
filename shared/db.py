"""
Shared database connection and session management.

This module provides sync SQLAlchemy engine and session setup that can be
reused by both the API and worker services. It uses the Alembic-managed
schema and provides Table/MetaData reflection for direct table access.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker, Session

from shared.config import get_config


# Global engine and session factory (initialized on first use).
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        config = get_config()
        if not config.database_url:
            raise ValueError(
                "DATABASE_URL environment variable is required. "
                "Set it to a PostgreSQL connection string."
            )
        _engine = create_engine(
            config.database_url,
            pool_pre_ping=True,
            echo=False,  # Set to True for SQL debugging in development.
        )
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_db_session() as session:
            # Use session here
            pass
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_table_metadata() -> MetaData:
    """
    Reflect the database schema to get Table objects.

    This allows us to work with tables without defining ORM models.
    """
    metadata = MetaData()
    metadata.reflect(bind=get_engine())
    return metadata


def get_audit_sessions_table() -> Table:
    """Get the audit_sessions table."""
    metadata = get_table_metadata()
    return metadata.tables["audit_sessions"]


def get_audit_pages_table() -> Table:
    """Get the audit_pages table."""
    metadata = get_table_metadata()
    return metadata.tables["audit_pages"]


def get_artifacts_table() -> Table:
    """Get the artifacts table."""
    metadata = get_table_metadata()
    return metadata.tables["artifacts"]


def get_crawl_logs_table() -> Table:
    """Get the crawl_logs table."""
    metadata = get_table_metadata()
    return metadata.tables["crawl_logs"]
