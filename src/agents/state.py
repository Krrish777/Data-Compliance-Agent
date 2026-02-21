"""
LangGraph state schema for the Data Compliance Agent.

This TypedDict is the single contract between all nodes in the graph.
Every node reads from and writes back a subset of these keys.
"""
import operator
from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict

from src.models.compilance_rules import ComplianceRuleModel
from src.models.structured_rule import StructuredRule


class ComplianceScannerState(TypedDict, total=False):
    """
    Central state object for the compliance scanning pipeline.

    Key naming convention
    ---------------------
    - Outputs of a stage are written with the stage name as prefix where
      ambiguous (e.g. scan_summary, violation_report).
    - Lists that are accumulated across nodes use Annotated[list, operator.add]
      so each node can append without overwriting previous values.
    """

    # ── Stage 0: entry ──────────────────────────────────────────────────────
    document_path: str          # Absolute path to the policy PDF
    db_config: Dict[str, Any]   # {db_path: "..."} for SQLite or
                                # {host, port, database, user, password} for Postgres
    db_type: Literal["sqlite", "postgresql"]

    # ── Stage 1: rule_extraction (YOU build) ────────────────────────────────
    # The LLM reads the PDF chunks and produces a list of raw, unstructured rules.
    # Use Annotated + operator.add so the LLM can stream multi-chunk results.
    raw_rules: Annotated[List[ComplianceRuleModel], operator.add]

    # ── Stage 2: schema_discovery (ME) ──────────────────────────────────────
    # Keyed by table name. Each value is:
    #   {columns: [{column_name, data_type, ...}], primary_key: str|tuple|None,
    #    row_count: int}
    schema_metadata: Dict[str, Dict[str, Any]]

    # ── Stage 3: rule_structuring (YOU build) ───────────────────────────────
    # Rules the LLM confidently mapped to real columns (confidence >= 0.7).
    structured_rules: List[StructuredRule]
    # Rules the LLM was unsure about — routed to human_review before scanning.
    low_confidence_rules: List[StructuredRule]

    # ── Stage 3b: human_review (YOU build) ──────────────────────────────────
    # Populated after the interrupt resumes. The node merges approved/edited
    # rules back into structured_rules before handing off to data_scanning.
    review_decision: Dict[str, Any]   # {approved: [...], edited: [...], dropped: [...]}

    # ── Stage 4: data_scanning (ME) ─────────────────────────────────────────
    scan_id: str
    violations_db_path: str           # Path to the SQLite violations log DB
    scan_summary: Dict[str, Any]      # Counts only — no full records in state
    batch_size: int                   # Rows per keyset page (default 1000)
    max_batches_per_table: Optional[int]  # Safety cap; None = unlimited

    # ── Stage 4b: violation_validator ───────────────────────────────────────
    validation_summary: Dict[str, Any]  # {confirmed, false_positives, skipped, by_rule}

    # ── Stage 5a: explanation_generator ─────────────────────────────────────
    rule_explanations: Dict[str, Any]   # {rule_id: {explanation, clause, remediation, severity}}

    # ── Stage 5b: violation_reporting (ME) ──────────────────────────────────
    violation_report: Dict[str, Any]

    # ── Cross-cutting ────────────────────────────────────────────────────────
    current_stage: str
    # Errors accumulate across nodes; Annotated+add means each node appends.
    errors: Annotated[List[str], operator.add]
