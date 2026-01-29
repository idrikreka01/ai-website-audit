"""
Structured logging setup for the AI Website Audit project.

All runtime logging should go through structlog. This module provides a
minimal, production-friendly baseline that can be shared by both the API
and worker services.

Key principles:
- Logs are structured (JSON by default) and include contextual fields.
- Context can be bound per-request / per-session (e.g. session_id, page_type).
- Configuration is deterministic and avoids ad-hoc logging configuration
  scattered across the codebase.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog


def _build_shared_processors() -> list[structlog.types.Processor]:
    """
    Processors shared by both API and worker services.

    These can be extended over time (e.g., to add trace IDs or service
    names) without changing call sites.
    """

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.EventRenamer("message"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]


def configure_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_stdout: bool = True,
) -> None:
    """
    Configure structlog and the standard logging module.

    This should be called once at process startup by each service
    (API and worker). It is safe to call multiple times, but later
    calls will effectively be no-ops once structlog is configured.

    - When log_stdout is True (default), a StreamHandler(sys.stdout) is added.
    - When log_file is set, a FileHandler is added (parent dir created if needed).
    - At least one handler is always added: if both log_stdout=False and log_file
      is unset, stdout is used as fallback so the process never has zero handlers.
    """

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    if log_stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(level)
        stdout_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(stdout_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(file_handler)

    if not root.handlers:
        # Fallback: avoid zero handlers (e.g. LOG_STDOUT=false and LOG_FILE unset)
        fallback = logging.StreamHandler(sys.stdout)
        fallback.setLevel(level)
        fallback.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(fallback)

    structlog.configure(
        processors=_build_shared_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """
    Obtain a structured logger.

    Usage:
        from shared.logging import get_logger, bind_request_context

        logger = get_logger(__name__)
        bind_request_context(session_id="...", page_type="homepage")
        logger.info("navigation_completed")
    """

    # If configure_logging() has not been called yet, fall back to a
    # minimal configuration to avoid silent failures.
    if not structlog.is_configured():
        configure_logging()

    return structlog.get_logger(name) if name else structlog.get_logger()


def bind_request_context(
    *,
    session_id: Optional[str] = None,
    page_type: Optional[str] = None,
    viewport: Optional[str] = None,
    domain: Optional[str] = None,
    **extra: Any,
) -> Mapping[str, Any]:
    """
    Bind common context fields for request / crawl logging.

    This centralizes the convention that logs should include:
    - session_id
    - page_type
    - viewport
    - domain

    Additional keyword arguments are also bound into the logging context.
    """

    context: dict[str, Any] = {
        "session_id": session_id,
        "page_type": page_type,
        "viewport": viewport,
        "domain": domain,
        **extra,
    }

    # Remove keys with None values to keep logs concise.
    filtered_context = {k: v for k, v in context.items() if v is not None}

    structlog.contextvars.bind_contextvars(**filtered_context)
    return filtered_context
