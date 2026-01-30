"""
Retention cleanup: delete expired html_gz artifacts and mark them deleted in DB.

Supports dry-run (log candidates only) and configurable batch size.
See TECH_SPEC_V1.1.md. No changes to crawl outputs.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from shared.config import get_config
from shared.logging import get_logger
from worker.db import get_db_session
from worker.repository import AuditRepository

logger = get_logger(__name__)


def run_retention_cleanup() -> dict:
    """
    Delete expired html_gz artifacts and mark them deleted in DB.

    Uses config: retention_cleanup_batch_size, retention_cleanup_dry_run.
    When dry_run is True, logs candidates without deleting files or updating DB.
    Returns dict with deleted, failed, reclaimed_bytes.
    """
    config = get_config()
    batch_size = config.retention_cleanup_batch_size
    dry_run = config.retention_cleanup_dry_run

    logger.info(
        "retention_cleanup.start",
        batch_size=batch_size,
        dry_run=dry_run,
    )

    deleted_count = 0
    failed_count = 0
    reclaimed_bytes = 0
    artifacts_root = Path(config.artifacts_dir)

    with get_db_session() as db_session:
        repository = AuditRepository(db_session)
        expired = repository.get_expired_html_artifacts(batch_size)

        for artifact in expired:
            artifact_id = artifact["id"]
            storage_uri = artifact["storage_uri"]
            size_bytes = artifact["size_bytes"]
            session_id = artifact["session_id"]

            try:
                if dry_run:
                    logger.info(
                        "retention_cleanup.candidate",
                        artifact_id=str(artifact_id),
                        session_id=str(session_id),
                        storage_uri=storage_uri,
                        size_bytes=size_bytes,
                        dry_run=True,
                    )
                    deleted_count += 1
                    reclaimed_bytes += size_bytes
                    continue

                full_path = artifacts_root / storage_uri
                full_path.unlink(missing_ok=True)

                repository.mark_artifact_deleted(UUID(str(artifact_id)))
                deleted_count += 1
                reclaimed_bytes += size_bytes

                logger.info(
                    "retention_cleanup.deleted",
                    artifact_id=str(artifact_id),
                    session_id=str(session_id),
                    storage_uri=storage_uri,
                    size_bytes=size_bytes,
                )
            except Exception as e:
                failed_count += 1
                logger.error(
                    "retention_cleanup.failed",
                    artifact_id=str(artifact_id),
                    storage_uri=storage_uri,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    reclaimed_mb = reclaimed_bytes / (1024 * 1024)
    logger.info(
        "retention_cleanup.complete",
        deleted=deleted_count,
        failed=failed_count,
        reclaimed_bytes=reclaimed_bytes,
        reclaimed_mb=round(reclaimed_mb, 2),
        dry_run=dry_run,
    )

    return {
        "deleted": deleted_count,
        "failed": failed_count,
        "reclaimed_bytes": reclaimed_bytes,
    }


def main() -> None:
    """CLI entrypoint: run retention cleanup and log results."""
    from dotenv import load_dotenv

    from shared.logging import configure_logging

    load_dotenv()
    configure_logging()
    result = run_retention_cleanup()
    reclaimed_mb = result["reclaimed_bytes"] / (1024 * 1024)
    print(
        f"Cleanup complete: deleted={result['deleted']}, failed={result['failed']}, "
        f"reclaimed_bytes={result['reclaimed_bytes']} ({reclaimed_mb:.2f} MB)"
    )


if __name__ == "__main__":
    main()
