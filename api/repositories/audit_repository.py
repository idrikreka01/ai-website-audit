"""
Repository for audit session, page, and artifact data access.

This module re-exports the shared repository for use in the API service.
"""

from __future__ import annotations

from shared.repository import AuditRepository

__all__ = ["AuditRepository"]
