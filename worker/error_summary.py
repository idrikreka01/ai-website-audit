"""
User-safe error summaries for DB/API storage.

Per spec: store user-safe summaries in Postgres; keep detailed errors in logs only.
All error_summary values written to the DB must come from this module or match
USER_SAFE_ERROR_SUMMARIES.
"""

from __future__ import annotations

# Canonical user-safe strings (no raw exception content in API/DB).
USER_SAFE_ERROR_SUMMARIES = frozenset(
    {
        "All viewports failed",
        "Audit failed",
        "Blocked (403/503)",
        "Bot-block",
        "Bot-block; reload failed",
        "Crawl failed",
        "Domain lock timeout",
        "Navigation failed",
        "Navigation timeout",
        "One or more viewports failed",
        "PDP not found",
        "PDP navigation failed",
        "Rate limited (429)",
    }
)


def get_user_safe_error_summary(
    exc: BaseException,
    fallback: str = "Crawl failed",
) -> str:
    """
    Return a user-safe error summary for storage/API.

    No raw exception messages or stack traces. Used for error_summary only;
    detailed error stays in logs. RuntimeError message is only used if it
    matches the allowlist of known safe summaries.
    """
    if isinstance(exc, RuntimeError):
        msg = str(exc).strip()
        if msg and msg in USER_SAFE_ERROR_SUMMARIES:
            return msg
    return fallback
