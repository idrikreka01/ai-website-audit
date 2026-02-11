"""
Environment-based configuration for the AI Website Audit project.

This module exposes a small, typed configuration surface that can be
shared between the API and worker services. All values are sourced from
environment variables with sensible, non-secret defaults.

No secrets or credentials are hard-coded here; they must be provided via
the environment (or tooling such as python-dotenv in local development).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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

    # Optional file path for structured JSON logs; when set, logs are written
    # to file (and stdout if log_stdout).
    log_file: Optional[str]
    # When True, logs go to stdout. When False, only file (if LOG_FILE set). Default True.
    log_stdout: bool

    # Infrastructure endpoints (metadata / queues / storage only).
    # These are URIs only; no credentials are stored here.
    database_url: Optional[str]
    redis_url: Optional[str]
    storage_root: str
    artifacts_dir: str

    # Redis lock and throttle (worker; TECH_SPEC_V1.1.md)
    domain_lock_ttl_seconds: int
    domain_lock_max_retries: int
    domain_lock_backoff_base_ms: int
    domain_min_delay_ms: int
    domain_throttle_ttl_seconds: int
    disable_throttle: bool
    disable_locks: bool

    # HTML artifact retention (worker; TECH_SPEC_V1.1.md, TECH_SPEC_V1.md)
    html_retention_days: int  # default 14, configurable 7–30

    # Retention cleanup job (TECH_SPEC_V1.1.md)
    retention_cleanup_enabled: bool
    retention_cleanup_batch_size: int
    retention_cleanup_dry_run: bool

    # RQ job timeout (seconds)
    audit_job_timeout_seconds: int

    # OpenAI API configuration (for HTML analysis)
    openai_api_key: Optional[str]
    html_analysis_mode: str

    # Telegram notification configuration
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]

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

        log_stdout_raw = (os.getenv("LOG_STDOUT") or "true").strip().lower()
        log_stdout = log_stdout_raw in ("true", "1", "yes")

        def _bool_env(name: str, default: bool) -> bool:
            raw = (os.getenv(name) or str(default)).strip().lower()
            return raw in ("true", "1", "yes")

        def _html_retention_days() -> int:
            raw = os.getenv("HTML_RETENTION_DAYS", "14").strip()
            try:
                days = int(raw)
            except ValueError:
                return 14
            return max(7, min(30, days))

        # In local/dev, default to disabling locks & throttle unless explicitly overridden.
        locks_disabled_by_default = environment in {"local", "dev"}
        throttle_disabled_by_default = environment in {"local", "dev"}

        return cls(
            environment=environment,  # type: ignore[arg-type]
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE") or None,
            log_stdout=log_stdout,
            database_url=os.getenv("DATABASE_URL"),
            redis_url=os.getenv("REDIS_URL"),
            storage_root=os.getenv("STORAGE_ROOT", "./storage"),
            artifacts_dir=os.getenv("ARTIFACTS_DIR", "./artifacts"),
            domain_lock_ttl_seconds=int(os.getenv("DOMAIN_LOCK_TTL_SECONDS", "300")),
            domain_lock_max_retries=int(os.getenv("DOMAIN_LOCK_MAX_RETRIES", "3")),
            domain_lock_backoff_base_ms=int(os.getenv("DOMAIN_LOCK_BACKOFF_BASE_MS", "1000")),
            domain_min_delay_ms=int(os.getenv("DOMAIN_MIN_DELAY_MS", "2000")),
            domain_throttle_ttl_seconds=int(os.getenv("DOMAIN_THROTTLE_TTL_SECONDS", "60")),
            disable_throttle=_bool_env("DISABLE_THROTTLE", throttle_disabled_by_default),
            disable_locks=_bool_env("DISABLE_LOCKS", locks_disabled_by_default),
            html_retention_days=_html_retention_days(),
            retention_cleanup_enabled=_bool_env("RETENTION_CLEANUP_ENABLED", False),
            retention_cleanup_batch_size=int(os.getenv("RETENTION_CLEANUP_BATCH_SIZE", "100")),
            retention_cleanup_dry_run=_bool_env("RETENTION_CLEANUP_DRY_RUN", False),
            audit_job_timeout_seconds=int(os.getenv("AUDIT_JOB_TIMEOUT_SECONDS", "1200")),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            html_analysis_mode=os.getenv("HTML_ANALYSIS_MODE", "automatic").lower(),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        )


def get_config() -> AppConfig:
    """
    Helper to obtain the current configuration.

    In simple scripts, calling this function directly is sufficient. In
    longer-lived processes, consider constructing a single `AppConfig`
    instance at startup and passing it explicitly through your code.
    """

    return AppConfig.from_env()
