"""
Database connection and session management for the API service.

This module re-exports shared database functionality with a FastAPI-specific
session dependency wrapper.
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy.orm import Session

from shared.db import (
    get_db_session as _get_db_session,
    get_audit_sessions_table,
    get_audit_pages_table,
    get_artifacts_table,
    get_crawl_logs_table,
)

# Re-export table getters for backward compatibility
__all__ = [
    "get_db_session",
    "get_audit_sessions_table",
    "get_audit_pages_table",
    "get_artifacts_table",
    "get_crawl_logs_table",
]


def get_db_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.

    This is a generator function that FastAPI's Depends can use.
    FastAPI will handle the cleanup automatically.
    """
    with _get_db_session() as session:
        yield session
