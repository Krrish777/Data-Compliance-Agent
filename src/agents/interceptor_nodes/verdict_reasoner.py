"""
Verdict Reasoner Node (Stage 3) — heavy LLM reasoning.

Uses Groq (llama-3.3-70b-versatile) to generate a compliance verdict
(APPROVE / BLOCK) with full reasoning, cited policies, and identified
sensitive columns.

This is the most expensive stage (~$0.045 per query).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def verdict_reasoner_node(state: InterceptorState) -> Dict[str, Any]:
    """
    Stage 3: Generate compliance verdict using Groq LLM.

    Reads from state:
        context_bundle, policy_mapping

    Writes to state:
        verdict  (serialised ComplianceVerdict dict)
    """
    context = state.get("context_bundle") or {}
    mapping = state.get("policy_mapping") or {}
    policies = mapping.get("relevant_policies", [])
    cost = state.get("total_cost_usd", 0.0) or 0.0

    prompt = _build_reasoning_prompt(context, policies)

    try:
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.0,
            max_tokens=2000,
        )
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        log.error(f"verdict_reasoner: LLM call failed: {e}")
        return {
            "verdict": _fallback_verdict(str(e)),
            "current_stage": "verdict_generated",
            "total_cost_usd": cost + 0.045,
        }

    # Parse JSON from LLM response
    verdict = _parse_verdict(str(text), policies)
    cost += 0.045

    log.info(
        f"verdict_reasoner: decision={verdict.get('decision', 'UNKNOWN')}, "
        f"cited={len(verdict.get('cited_policies', []))}, "
        f"sensitive_cols={len(verdict.get('sensitive_columns', []))}"
    )

    return {
        "verdict": verdict,
        "current_stage": "verdict_generated",
        "total_cost_usd": cost,
    }


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_reasoning_prompt(
    context: Dict[str, Any],
    policies: List[Dict[str, Any]],
) -> str:
    """Build a focused reasoning prompt from raw state data."""
    user_ctx = context.get("user_context", {})
    schema = context.get("schema_snapshot", {})

    # Format policy chunks
    policy_lines: List[str] = []
    for p in policies:
        cid = p.get("chunk_id", "?")
        article = p.get("article_number", "")
        title = p.get("article_title", "")
        text = p.get("full_text", "")
        policy_lines.append(f"[{cid}] {article} — {title}\n{text}")
    policy_text = "\n\n".join(policy_lines) if policy_lines else "(No specific policies retrieved)"

    # Format columns
    col_lines: List[str] = []
    for col in schema.get("queried_columns", []):
        cname = col.get("column_name", "?")
        dtype = col.get("data_type", "?")
        pii = "PII" if col.get("is_pii") else "non-PII"
        cats = ", ".join(col.get("pii_categories", []))
        cls_ = col.get("classification", "internal")
        detail = f"- {cname} ({dtype}): {pii}"
        if cats:
            detail += f" [{cats}]"
        detail += f" classification={cls_}"
        col_lines.append(detail)
    columns_text = "\n".join(col_lines) if col_lines else "- (no column metadata)"

    approved = ", ".join(user_ctx.get("approved_purposes", [])) or "none specified"
    sample_chunk_id = policies[0].get("chunk_id", "RULE_X") if policies else "RULE_X"

    return f"""You are a compliance decision engine evaluating data access requests.

QUERY: {context.get("query", "")}

USER CONTEXT:
- Role: {user_ctx.get("role", "unknown")}
- Department: {user_ctx.get("department", "unknown")}
- Stated Purpose: {context.get("stated_purpose") or "NOT PROVIDED"}
- Approved Purposes: {approved}
- Access Level: {user_ctx.get("data_access_level", 1)}/5

SCHEMA CONTEXT:
Tables: {", ".join(schema.get("queried_tables", []))}
Columns:
{columns_text}

Data Classification: {schema.get("max_classification", "internal")}
Contains PII: {schema.get("has_pii", False)}

APPLICABLE POLICIES (you MUST cite only from this list):
{policy_text}

TASK:
Determine if this query complies with the listed policies.

CRITICAL RULES:
1. ONLY cite policy chunk IDs from the list above (e.g., [{sample_chunk_id}])
2. Identify ALL sensitive columns (PII, protected data)
3. If uncertain or policies conflict, choose BLOCK
4. Reference specific policy clauses in your reasoning

OUTPUT (strict JSON, no markdown fences):
{{
  "decision": "APPROVE" or "BLOCK",
  "reasoning": "Detailed explanation citing specific policies",
  "cited_policies": ["chunk_id_1", "chunk_id_2"],
  "sensitive_columns": ["col1", "col2"],
  "required_controls": ["log_access", "mask_pii"]
}}"""


# ── Response parsing ──────────────────────────────────────────────────────────


def _parse_verdict(
    text: str,
    policies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Parse LLM JSON response into a verdict dict.  Graceful fallback."""
    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()

    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        log.warning("verdict_reasoner: JSON parse failed — constructing from text")
        return _fallback_verdict(f"Unparseable LLM response: {text[:200]}")

    # Normalise decision
    decision = str(verdict.get("decision", "BLOCK")).upper().strip()
    if decision not in ("APPROVE", "BLOCK"):
        decision = "BLOCK"

    return {
        "decision": decision,
        "reasoning": verdict.get("reasoning", ""),
        "cited_policies": verdict.get("cited_policies", []),
        "sensitive_columns": verdict.get("sensitive_columns", []),
        "required_controls": verdict.get("required_controls", []),
        "confidence": verdict.get("confidence", 0.7),
    }


def _fallback_verdict(error_msg: str) -> Dict[str, Any]:
    """Safe default: BLOCK with error context."""
    return {
        "decision": "BLOCK",
        "reasoning": f"Verdict generation failed: {error_msg}. Blocking by default for safety.",
        "cited_policies": [],
        "sensitive_columns": [],
        "required_controls": ["manual_review"],
        "confidence": 0.0,
    }
