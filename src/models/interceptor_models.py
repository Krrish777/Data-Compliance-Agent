"""
Data models for the Interceptor (real-time query enforcement) mode.

These Pydantic models define the structured data flowing through each
interceptor stage: context building, intent classification, policy mapping,
verdict reasoning, auditing, and execution.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════════════════
# Schema & User Context
# ═══════════════════════════════════════════════════════════════════════════════


class ColumnMetadata(BaseModel):
    """Metadata for a single database column."""

    column_name: str
    table_name: str
    data_type: str = "string"
    is_pii: bool = False
    pii_categories: List[str] = Field(default_factory=list)
    jurisdiction: Optional[str] = None
    classification: str = "internal"  # public | internal | confidential | restricted


class SchemaSnapshot(BaseModel):
    """Schema context assembled for the intercepted query."""

    queried_tables: List[str] = Field(default_factory=list)
    queried_columns: List[ColumnMetadata] = Field(default_factory=list)
    has_pii: bool = False
    has_multi_jurisdiction: bool = False
    max_classification: str = "internal"


class UserContext(BaseModel):
    """User identity, role, and authorised purposes."""

    user_id: str
    role: str = "analyst"
    department: str = "unknown"
    jurisdiction: str = "unknown"
    approved_purposes: List[str] = Field(default_factory=list)
    data_access_level: int = Field(default=1, ge=1, le=5)


class ContextBundle(BaseModel):
    """Complete context assembled in the Context Builder node (Stage 0)."""

    query: str
    normalized_query: str = ""
    user_context: UserContext
    schema_snapshot: SchemaSnapshot = Field(default_factory=SchemaSnapshot)
    stated_purpose: Optional[str] = None
    bundle_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_hash(self) -> str:
        """Deterministic hash for caching — same role + query → same hash."""
        payload = (
            f"{self.normalized_query}|{self.user_context.role}|"
            f"{','.join(sorted(self.schema_snapshot.queried_tables))}|"
            f"{','.join(sorted(c.column_name for c in self.schema_snapshot.queried_columns))}"
        )
        self.bundle_hash = hashlib.sha256(payload.encode()).hexdigest()
        return self.bundle_hash


# ═══════════════════════════════════════════════════════════════════════════════
# Stage Outputs
# ═══════════════════════════════════════════════════════════════════════════════


class IntentClassificationResult(BaseModel):
    """Output of the Intent Classifier (Stage 1)."""

    status: Literal["CLEAR", "VAGUE"] = "CLEAR"
    missing_dimensions: List[str] = Field(default_factory=list)
    clarification_message: Optional[str] = None
    confidence_score: float = 1.0
    processing_method: str = "rule_based"  # rule_based | llm_classified


class PolicyChunk(BaseModel):
    """A single policy chunk retrieved from the vector DB."""

    chunk_id: str
    framework: str = "AML"  # AML | GDPR | HIPAA | CCPA | ...
    article_number: str = ""
    article_title: str = ""
    full_text: str = ""
    concepts: List[str] = Field(default_factory=list)
    version: str = "1.0"
    effective_date: Optional[datetime] = None
    score: float = 0.0  # retrieval similarity score


class PolicyMappingResult(BaseModel):
    """Output of the Policy Mapper (Stage 2)."""

    status: Literal["CONFIDENT", "UNCERTAIN"] = "UNCERTAIN"
    relevant_policies: List[PolicyChunk] = Field(default_factory=list)
    confidence_scores: Dict[str, float] = Field(default_factory=dict)
    overall_confidence: float = 0.0


class ComplianceVerdict(BaseModel):
    """Output of the Verdict Reasoner (Stage 3)."""

    decision: Literal["APPROVE", "BLOCK"] = "BLOCK"
    reasoning: str = ""
    cited_policies: List[str] = Field(default_factory=list)
    sensitive_columns: List[str] = Field(default_factory=list)
    required_controls: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    @field_validator("decision", mode="before")
    @classmethod
    def normalise_decision(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.upper().strip()
        if v not in ("APPROVE", "BLOCK"):
            return "BLOCK"
        return v


class AuditCheckResult(BaseModel):
    """Output of the Auditor (Stage 4)."""

    status: Literal["PASS", "FAIL"] = "FAIL"
    validation_checks: Dict[str, bool] = Field(default_factory=dict)
    failure_reasons: List[str] = Field(default_factory=list)
    retry_count: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Log Entry (immutable record)
# ═══════════════════════════════════════════════════════════════════════════════


class AuditLogEntry(BaseModel):
    """Immutable audit log record for every interceptor decision."""

    log_id: str = ""
    session_id: str = ""
    query: str = ""
    user_id: str = ""
    user_role: str = ""
    stated_purpose: Optional[str] = None
    decision: Literal["APPROVE", "BLOCK", "CLARIFICATION_REQUIRED", "ESCALATED"] = "BLOCK"
    reasoning: str = ""
    cited_policies: List[str] = Field(default_factory=list)
    sensitive_columns: List[str] = Field(default_factory=list)
    cache_hit: bool = False
    cache_layer: Optional[str] = None
    total_cost_usd: float = 0.0
    processing_time_ms: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage_outputs: Dict[str, Any] = Field(default_factory=dict)
