"""
Explanation Generator Node — Stage 5.

LLM-powered natural language explanation engine.

For every rule that produced violations the node generates:
  - explanation        : Why these records violate the policy (plain English,
                         2-4 sentences, references exact column + threshold).
  - policy_clause      : The specific policy section / clause being violated.
  - remediation_steps  : Ordered list of concrete actions to fix the issue.
  - severity           : HIGH | MEDIUM | LOW based on violation scope.
  - risk_description   : One sentence on business/legal risk if unresolved.

One LLM call per rule (never per-row). Up to 5 sample records are included
so the LLM can reference real data patterns.

Model: llama-3.3-70b-versatile (larger model for synthesis quality).
Token budget: ~2 000 input tokens per call (rule + 5 sample records).

Stores results in the rule_explanations table via violations_store helpers
and emits rule_explanations dict into LangGraph state.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_groq import ChatGroq
from sqlmodel import Session, create_engine, text

from src.agents.tools.database.violations_store import (
    create_explanations_table,
    get_scan_summary,
    get_violations_by_scan,
    store_rule_explanation,
)
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL          = "llama-3.3-70b-versatile"
_SAMPLE_RECORDS = 5     # records shown to LLM per rule
_SEVERITY_MAP   = {     # violation count thresholds → severity
    "HIGH":   500,
    "MEDIUM": 50,
    "LOW":    0,
}

_SYSTEM_PROMPT = """You are a senior compliance officer writing an audit report.
For each compliance rule violation you will receive:
  - The policy rule text
  - The column and condition that was checked
  - The violation count
  - A sample of violating records

Generate a structured JSON explanation with these exact keys:
{
  "explanation": "<2-4 sentence plain-English explanation of WHY these records violate the rule>",
  "policy_clause": "<specific policy section or clause reference, e.g. 'Section 3.2 — Large Transaction Reporting'>",
  "remediation_steps": ["<step 1>", "<step 2>", ...],
  "severity": "HIGH"|"MEDIUM"|"LOW",
  "risk_description": "<one sentence on legal/business risk if unresolved>"
}

Be specific about the column name, threshold value, and actual data patterns seen.
Return ONLY the JSON object — no markdown fences, no other text."""

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _infer_severity(violation_count: int) -> str:
    if violation_count >= _SEVERITY_MAP["HIGH"]:
        return "HIGH"
    if violation_count >= _SEVERITY_MAP["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _slim_violation(v: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a compact record preview from a violation row."""
    raw = v.get("violating_data") or v.get("violating_record") or "{}"
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    else:
        data = raw or {}
    # Keep first 6 columns to stay token-efficient
    items = list(data.items())[:6]
    return {
        "pk":     v.get("record_primary_key", "?"),
        "sample": dict(items),
    }


def _build_prompt(
    rule_text: str,
    target_column: str,
    operator: str,
    value: str,
    violation_count: int,
    sample_records: List[Dict[str, Any]],
) -> str:
    sample_text = json.dumps(
        [_slim_violation(r) for r in sample_records[:_SAMPLE_RECORDS]],
        indent=2,
    )
    return (
        f"Rule: {rule_text}\n\n"
        f"Check: column='{target_column}', operator='{operator}', value='{value}'\n"
        f"Violation count: {violation_count}\n\n"
        f"Sample violating records ({min(len(sample_records), _SAMPLE_RECORDS)}):\n"
        f"{sample_text}\n\n"
        "Generate the JSON explanation now."
    )


