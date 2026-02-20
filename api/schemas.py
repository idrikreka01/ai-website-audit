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
    homepage_ok: bool = False
    pdp_ok: bool = False
    cart_ok: bool = False
    checkout_ok: bool = False
    page_coverage_score: int = Field(0, ge=0, le=4)
    ai_audit_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    ai_audit_flag: Optional[Literal["high", "medium", "low"]] = None
    functional_flow_score: int = Field(0, ge=0, le=3)
    functional_flow_details: Optional[dict] = None
    overall_score_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)
    needs_manual_review: bool = False
    pages: list[AuditPageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AuditPageResponse(BaseModel):
    """Response schema for audit page metadata."""

    id: UUID
    session_id: UUID
    page_type: Literal["homepage", "pdp", "cart", "checkout"]
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

    question_id: int
    category: str
    question: str
    ai_criteria: str
    tier: int
    severity: int
    bar_chart_category: str
    exact_fix: str
    page_type: Literal["homepage", "product", "cart", "checkout"]

    model_config = ConfigDict(from_attributes=True)


class CreateAuditQuestionRequest(BaseModel):
    """Request schema for POST /audits/questions."""

    category: str = Field(..., description="Question category")
    question: str = Field(..., description="The audit question text")
    ai_criteria: str = Field(..., description="Full AI evaluation criteria and instructions")
    tier: int = Field(..., ge=1, le=3, description="Tier (1, 2, or 3)")
    severity: int = Field(..., ge=1, le=5, description="Severity score (1-5)")
    bar_chart_category: str = Field(..., description="Bar chart category")
    exact_fix: str = Field(..., description="Exact fix description")
    page_type: Literal["homepage", "product", "cart", "checkout"] = Field(
        ..., description="Page type this question applies to"
    )


class UpdateAuditQuestionRequest(BaseModel):
    """Request schema for PUT /audits/questions/{question_id}."""

    category: Optional[str] = None
    question: Optional[str] = None
    ai_criteria: Optional[str] = None
    tier: Optional[int] = Field(None, ge=1, le=3)
    severity: Optional[int] = Field(None, ge=1, le=5)
    bar_chart_category: Optional[str] = None
    exact_fix: Optional[str] = None
    page_type: Optional[Literal["homepage", "product", "cart", "checkout"]] = None


class AuditResultResponse(BaseModel):
    """Response schema for audit result."""

    result_id: int
    question_id: int
    session_id: str
    result: Literal["pass", "fail", "unknown"]
    reason: Optional[str] = None
    confidence_score: int = Field(..., ge=1, le=10, description="Confidence score (1-10)")

    model_config = ConfigDict(from_attributes=True)


class CreateAuditResultRequest(BaseModel):
    """Request schema for POST /audits/results."""

    question_id: int = Field(..., description="Question ID")
    session_id: str = Field(..., description="Session ID")
    result: Literal["pass", "fail", "unknown"] = Field(..., description="Result: pass, fail, or unknown")
    reason: Optional[str] = Field(None, description="Reason for the result")
    confidence_score: int = Field(5, ge=1, le=10, description="Confidence score (1-10, defaults to 5)")


class AuditReportQuestionResponse(BaseModel):
    """Response schema for a question in the audit report."""

    question_id: int
    question: str
    category: str
    bar_chart_category: str
    tier: int
    severity: int
    exact_fix: str
    result: Literal["pass", "fail", "unknown"]
    reason: Optional[str] = None
    confidence_score: Optional[int] = None


class StageSummaryResponse(BaseModel):
    """Response schema for stage summary."""

    stage: Literal["Awareness", "Consideration", "Conversion"]
    summary: str
    generated_at: str
    model_version: str


class CategoryScoreResponse(BaseModel):
    """Response schema for weighted category score."""

    category: str
    score: float
    total_questions: int
    total_weight: float


class ActionableFindingResponse(BaseModel):
    """Response schema for actionable finding in changelog."""

    actionable_finding: str
    impact: Literal["High", "Medium", "Low"]
    category: str
    tier: int
    severity: int
    question_id: int


class StageScoresResponse(BaseModel):
    """Response schema for stage scores."""

    awareness: float
    consideration: float
    conversion: float


class CategoryScoresByStageResponse(BaseModel):
    """Response schema for category scores grouped by stage."""

    awareness: list[CategoryScoreResponse] = []
    consideration: list[CategoryScoreResponse] = []
    conversion: list[CategoryScoreResponse] = []


class StorefrontReportCardResponse(BaseModel):
    """Response schema for storefront report card."""

    stage_descriptions: dict[str, str]
    final_thoughts: str


class AuditReportResponse(BaseModel):
    """Response schema for audit report (JSON format)."""

    session_id: str
    url: str
    overall_score_percentage: Optional[float] = None
    overall_score: float
    stage_scores: StageScoresResponse
    category_scores: list[CategoryScoreResponse] = []
    category_scores_by_stage: CategoryScoresByStageResponse
    storefront_report_card: Optional[StorefrontReportCardResponse] = None
    needs_manual_review: bool = False
    tier1_passed: bool
    tier2_passed: bool
    tier3_included: bool
    questions: list[AuditReportQuestionResponse]
    stage_summaries: list[StageSummaryResponse] = []
    actionable_findings: list[ActionableFindingResponse] = []
