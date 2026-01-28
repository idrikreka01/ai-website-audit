"""
Repository for audit session, page, and log data access in the worker.

This module re-exports the shared repository for use in the worker service.
"""

from __future__ import annotations

from shared.repository import AuditRepository

__all__ = ["AuditRepository"]
