"""
Worker entrypoint for processing audit jobs from RQ.

This module starts an RQ worker that consumes jobs from the "audit_jobs" queue.
"""

from __future__ import annotations

import sys

import redis
from dotenv import load_dotenv
from rq import Connection, Queue, Worker

from shared.config import get_config
from shared.logging import configure_logging, get_logger

load_dotenv()


def main() -> None:
    """Start the RQ worker."""
    # Configure logging
    config = get_config()
    import logging

    log_level = logging.getLevelName(config.log_level.upper())
    configure_logging(
        level=log_level,
        log_file=config.log_file,
        log_stdout=config.log_stdout,
    )

    logger = get_logger(__name__)

    # Validate Redis connection
    if not config.redis_url:
        logger.error("redis_url_not_configured")
        print("ERROR: REDIS_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    try:
        redis_conn = redis.from_url(config.redis_url)
        # Test connection
        redis_conn.ping()
    except Exception as e:
        logger.error("redis_connection_failed", error=str(e))
        print(f"ERROR: Failed to connect to Redis: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate database connection
    if not config.database_url:
        logger.error("database_url_not_configured")
        print("ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    logger.info("worker_starting", redis_url=config.redis_url)

    # Start RQ worker
    with Connection(redis_conn):
        queue = Queue("audit_jobs")
        worker = Worker([queue], name="audit_worker")

        logger.info("worker_ready", queue_name="audit_jobs")
        print("Worker started. Listening for jobs on queue 'audit_jobs'...")
        print("Press Ctrl+C to stop.")

        try:
            worker.work()
        except KeyboardInterrupt:
            logger.info("worker_stopping")
            print("\nWorker stopped.")


if __name__ == "__main__":
    main()
