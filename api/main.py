"""
FastAPI application entrypoint for the AI Website Audit API.

This module sets up the FastAPI app, configures logging, and registers
route handlers.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import audits
from shared.config import get_config
from shared.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()

    # Configure structured logging
    log_level = logging.getLevelName(config.log_level.upper())
    configure_logging(level=log_level)

    app = FastAPI(
        title="AI Website Audit API",
        description="API for creating and querying website audit sessions",
        version="0.1.0",
    )

    # CORS middleware (permissive for MVP; tighten in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route handlers
    app.include_router(audits.router)

    @app.get("/health")
    def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    return app


# Create the app instance
app = create_app()
