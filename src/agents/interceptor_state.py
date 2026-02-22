"""
LangGraph state schema for the Interceptor (real-time query enforcement) mode.

This TypedDict is the contract between all interceptor nodes.
Separate from ComplianceScannerState because the interceptor handles
individual queries (real-time) while the scanner handles batch scans.
"""
import operator
from typing import Annotated, Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict


class InterceptorState(TypedDict, total=False):
    """
    State for the real-time compliance interceptor pipeline.

    Flow
    ----
    QUERY_IN → cache_check → context_builder → intent_classifier
             → policy_mapper → verdict_reasoner → auditor → executor → END
    """

    # ── Input ────────────────────────────────────────────────────────────────
    query: str                       # Raw SQL query to evaluate
    user_id: str                     # Who is requesting
    user_role: str                   # Role of the requester
    stated_purpose: Optional[str]    # Why they need the data
    session_id: str                  # Unique request ID for tracing

    # ── Database connection (for schema lookups & query execution) ────────────
    db_config: Dict[str, Any]
    db_type: Literal["sqlite", "postgresql"]

    # ── Cache ────────────────────────────────────────────────────────────────
    cache_hit: bool
    cache_layer: Optional[str]       # "exact" | "fuzzy" | "semantic" | None
    cached_decision: Optional[Dict[str, Any]]

    # ── Stage 0: Context Builder ─────────────────────────────────────────────
    context_bundle: Optional[Dict[str, Any]]   # Serialised ContextBundle

    # ── Stage 1: Intent Classifier ───────────────────────────────────────────
    intent_result: Optional[Dict[str, Any]]    # Serialised IntentClassificationResult

    # ── Stage 2: Policy Mapper ───────────────────────────────────────────────
    policy_mapping: Optional[Dict[str, Any]]   # Serialised PolicyMappingResult

    # ── Stage 3: Verdict Reasoner ────────────────────────────────────────────
    verdict: Optional[Dict[str, Any]]          # Serialised ComplianceVerdict

    # ── Stage 4: Auditor ─────────────────────────────────────────────────────
    audit_result: Optional[Dict[str, Any]]     # Serialised AuditCheckResult

    # ── Execution / Output ───────────────────────────────────────────────────
    final_decision: Optional[Literal["APPROVE", "BLOCK",
                                      "CLARIFICATION_REQUIRED", "ESCALATED"]]
    block_reason: Optional[str]
    guidance: Optional[str]
    query_results: Optional[Any]               # Results if APPROVE'd

    # ── Execution metadata ───────────────────────────────────────────────────
    current_stage: str
    retry_counts: Dict[str, int]
    errors: Annotated[List[str], operator.add]
    total_cost_usd: float
    processing_start_time: Optional[str]       # ISO timestamp
