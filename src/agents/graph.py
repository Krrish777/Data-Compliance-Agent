"""
Graph builder — assembles and compiles the full LangGraph compliance pipeline.

This is the single entrypoint for running the agent. It wires every node
into a ``StateGraph`` with conditional edges, compiles it with a
checkpointer, and exposes helpers for invoke / stream.

Architecture
------------
    START
      │
      ▼
    rule_extraction  (LLM — reads PDF, extracts rules)
      │
      ▼
    schema_discovery (deterministic — reads DB schema)
      │
      ▼
    rule_structuring (LLM — maps rules to columns)  [stub → pass-through]
      │
      ├── confidence >= 0.7 → data_scanning
      └── confidence <  0.7 → human_review → data_scanning
      │
      ▼
    data_scanning     (deterministic — queries DB for violations)
      │
      ▼
    violation_reporting (deterministic — aggregates report)
      │
      ▼
    END

Usage
-----
    from src.agents.graph import build_graph
    from src.agents.memory import get_checkpointer
    from src.agents.runtime import make_config

    with get_checkpointer("memory") as cp:
        graph = build_graph(checkpointer=cp)
        config = make_config(thread_id="scan-001")
        result = graph.invoke(
            {
                "document_path": "/path/to/policy.pdf",
                "db_type": "sqlite",
                "db_config": {"db_path": "company.db"},
            },
            config=config,
        )
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from src.agents.nodes.data_scanning import data_scanning_node
from src.agents.nodes.explanation_generator import explanation_generator_node
from src.agents.nodes.report_generation import report_generation_node
from src.agents.nodes.rule_extraction import rule_extraction_node
from src.agents.nodes.schema_discovery import schema_discovery_node
from src.agents.nodes.violation_reporting import violation_reporting_node
from src.agents.nodes.violation_validator import violation_validator_node
from src.agents.state import ComplianceScannerState
from src.utils.logger import setup_logger

log = setup_logger(__name__)


# ── Stub nodes (to be built later) ──────────────────────────────────────────

def rule_structuring_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stub: pass raw_rules through as structured_rules.

    In production this will be an LLM node that maps each
    ``ComplianceRuleModel`` to a ``StructuredRule`` with real column names
    from ``schema_metadata``. For now it converts directly so the
    downstream scanning node has something to work with.
    """
    from src.models.structured_rule import StructuredRule

    raw_rules = state.get("raw_rules", [])
    schema_metadata = state.get("schema_metadata", {})
    all_tables = list(schema_metadata.keys()) or None

    structured: list = []
    low_confidence: list = []

    # Operators we cannot translate to ANY executable check — drop entirely.
    _TRULY_UNSCANNABLE = {"EXISTS", "SKIP", ""}

    # Complex operators — handled by Python complex_executor, not SQL.
    _BETWEEN_OPS = {"BETWEEN"}
    _REGEX_OPS   = {"REGEX", "REGEXP", "MATCHES", "MATCHES_REGEX",
                    "REGEX_MATCH", "LIKE_REGEX", "MATCHES_PATTERN"}

    # Date math keywords that signal runtime datetime comparison needed.
    _DATE_MATH_TOKENS = ("NOW()", "NOW", "INTERVAL", "DATETIME('NOW",
                         "CURRENT_TIMESTAMP", "CURRENT_DATE",
                         "DAYS", "MONTHS", "YEARS")

    # Comprehensive alias → canonical SQL operator mapping.
    # Keys must already be .upper().strip().
    _OP_ALIASES = {
        # equality
        "EQUAL": "=", "EQUALS": "=", "EQUAL TO": "=", "EQ": "=", "IS": "=",
        # inequality
        "NOT EQUAL": "!=", "NOT_EQUAL": "!=", "NOT EQUALS": "!=",
        "NEQ": "!=", "NE": "!=", "<>": "!=", "IS NOT": "!=", "ISNOT": "!=",
        # greater
        "GREATER THAN": ">", "GREATER_THAN": ">", "GT": ">", "GREATER": ">",
        # less
        "LESS THAN": "<", "LESS_THAN": "<", "LT": "<", "LESS": "<",
        # greater-or-equal
        "GREATER THAN OR EQUAL": ">=", "GREATER_THAN_OR_EQUAL": ">=",
        "GREATER OR EQUAL": ">=", "GTE": ">=", "GE": ">=",
        # less-or-equal
        "LESS THAN OR EQUAL": "<=", "LESS_THAN_OR_EQUAL": "<=",
        "LESS OR EQUAL": "<=", "LTE": "<=", "LE": "<=",
        # null checks — these express a CONSTRAINT; we flip them below to get the VIOLATION
        "IS NOT NULL": "IS NOT NULL", "IS_NOT_NULL": "IS NOT NULL",
        "ISNOTNULL": "IS NOT NULL", "NOT NULL": "IS NOT NULL",
        "NOT_NULL": "IS NOT NULL", "NOTNULL": "IS NOT NULL",
        "HAS VALUE": "IS NOT NULL", "PRESENT": "IS NOT NULL",
        "IS NULL": "IS NULL", "IS_NULL": "IS NULL", "ISNULL": "IS NULL",
        "NULL": "IS NULL", "EMPTY": "IS NULL", "IS EMPTY": "IS NULL",
        "MISSING": "IS NULL",
        # set membership
        "IN LIST": "IN", "IN_LIST": "IN", "IN SET": "IN", "IN_SET": "IN",
        "NOT IN LIST": "NOT IN", "NOT_IN_LIST": "NOT IN",
        "NOT IN SET": "NOT IN", "NOT_IN_SET": "NOT IN",
        # substring / pattern
        "CONTAINS": "CONTAINS", "INCLUDES": "CONTAINS",
        "STARTS WITH": "STARTS_WITH", "BEGINS WITH": "STARTS_WITH",
        "ENDS WITH": "ENDS_WITH",
    }

    # Track rule_ids already added so duplicate extractions from different chunks are skipped.
    _seen_rule_ids: set = set()

    for rule in raw_rules:
        rule_id   = rule.rule_id   if hasattr(rule, "rule_id")   else rule.get("rule_id", "")
        logic     = rule.logic     if hasattr(rule, "logic")     else rule.get("logic", None)
        rule_text = rule.rule_text if hasattr(rule, "rule_text") else rule.get("rule_text", "")
        rule_type = rule.rule_type if hasattr(rule, "rule_type") else rule.get("rule_type", "")
        confidence = rule.confidence if hasattr(rule, "confidence") else rule.get("confidence", 0.5)

        # Skip duplicate rule_ids (LLM may extract the same rule from multiple chunks)
        if rule_id in _seen_rule_ids:
            log.info(f"rule_structuring_node: skipping duplicate rule_id {rule_id!r}")
            continue

        # Determine column + operator from logic block
        if logic and getattr(logic, "field", None) and getattr(logic, "operator", None):
            col = logic.field.strip()          # strip accidental whitespace
            op  = logic.operator.upper().strip()
            val = logic.value if logic.value not in (None, "null", "NULL", "") else None
        else:
            # No scannable logic — skip entirely
            log.warning(
                f"rule_structuring_node: DROPPING rule {rule_id!r} — "
                f"no scannable logic (field+operator). "
                f"rule_text={rule_text[:80]!r}"
            )
            continue

        # Rules that point at multiple columns can't be mapped to a single SQL condition
        if " and " in col.lower() or col.strip() == "*":
            log.warning(
                f"rule_structuring_node: DROPPING rule {rule_id!r} — "
                f"multi-column field {col!r} cannot map to single SQL condition"
            )
            continue

        # ── Normalise operator via alias table first, then hard-coded specials ──
        op = _OP_ALIASES.get(op, op)   # resolve alias; unknown ops kept as-is

        # -- Classify rule complexity -----------------------------------------
        # Determine whether this rule needs the complex Python executor or
        # can go through standard SQL keyset scanning.

        rule_complexity = "simple"
        second_column: Optional[str] = None

        if op in _TRULY_UNSCANNABLE:
            log.warning(
                f"rule_structuring_node: DROPPING rule {rule_id!r} — "
                f"unscannable operator {op!r}"
            )
            continue

        if op in _BETWEEN_OPS:
            # BETWEEN: normalise value to "lo,hi" format
            rule_complexity = "between"
            # Forms: "1000 AND 10000" or "1000, 10000" or "1000-10000"
            if val:
                norm = re.sub(r'\bAND\b', ',', val, flags=re.IGNORECASE)
                norm = norm.replace(' - ', ',')
                val  = norm.strip()
            op = "BETWEEN"  # keep as-is; complex_executor handles it

        elif op in _REGEX_OPS:
            rule_complexity = "regex"

        elif op in ("=", "!=", ">", "<", ">=", "<=") and val:
            # Cross-field: if value matches a known column name in the schema
            all_columns: set = set()
            for tbl_info in schema_metadata.values():
                for col_info in tbl_info.get("columns", []):
                    all_columns.add(col_info.get("column_name", "").lower())
            if val.lower().strip() in all_columns and val.lower().strip() != col.lower().strip():
                rule_complexity = "cross_field"
                second_column   = val.strip()

            # Date-math: value contains datetime arithmetic tokens
            if rule_complexity == "simple" and any(
                tok in str(val).upper() for tok in _DATE_MATH_TOKENS
            ):
                rule_complexity = "date_math"

        # ── Constraint inversion: the scanner finds VIOLATIONS, so we must
        #    map null-related concepts to the correct IS NULL / IS NOT NULL. ──
        #
        # Two conceptual groups — both end up as IS NULL for the violation scan:
        #  (a) CONSTRAINT ops ("field MUST have value") → violation = IS NULL
        #      e.g. IS NOT NULL / NOT NULL / HAS VALUE / PRESENT
        #  (b) VIOLATION ops ("field has no value")    → already = IS NULL
        #      e.g. IS NULL / NULL / EMPTY / MISSING
        #
        # Comparison ops (=, !=, >, <, IN, LIKE …) already express the violating
        # row condition directly — no transformation needed.
        _NULL_OPS_TO_IS_NULL = {
            # constraint form
            "IS NOT NULL", "NOT NULL", "NOT_NULL", "NOTNULL",
            "HAS VALUE", "PRESENT",
            # violation form (already the null state)
            "IS NULL", "NULL", "IS_NULL", "ISNULL",
            "EMPTY", "IS EMPTY", "MISSING",
        }
        if op in _NULL_OPS_TO_IS_NULL:
            op = "IS NULL"

        # Auto-detect data_type from column name so numeric comparisons use
        # CAST semantics in the query builder (avoids string comparison on amounts)
        _NUMERIC_KEYWORDS = ("amount", "count", "balance", "fee", "rate", "price",
                             "quantity", "total", "sum", "laundering")
        _col_lower = col.lower()
        auto_data_type = "number" if any(k in _col_lower for k in _NUMERIC_KEYWORDS) else "string"

        # ── Expand substring-match shorthands into LIKE + wildcard-wrapped values ──
        if op == "CONTAINS":
            op  = "LIKE"
            val = f"%{val}%" if val else "%"
        elif op == "STARTS_WITH":
            op  = "LIKE"
            val = f"{val}%" if val else "%"
        elif op == "ENDS_WITH":
            op  = "LIKE"
            val = f"%{val}" if val else "%"

        sr = StructuredRule(
            rule_id=rule_id,
            rule_text=rule_text,
            source="pdf_extraction",
            rule_type=rule_type,
            target_column=col,
            operator=op, # type: ignore
            value=val,
            data_type=auto_data_type,
            applies_to_tables=all_tables,
            confidence=confidence,
            rule_complexity=rule_complexity,
            second_column=second_column,
        )

        _seen_rule_ids.add(rule_id)   # mark as seen AFTER successful structuring
        if sr.confidence >= 0.7:
            structured.append(sr)
        else:
            low_confidence.append(sr)

    log.info(
        f"rule_structuring_node (stub): {len(structured)} structured, "
        f"{len(low_confidence)} low-confidence"
    )

    return {
        "structured_rules": structured,
        "low_confidence_rules": low_confidence,
        "current_stage": "rules_structured",
    }


