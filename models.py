"""
models.py — Pydantic models for request / response schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class ApplicationRequest(BaseModel):
    """Incoming application to be evaluated."""
    application_id: str = Field(..., description="Unique identifier for the application")
    income: float = Field(..., description="Applicant's annual income")
    credit_score: int = Field(..., description="Applicant's credit score (300-850)")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

class WorkflowStateResponse(BaseModel):
    """Mirrors the WorkflowState DB record."""
    application_id: str
    status: str
    created_at: str
    updated_at: str


class AuditLogEntry(BaseModel):
    """Single audit log record."""
    id: int
    application_id: str
    action: str
    rule_triggered: Optional[str] = None
    result: str
    timestamp: str


class EvaluationResponse(BaseModel):
    """Full response returned by POST /evaluate."""
    application_id: str
    decision: str
    reason: str
    is_cached: bool = False
    state: WorkflowStateResponse
    audit_trail: list[AuditLogEntry] = []
