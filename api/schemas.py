"""
Pydantic schemas for API request/response contracts.

These models define the typed interface between the API and clients, ensuring
validation and clear contracts per the tech spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator


# Request schemas
class CreateAuditRequest(BaseModel):
    """Request schema for POST /audits."""

    url: HttpUrl = Field(..., description="URL to audit (must be a valid HTTP/HTTPS URL)")
    mode: Literal["standard", "debug"] = Field(
        default="standard",
        description="Audit mode: 'standard' or 'debug'",
    )

    @field_validator("url", mode="before")
    @classmethod
    def normalize_url(cls, v: str | HttpUrl) -> str:
        """Normalize URL to a consistent string format."""
        if isinstance(v, HttpUrl):
            return str(v)
        # Pydantic will validate it's a valid URL
        return str(v).strip()


# Response schemas
class AuditSessionResponse(BaseModel):
    """Response schema for audit session metadata."""

    id: UUID
    url: str
    status: Literal["queued", "running", "completed", "failed", "partial"]
    created_at: datetime
    final_url: Optional[str] = None
    mode: Literal["standard", "debug", "evidence_pack"]
    retention_policy: Literal["standard", "short", "long"]
    attempts: int
    error_summary: Optional[str] = None
    crawl_policy_version: str
    config_snapshot: dict
    low_confidence: bool
    pages: list[AuditPageResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AuditPageResponse(BaseModel):
    """Response schema for audit page metadata."""

    id: UUID
    session_id: UUID
    page_type: Literal["homepage", "pdp"]
    viewport: Literal["desktop", "mobile"]
    status: Literal["ok", "failed", "pending"]
    load_timings: dict
    low_confidence_reasons: list[str]

    class Config:
        from_attributes = True


class ArtifactResponse(BaseModel):
    """Response schema for artifact metadata."""

    id: UUID
    session_id: UUID
    page_id: UUID
    type: Literal["screenshot", "visible_text", "features_json", "html_gz"]
    storage_uri: str
    size_bytes: int
    created_at: datetime
    retention_until: Optional[datetime] = None
    checksum: Optional[str] = None

    class Config:
        from_attributes = True


class CreateAuditResponse(BaseModel):
    """Response schema for POST /audits."""

    id: UUID
    status: Literal["queued"]
    url: str
