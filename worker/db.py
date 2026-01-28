"""
Database connection and session management for the worker service.

This module re-exports shared database functionality.
"""

from __future__ import annotations

from shared.db import get_db_session

__all__ = ["get_db_session"]