def human_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Human-in-the-loop review of low-confidence rules.

    Uses ``interrupt()`` to pause the graph and present rules to a human
    reviewer.  The reviewer can approve, edit, or drop each rule.

    When running non-interactively (e.g. ``run_hi_small.py``), the caller
    can pass ``review_decision`` pre-populated in state to skip the
    interrupt — this keeps backward compatibility with the batch runner.

    Resume payload schema::

        {
            "approved":  [rule_id, ...],
            "edited":    [{rule_id, changes: {...}}, ...],
            "dropped":   [rule_id, ...]
        }
    """
    from langgraph.types import interrupt

    structured = list(state.get("structured_rules", []))
    low_confidence = state.get("low_confidence_rules", [])

    if not low_confidence:
        log.info("human_review_node: no low-confidence rules — nothing to review")
        return {
            "structured_rules": structured,
            "review_decision": {"approved": [], "edited": [], "dropped": []},
            "current_stage": "review_complete",
        }

    # Check if a review decision was already provided (batch / test mode)
    existing_decision = state.get("review_decision")
    if existing_decision and existing_decision.get("approved") is not None:
        log.info("human_review_node: pre-populated review_decision found — skipping interrupt")
        review = existing_decision
    else:
        # ── Pause for human review ──────────────────────────────────────
        review_payload = {
            "message": (
                f"{len(low_confidence)} low-confidence rules need review. "
                "Approve, edit, or drop each rule."
            ),
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "rule_text": r.rule_text,
                    "target_column": r.target_column,
                    "operator": r.operator,
                    "value": r.value,
                    "confidence": r.confidence,
                    "rule_type": r.rule_type,
                }
                for r in low_confidence
            ],
        }
        review = interrupt(review_payload)

    # ── Process the review decision ─────────────────────────────────────
    approved_ids = set(review.get("approved", []))
    dropped_ids = set(review.get("dropped", []))
    edited_map: Dict[str, Dict] = {
        e["rule_id"]: e.get("changes", {})
        for e in review.get("edited", [])
        if isinstance(e, dict) and "rule_id" in e
    }

    for rule in low_confidence:
        if rule.rule_id in dropped_ids:
            continue
        if rule.rule_id in edited_map:
            changes = edited_map[rule.rule_id]
            for attr, new_val in changes.items():
                if hasattr(rule, attr):
                    setattr(rule, attr, new_val)
            structured.append(rule)
        elif rule.rule_id in approved_ids or not (approved_ids or edited_map or dropped_ids):
            # If no explicit decision provided, auto-approve (backward compat)
            structured.append(rule)

    log.info(
        f"human_review_node: approved={len(approved_ids)}, "
        f"edited={len(edited_map)}, dropped={len(dropped_ids)}"
    )

    return {
        "structured_rules": structured,
        "review_decision": {
            "approved": list(approved_ids),
            "edited": list(edited_map.keys()),
            "dropped": list(dropped_ids),
        },
        "current_stage": "review_complete",
    }


# ── Routing logic ────────────────────────────────────────────────────────────

def _route_after_structuring(state: Dict[str, Any]) -> str:
    """Decide whether human review is needed."""
    low_confidence = state.get("low_confidence_rules", [])
    if low_confidence:
        return "human_review"
    return "data_scanning"


# ── Graph builder ────────────────────────────────────────────────────────────

def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> Any:
    """
    Build and compile the full compliance scanning graph.

    Parameters
    ----------
    checkpointer : BaseCheckpointSaver, optional
        Persistence backend. Pass one from ``get_checkpointer()``.

    Returns
    -------
    CompiledGraph
        Ready to ``.invoke()`` or ``.stream()``.
    """
    workflow = StateGraph(ComplianceScannerState)

    # ── Add nodes ────────────────────────────────────────────────────────
    workflow.add_node("rule_extraction", rule_extraction_node)  # type: ignore
    workflow.add_node("schema_discovery", schema_discovery_node) # type: ignore
    workflow.add_node("rule_structuring", rule_structuring_node) # type: ignore
    workflow.add_node("human_review", human_review_node)  # type: ignore
    workflow.add_node("data_scanning", data_scanning_node) # type: ignore
    workflow.add_node("violation_validator", violation_validator_node) # type: ignore
    workflow.add_node("explanation_generator", explanation_generator_node) # type: ignore
    workflow.add_node("violation_reporting", violation_reporting_node) # type: ignore
    workflow.add_node("report_generation", report_generation_node)  # type: ignore

    # ── Add edges ────────────────────────────────────────────────────────
    workflow.add_edge(START, "rule_extraction")
    workflow.add_edge("rule_extraction", "schema_discovery")
    workflow.add_edge("schema_discovery", "rule_structuring")

    # Conditional: need human review?
    workflow.add_conditional_edges(
        "rule_structuring",
        _route_after_structuring,
        {
            "human_review": "human_review",
            "data_scanning": "data_scanning",
        },
    )

    workflow.add_edge("human_review", "data_scanning")
    workflow.add_edge("data_scanning", "violation_validator")
    workflow.add_edge("violation_validator", "explanation_generator")
    workflow.add_edge("explanation_generator", "violation_reporting")
    workflow.add_edge("violation_reporting", "report_generation")
    workflow.add_edge("report_generation", END)

    # ── Compile ──────────────────────────────────────────────────────────
    graph = workflow.compile(checkpointer=checkpointer)
    log.info("build_graph: compliance pipeline compiled successfully")
    return graph


# Module-level compiled graph instance required by LangGraph dev server / Studio.
# langgraph.json points to this file with variable name "agent".
agent = build_graph()