def _call_llm(llm: ChatGroq, human_msg: str) -> Dict[str, Any]:
    """Invoke LLM and parse JSON response. Returns {} on any failure."""
    try:
        response = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": human_msg},
        ])
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        log.warning(f"explanation_generator LLM call failed: {exc}")
        return {}

    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not m:
        log.warning("explanation_generator: no JSON found in LLM response")
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        log.warning(f"explanation_generator JSON parse error: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def explanation_generator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: generate LLM explanations for every rule that has violations.

    Reads from state
    ----------------
    - scan_id
    - violations_db_path
    - structured_rules

    Writes to state
    ---------------
    - rule_explanations : {rule_id: {explanation, policy_clause, remediation_steps,
                                     severity, risk_description, violation_count}}
    - current_stage     : 'explanations_complete' | 'explanations_skipped'
    """
    scan_id = state.get("scan_id", "")
    violations_db_path = state.get("violations_db_path", "violations.db")
    structured_rules = state.get("structured_rules", [])

    if not scan_id:
        log.warning("explanation_generator_node: no scan_id — skipping")
        return {
            "rule_explanations": {},
            "current_stage": "explanations_skipped",
        }

    db_path = Path(violations_db_path)
    if not db_path.exists():
        log.warning(f"explanation_generator_node: violations DB not found at {db_path}")
        return {
            "rule_explanations": {},
            "current_stage": "explanations_skipped",
        }

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        log.warning("explanation_generator_node: GROQ_API_KEY not set — skipping")
        return {
            "rule_explanations": {},
            "current_stage": "explanations_skipped",
        }

    # Build rule lookup: rule_id → StructuredRule (or dict)
    rule_lookup: Dict[str, Any] = {}
    for rule in structured_rules:
        rid = rule.rule_id if hasattr(rule, "rule_id") else rule.get("rule_id", "")
        rule_lookup[rid] = rule

    llm = ChatGroq(model=_MODEL, api_key=api_key, temperature=0)  # type: ignore
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    rule_explanations: Dict[str, Any] = {}

    with Session(engine) as session:
        # Ensure the table exists
        create_explanations_table(session)

        # Get violation counts per rule
        scan_summary = get_scan_summary(session, scan_id)
        # violations_by_rule is not in get_scan_summary — query separately
        counts_sql = text("""
            SELECT rule_id, COUNT(*) as cnt
              FROM violations_log
             WHERE scan_id = :scan_id
             GROUP BY rule_id
        """)
        counts_result = session.exec(counts_sql, params={"scan_id": scan_id})  # type: ignore
        counts_rows   = counts_result.fetchall()
        violations_by_rule: Dict[str, int] = {r[0]: r[1] for r in counts_rows}

        # Fetch all violations once and group by rule_id for sampling
        all_violations = get_violations_by_scan(session, scan_id)
        by_rule: Dict[str, List[Dict[str, Any]]] = {}
        for v in all_violations:
            rid = v.get("rule_id", "")
            by_rule.setdefault(rid, []).append(v)

        # Process rules that have > 0 violations
        for rule_id, count in violations_by_rule.items():
            if count == 0:
                continue

            rule = rule_lookup.get(rule_id)
            if rule is None:
                log.debug(f"explanation_generator: rule '{rule_id}' not in structured_rules — skipping")
                continue

            rule_text      = rule.rule_text      if hasattr(rule, "rule_text")      else rule.get("rule_text", "")
            target_column  = rule.target_column  if hasattr(rule, "target_column")  else rule.get("target_column", "")
            operator       = rule.operator       if hasattr(rule, "operator")       else rule.get("operator", "")
            value          = rule.value          if hasattr(rule, "value")          else rule.get("value", "")

            sample_records = by_rule.get(rule_id, [])[:_SAMPLE_RECORDS]

            human_msg = _build_prompt(
                rule_text=rule_text,
                target_column=target_column,
                operator=str(operator),
                value=str(value),
                violation_count=count,
                sample_records=sample_records,
            )

            log.info(
                f"explanation_generator: generating explanation for rule '{rule_id}' "
                f"({count} violations)"
            )
            llm_result = _call_llm(llm, human_msg)

            if not llm_result:
                # Fallback: generate a minimal template explanation
                auto_severity = _infer_severity(count)
                llm_result = {
                    "explanation": (
                        f"{count} records in column '{target_column}' violate the rule: {rule_text}"
                    ),
                    "policy_clause": rule_text[:120],
                    "remediation_steps": [
                        f"Review all {count} flagged records in column '{target_column}'.",
                        "Update or delete records that do not meet the policy requirement.",
                        "Implement data validation to prevent future violations.",
                    ],
                    "severity": auto_severity,
                    "risk_description": (
                        f"Unresolved violations in '{target_column}' may indicate "
                        f"non-compliance with policy: {rule_text[:80]}."
                    ),
                }

            # Normalise severity (LLM might return lowercase)
            severity = str(llm_result.get("severity", "MEDIUM")).upper()
            if severity not in ("HIGH", "MEDIUM", "LOW"):
                severity = _infer_severity(count)

            explanation       = str(llm_result.get("explanation", ""))
            policy_clause     = str(llm_result.get("policy_clause", ""))
            remediation_steps = llm_result.get("remediation_steps", [])
            if isinstance(remediation_steps, str):
                remediation_steps = [remediation_steps]
            risk_description  = str(llm_result.get("risk_description", ""))

            # Persist to DB
            store_rule_explanation(
                session=session,
                scan_id=scan_id,
                rule_id=rule_id,
                violation_count=count,
                severity=severity,
                explanation=explanation,
                policy_clause=policy_clause,
                remediation_steps=remediation_steps,
                risk_description=risk_description,
            )

            rule_explanations[rule_id] = {
                "rule_text":         rule_text,
                "violation_count":   count,
                "severity":          severity,
                "explanation":       explanation,
                "policy_clause":     policy_clause,
                "remediation_steps": remediation_steps,
                "risk_description":  risk_description,
            }

    log.info(
        f"explanation_generator_node: generated explanations for "
        f"{len(rule_explanations)} rules"
    )
    return {
        "rule_explanations": rule_explanations,
        "current_stage": "explanations_complete",
    }
