"""
Environment-based configuration for the AI Website Audit project.

This module exposes a small, typed configuration surface that can be
shared between the API and worker services. All values are sourced from
environment variables with sensible, non-secret defaults.

No secrets or credentials are hard-coded here; they must be provided via
the environment (or tooling such as python-dotenv in local development).
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal, Optional


Environment = Literal["local", "dev", "staging", "prod"]


@dataclass(frozen=True)
class AppConfig:
    """
    Top-level application configuration.

    This config is intentionally minimal for the scaffolding phase and
    focuses on cross-cutting concerns that both services may need. It can
    be safely extended in later tasks as requirements become concrete.
    """

    environment: Environment
    log_level: str

    # Infrastructure endpoints (metadata / queues / storage only).
    # These are URIs only; no credentials are stored here.
    database_url: Optional[str]
    redis_url: Optional[str]
    storage_root: str
    artifacts_dir: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        """
        Construct configuration from environment variables.

        All fields have sensible defaults suitable for local development.
        Production deployments are expected to override these via env vars.
        """

        environment = os.getenv("APP_ENV", "local")

        # Narrow the type at runtime while keeping a simple env interface.
        if environment not in {"local", "dev", "staging", "prod"}:
            # For scaffolding, fail fast on unexpected values instead of
            # guessing. This can be relaxed or logged differently later.
            raise ValueError(f"Unsupported APP_ENV value: {environment!r}")

        return cls(
            environment=environment,  # type: ignore[arg-type]
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            database_url=os.getenv("DATABASE_URL"),
            redis_url=os.getenv("REDIS_URL"),
            storage_root=os.getenv("STORAGE_ROOT", "./storage"),
            artifacts_dir=os.getenv("ARTIFACTS_DIR", "./artifacts"),
        )


def get_config() -> AppConfig:
    """
    Helper to obtain the current configuration.

    In simple scripts, calling this function directly is sufficient. In
    longer-lived processes, consider constructing a single `AppConfig`
    instance at startup and passing it explicitly through your code.
    """

    return AppConfig.from_env()

