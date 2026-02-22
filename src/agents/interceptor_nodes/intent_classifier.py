"""
Intent Classifier Node (Stage 1) — hybrid rules + LLM.

Determines whether the incoming query is CLEAR or VAGUE.

Fast path (90%): deterministic rules check for missing purpose,
SELECT *, multi-jurisdiction ambiguity.

Slow path (10%): Groq LLM (llama-3.1-8b-instant) for ambiguous cases.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal

from langgraph.types import Command

from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)


# ── Deterministic rules ──────────────────────────────────────────────────────

def _has_where_clause(sql: str) -> bool:
    return bool(re.search(r"\bWHERE\b", sql, re.IGNORECASE))


def _has_aggregation(sql: str) -> bool:
    return bool(re.search(
        r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP\s+BY)\b", sql, re.IGNORECASE
    ))


def _is_select_star(sql: str) -> bool:
    return bool(re.search(r"\bSELECT\s+\*", sql, re.IGNORECASE))


def _detect_missing_dimensions(
    context: Dict[str, Any],
) -> List[str]:
    """Return list of missing dimensions based on deterministic rules."""
    missing: List[str] = []

    stated_purpose = context.get("stated_purpose")
    if not stated_purpose:
        missing.append("PURPOSE")

    query = context.get("query", "")
    normalized = context.get("normalized_query", query.lower())

    if _is_select_star(query) and not _has_where_clause(query):
        missing.append("COLUMN_SCOPE")

    schema = context.get("schema_snapshot", {})
    if schema.get("has_multi_jurisdiction") and "jurisdiction" not in normalized:
        missing.append("JURISDICTION")

    if schema.get("has_pii") and not stated_purpose:
        missing.append("PII_JUSTIFICATION")

    return missing


# ── LLM fallback ─────────────────────────────────────────────────────────────

def _classify_with_llm(context: Dict[str, Any], missing: List[str]) -> Dict[str, Any]:
    """Use Groq (llama-3.1-8b-instant) for ambiguous intent classification."""
    from langchain_groq import ChatGroq

    user_ctx = context.get("user_context", {})
    prompt = f"""Analyze this data access query to determine if it is sufficiently clear to evaluate for compliance.

Query: {context.get("query", "")}
Stated Purpose: {context.get("stated_purpose") or "NOT PROVIDED"}
User Role: {user_ctx.get("role", "unknown")}

Potential issues detected:
{chr(10).join(f"- {dim}" for dim in missing)}

Is this query clear enough to evaluate? Consider:
- Can we infer the user's purpose from context?
- Is the column scope reasonable given the query type?
- Can we determine applicable regulations?

Respond with JSON only:
{{
    "is_clear": true or false,
    "additional_missing": [],
    "reasoning": "brief explanation"
}}"""

    try:
        llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0, max_tokens=500)
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)

        # Strip markdown fences
        text = re.sub(r"```json\s*", "", str(text))
        text = re.sub(r"```\s*", "", text).strip()
        return json.loads(text)
    except Exception as e:
        log.warning(f"intent_classifier LLM fallback failed: {e}")
        return {"is_clear": False, "additional_missing": [], "reasoning": "LLM failed"}


# ── Node ──────────────────────────────────────────────────────────────────────

def intent_classifier_node(
    state: InterceptorState,
) -> Command[Literal["policy_mapper", "return_clarification"]]:
    """
    Stage 1: Classify query intent as CLEAR or VAGUE.

    Routes to ``policy_mapper`` when clear, ``return_clarification`` when vague.
    """
    context = state.get("context_bundle") or {}
    cost = state.get("total_cost_usd", 0.0) or 0.0

    missing = _detect_missing_dimensions(context)

    # ── Fast path: definitely vague (2+ missing = don't bother with LLM) ─
    if len(missing) >= 2:
        result = {
            "status": "VAGUE",
            "missing_dimensions": missing,
            "clarification_message": _build_clarification_message(missing),
            "confidence_score": 0.95,
            "processing_method": "rule_based",
        }
        log.info(f"intent_classifier: VAGUE (rule_based) — missing={missing}")
        return Command(
            update={
                "intent_result": result,
                "current_stage": "intent_classified",
                "total_cost_usd": cost,
            },
            goto="return_clarification",
        )

    # ── Fast path: definitely clear (aggregation, no PII, 0 missing) ────
    query = context.get("query", "")
    if len(missing) == 0 and _has_aggregation(query):
        result = {
            "status": "CLEAR",
            "missing_dimensions": [],
            "clarification_message": None,
            "confidence_score": 0.99,
            "processing_method": "rule_based",
        }
        log.info("intent_classifier: CLEAR (rule_based, aggregation)")
        return Command(
            update={
                "intent_result": result,
                "current_stage": "intent_classified",
                "total_cost_usd": cost,
            },
            goto="policy_mapper",
        )

    # ── Fast path: 0 missing dimensions ─────────────────────────────────
    if len(missing) == 0:
        result = {
            "status": "CLEAR",
            "missing_dimensions": [],
            "clarification_message": None,
            "confidence_score": 0.90,
            "processing_method": "rule_based",
        }
        log.info("intent_classifier: CLEAR (rule_based)")
        return Command(
            update={
                "intent_result": result,
                "current_stage": "intent_classified",
                "total_cost_usd": cost,
            },
            goto="policy_mapper",
        )

    # ── Slow path: 1 missing dimension → ask LLM ────────────────────────
    llm_result = _classify_with_llm(context, missing)
    cost += 0.0015  # Approximate cost for 8b-instant

    if llm_result.get("is_clear", False):
        result = {
            "status": "CLEAR",
            "missing_dimensions": missing,
            "clarification_message": None,
            "confidence_score": 0.75,
            "processing_method": "llm_classified",
        }
        log.info("intent_classifier: CLEAR (llm_classified)")
        return Command(
            update={
                "intent_result": result,
                "current_stage": "intent_classified",
                "total_cost_usd": cost,
            },
            goto="policy_mapper",
        )
    else:
        all_missing = list(set(missing + llm_result.get("additional_missing", [])))
        result = {
            "status": "VAGUE",
            "missing_dimensions": all_missing,
            "clarification_message": _build_clarification_message(all_missing),
            "confidence_score": 0.80,
            "processing_method": "llm_classified",
        }
        log.info(f"intent_classifier: VAGUE (llm_classified) — missing={all_missing}")
        return Command(
            update={
                "intent_result": result,
                "current_stage": "intent_classified",
                "total_cost_usd": cost,
            },
            goto="return_clarification",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_clarification_message(missing: List[str]) -> str:
    """Build a user-friendly clarification request."""
    lines = ["Please provide the following information:"]
    prompts = {
        "PURPOSE": "- The specific purpose for accessing this data (analytics, support, marketing, etc.)",
        "COLUMN_SCOPE": "- Which specific columns you need instead of SELECT *",
        "JURISDICTION": "- The jurisdiction/country filter for this multi-jurisdiction data",
        "PII_JUSTIFICATION": "- Justification for accessing PII data (business need, legal basis)",
    }
    for dim in missing:
        lines.append(prompts.get(dim, f"- Details about: {dim}"))
    return "\n".join(lines)
