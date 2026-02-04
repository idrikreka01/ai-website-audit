"""
Pydantic schemas for API request/response contracts.

These models define the typed interface between the API and clients, ensuring
validation and clear contracts per the tech spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


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

    model_config = ConfigDict(from_attributes=True)


class AuditPageResponse(BaseModel):
    """Response schema for audit page metadata."""

    id: UUID
    session_id: UUID
    page_type: Literal["homepage", "pdp"]
    viewport: Literal["desktop", "mobile"]
    status: Literal["ok", "failed", "pending"]
    load_timings: dict
    low_confidence_reasons: list[str]

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class CreateAuditResponse(BaseModel):
    """Response schema for POST /audits."""

    id: UUID
    status: Literal["queued"]
    url: str


class AuditQuestionResponse(BaseModel):
    """Response schema for audit question."""

    id: UUID
    key: str
    stage: Literal["awareness", "consideration", "conversion"]
    category: str
    page_type: Literal["homepage", "collection", "product", "cart", "checkout"]
    narrative_tier: int
    baseline_severity: int
    fix_intent: Optional[str] = None
    specific_example_fix_text: Optional[str] = None
    question_text: str
    pass_criteria: Optional[str] = None
    fail_criteria: Optional[str] = None
    notes: Optional[str] = None
    allowed_evidence_types: list[str]
    ruleset_version: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateAuditQuestionRequest(BaseModel):
    """Request schema for POST /audits/questions."""

    key: str = Field(..., description="Unique stable identifier (e.g. 'aw_headline_clear_offer')")
    stage: Literal["awareness", "consideration", "conversion"] = Field(
        ..., description="Audit stage"
    )
    category: str = Field(..., description="Question category")
    page_type: Literal["homepage", "collection", "product", "cart", "checkout"] = Field(
        ..., description="Page type this question applies to"
    )
    narrative_tier: int = Field(..., ge=1, le=3, description="Narrative tier (1, 2, or 3)")
    baseline_severity: int = Field(
        ..., ge=1, le=5, description="Baseline severity score (1-5)"
    )
    question_text: str = Field(..., description="The audit question text")
    allowed_evidence_types: list[str] = Field(
        default_factory=list,
        description="Allowed evidence types (e.g. ['dom', 'screenshot', 'visible_text'])",
    )
    ruleset_version: str = Field(default="v1", description="Ruleset version")
    fix_intent: Optional[str] = Field(None, description="Fix intent description")
    specific_example_fix_text: Optional[str] = Field(None, description="Example fix text")
    pass_criteria: Optional[str] = Field(None, description="Pass criteria description")
    fail_criteria: Optional[str] = Field(None, description="Fail criteria description")
    notes: Optional[str] = Field(None, description="Additional notes")


class UpdateAuditQuestionRequest(BaseModel):
    """Request schema for PUT /audits/questions/{question_id}."""

    stage: Optional[Literal["awareness", "consideration", "conversion"]] = None
    category: Optional[str] = None
    page_type: Optional[Literal["homepage", "collection", "product", "cart", "checkout"]] = None
    narrative_tier: Optional[int] = Field(None, ge=1, le=3)
    baseline_severity: Optional[int] = Field(None, ge=1, le=5)
    question_text: Optional[str] = None
    allowed_evidence_types: Optional[list[str]] = None
    ruleset_version: Optional[str] = None
    fix_intent: Optional[str] = None
    specific_example_fix_text: Optional[str] = None
    pass_criteria: Optional[str] = None
    fail_criteria: Optional[str] = None
    notes: Optional[str] = None


class AuditQuestionResultResponse(BaseModel):
    """Response schema for audit question result."""

    id: UUID
    audit_id: UUID
    question_id: UUID
    pass_fail: bool
    score_1_to_10: int
    evidence_source_type: Literal["html_safe", "screenshot_only", "mixed"]
    payload_ref: Optional[dict] = None
    ai_reasoning_summary: Optional[str] = None
    ai_confidence_1_to_10: Optional[int] = None
    model_version: Optional[str] = None
    ruleset_version: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
