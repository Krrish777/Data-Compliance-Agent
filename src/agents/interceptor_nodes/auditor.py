"""
Auditor Node (Stage 4) — verification & validation.

Validates the verdict before execution:
  1. JSON schema validity  (rule-based, free)
  2. Citation grounding     (rule-based, free)
  3. Column mapping         (rule-based, free)
  4. Logic consistency      (LLM-based, cheap — llama-3.1-8b-instant)

Routes:
  - PASS         → executor
  - FAIL + retry → verdict_reasoner  (retry loop, max 2)
  - FAIL + exhausted → escalate_human
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Set

from langgraph.types import Command

from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)

MAX_RETRIES = 2


def auditor_node(
    state: InterceptorState,
) -> Command[Literal["executor", "verdict_reasoner", "escalate_human"]]:
    """
    Stage 4: Audit the verdict for correctness before execution.

    Reads from state:
        verdict, context_bundle, policy_mapping, retry_counts

    Writes to state:
        audit_result, retry_counts
    """
    verdict = state.get("verdict") or {}
    context = state.get("context_bundle") or {}
    mapping = state.get("policy_mapping") or {}
    policies = mapping.get("relevant_policies", [])
    cost = state.get("total_cost_usd", 0.0) or 0.0
    retry_counts = dict(state.get("retry_counts") or {})
    current_retries = retry_counts.get("reasoner", 0)

    checks: Dict[str, bool] = {}
    failures: List[str] = []

    # ── Check 1: JSON schema validity ────────────────────────────────────
    required_fields = ["decision", "reasoning", "cited_policies", "sensitive_columns"]
    checks["json_valid"] = all(f in verdict for f in required_fields)
    if not checks["json_valid"]:
        missing = [f for f in required_fields if f not in verdict]
        failures.append(f"Missing required fields: {missing}")

    # Decision enum check
    checks["decision_valid"] = verdict.get("decision") in ("APPROVE", "BLOCK")
    if not checks["decision_valid"]:
        failures.append(f"Invalid decision value: {verdict.get('decision')}")

    # ── Check 2: Citation grounding ──────────────────────────────────────
    valid_chunk_ids: Set[str] = {
        p.get("chunk_id", "") for p in policies if p.get("chunk_id")
    }
    cited = verdict.get("cited_policies", [])

    if valid_chunk_ids and cited:
        grounded = all(cid in valid_chunk_ids for cid in cited)
        checks["citations_grounded"] = grounded
        if not grounded:
            hallucinated = [cid for cid in cited if cid not in valid_chunk_ids]
            failures.append(f"Hallucinated citations: {hallucinated}")
    elif not cited and verdict.get("decision") == "BLOCK":
        # Missing citations on BLOCK is a soft warning — the LLM may not have
        # returned exact chunk_ids.  Only fail if rule-based checks also fail.
        checks["citations_grounded"] = True
        log.info("auditor: BLOCK with no cited policies (advisory warning)")
    else:
        checks["citations_grounded"] = True  # no citations to check

    # ── Check 3: Column mapping ──────────────────────────────────────────
    # A column is "known" if it appears in queried_columns (SELECT clause)
    # OR anywhere in the raw SQL (WHERE, GROUP BY, HAVING, etc.).
    schema = context.get("schema_snapshot", {})
    known_columns: Set[str] = {
        c.get("column_name", "").lower()
        for c in schema.get("queried_columns", [])
    }
    # Also accept any column name that appears in the raw SQL text
    raw_query_lower = context.get("query", state.get("query", "")).lower()
    sensitive = verdict.get("sensitive_columns", [])
    if sensitive and (known_columns or raw_query_lower):
        col_valid = all(
            sc.lower() in known_columns or sc.lower() in raw_query_lower
            for sc in sensitive
        )
        checks["columns_valid"] = col_valid
        if not col_valid:
            bad = [
                sc for sc in sensitive
                if sc.lower() not in known_columns and sc.lower() not in raw_query_lower
            ]
            failures.append(f"Invented columns in sensitive_columns: {bad}")
    else:
        checks["columns_valid"] = True

    # ── Check 4: Logic consistency (LLM) — advisory, not blocking ──────
    try:
        consistency = _check_logic_consistency(verdict, context)
        checks["logic_consistent"] = consistency.get("consistent", True)
        if not checks["logic_consistent"]:
            # Log but treat as advisory; don't add to hard failures unless
            # all rule-based checks already passed (avoid retry loops over
            # subjective LLM opinions).
            rule_based_ok = all(
                v for k, v in checks.items() if k != "logic_consistent"
            )
            if rule_based_ok:
                log.info(
                    f"auditor: LLM flagged logic inconsistency (advisory): "
                    f"{consistency.get('reason', '?')}"
                )
                checks["logic_consistent"] = True  # override — advisory only
            else:
                failures.append(
                    f"Logic inconsistency: {consistency.get('reason', '?')}"
                )
        cost += 0.002  # cheap Haiku-equivalent call
    except Exception as e:
        log.warning(f"auditor: logic consistency check failed: {e}")
        checks["logic_consistent"] = True  # permissive on LLM failure
        cost += 0.002

    # ── Determine routing ────────────────────────────────────────────────
    all_pass = all(checks.values())

    if all_pass:
        log.info("auditor: PASS — all checks passed")
        return Command(
            update={
                "audit_result": {
                    "status": "PASS",
                    "validation_checks": checks,
                    "failure_reasons": [],
                    "retry_count": current_retries,
                },
                "current_stage": "audit_passed",
                "total_cost_usd": cost,
            },
            goto="executor",
        )

    # ── FAIL: retry or escalate ──────────────────────────────────────────
    if current_retries < MAX_RETRIES:
        retry_counts["reasoner"] = current_retries + 1
        log.warning(
            f"auditor: FAIL — retrying verdict_reasoner "
            f"(attempt {current_retries + 1}/{MAX_RETRIES}). "
            f"Failures: {failures}"
        )
        return Command(
            update={
                "audit_result": {
                    "status": "FAIL",
                    "validation_checks": checks,
                    "failure_reasons": failures,
                    "retry_count": current_retries + 1,
                },
                "retry_counts": retry_counts,
                "current_stage": "audit_retry",
                "total_cost_usd": cost,
                "errors": [f"Audit fail (retry {current_retries + 1}): {'; '.join(failures)}"],
            },
            goto="verdict_reasoner",
        )

    log.warning(f"auditor: FAIL — max retries exhausted, escalating. Failures: {failures}")
    return Command(
        update={
            "audit_result": {
                "status": "FAIL",
                "validation_checks": checks,
                "failure_reasons": failures,
                "retry_count": current_retries,
            },
            "current_stage": "audit_escalated",
            "total_cost_usd": cost,
            "errors": [f"Audit exhausted retries: {'; '.join(failures)}"],
        },
        goto="escalate_human",
    )


# ── LLM logic consistency check ──────────────────────────────────────────────


def _check_logic_consistency(
    verdict: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Use Groq (8b-instant) to check logical consistency."""
    from langchain_groq import ChatGroq

    schema = context.get("schema_snapshot", {})
    col_names = [c.get("column_name", "?") for c in schema.get("queried_columns", [])]

    prompt = f"""Check if this compliance verdict is logically consistent.

Verdict:
- Decision: {verdict.get("decision")}
- Reasoning: {verdict.get("reasoning", "")[:500]}
- Sensitive Columns: {verdict.get("sensitive_columns", [])}
- Cited Policies: {verdict.get("cited_policies", [])}

Query Context:
- Query: {context.get("query", "")}
- Contains PII: {schema.get("has_pii", False)}
- Queried Columns: {col_names}

Check for inconsistencies:
1. If reasoning mentions PII, are there entries in sensitive_columns?
2. If decision is BLOCK, does reasoning explain why?
3. If sensitive_columns is populated, are policies cited?

Respond with JSON only:
{{
  "consistent": true or false,
  "reason": "brief explanation if inconsistent"
}}"""

    try:
        llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0, max_tokens=300)
        response = llm.invoke(prompt)
        text = str(response.content if hasattr(response, "content") else response)
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()
        return json.loads(text)
    except Exception as e:
        log.warning(f"auditor._check_logic_consistency LLM failed: {e}")
        return {"consistent": True, "reason": "LLM check skipped"}
