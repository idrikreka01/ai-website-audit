"""
Pytest configuration and fixtures for API tests.

This module provides shared test fixtures including database setup
and FastAPI test client.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import create_app
from api.db import get_db_session


# Use a test database URL (can be overridden via TEST_DATABASE_URL env var)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/ai_website_audit_test",
)


def run_migrations(database_url: str) -> None:
    """
    Run Alembic migrations against the test database.

    This ensures the database schema is up to date before tests run.
    """
    # Find the repo root (where alembic.ini and migrations/ are located)
    # This file is at api/tests/conftest.py, so go up two levels
    repo_root = Path(__file__).parent.parent.parent

    # Create Alembic config pointing to the test database
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(repo_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    # Run migrations
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def test_engine():
    """
    Create a test database engine and bootstrap the schema.

    This fixture runs once per test session and applies Alembic migrations
    to ensure the database schema is initialized.

    Note: The test database must exist before running tests. Create it with:
        createdb ai_website_audit_test
    Or set TEST_DATABASE_URL to point to an existing database.
    """
    # Bootstrap schema by running migrations before creating engine
    run_migrations(TEST_DATABASE_URL)

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """Create a test database session with transaction rollback."""
    connection = test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)

    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(test_session):
    """Create a FastAPI test client with a test database session."""
    app = create_app()

    # Override the database dependency
    def override_get_db():
        yield test_session

    app.dependency_overrides[get_db_session] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def db_session(test_session):
    """Provide a test database session for direct repository testing."""
    return test_session
