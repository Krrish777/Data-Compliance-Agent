"""
Violation Validator Node — Stage 4B.

LLM-powered false-positive reducer.

For each rule with sampled low-confidence violations the node sends a
batch of records to the LLM and asks it to classify each as:
  - "confirmed"      — genuine policy violation
  - "false_positive" — benign record that was flagged incorrectly

The node then writes the verdicts back to violations_log.review_status
and emits a validation_summary into state.

Design constraints
------------------
- Validates ONLY violations with confidence < 0.85.
- Validates ONLY rule types: data_quality, data_security, data_privacy.
  Financial threshold and NULL rules are deterministic — no LLM needed.
- Max 20 records per LLM call; max 50 records sampled per rule.
- Uses llama-3.1-8b-instant (cheapest, fast enough for verdict classification).
- Full JSON response parsing with regex fallback; never crashes the pipeline.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_groq import ChatGroq
from sqlmodel import Session, create_engine

from src.agents.middleware.retry import retry_with_backoff
from src.agents.tools.database.violations_store import (
    get_violations_sample_for_validation,
    update_violation_status,
)
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALIDATE_RULE_TYPES = {"data_quality", "data_security", "data_privacy"}
_CONFIDENCE_CEILING  = 0.85       # skip rules whose violations are all high-confidence
_MAX_SAMPLE_PER_RULE = 50         # total records sampled per rule
_BATCH_SIZE          = 20         # records per LLM call
_MODEL               = "llama-3.1-8b-instant"

_SYSTEM_PROMPT = """You are a compliance auditor reviewing flagged database records.
For each record decide:
  "confirmed"      — the record genuinely violates the stated policy rule
  "false_positive" — the record was incorrectly flagged (benign or irrelevant)

Respond ONLY with a single JSON object in this exact format:
{
  "results": [
    {"violation_id": <int>, "verdict": "confirmed"|"false_positive", "reason": "<1 sentence>"}
  ]
}"""

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

@retry_with_backoff(max_retries=2, initial_delay=2.0, backoff_factor=2.0)
def _invoke_validator_llm(llm: ChatGroq, system_prompt: str, human_msg: str) -> Any:
    """Invoke the validator LLM with exponential backoff on 429/500/timeout."""
    return llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": human_msg},
    ])


def _call_llm(llm: ChatGroq, rule_text: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ask the LLM to validate *records* against *rule_text*.

    Returns list of {violation_id, verdict, reason} dicts (may be partial on parse failure).
    """
    records_text = json.dumps(
        [
            {
                "violation_id": r.get("id"),
                "column_value": _extract_column_value(r),
                "full_record_preview": _slim_record(r),
            }
            for r in records
        ],
        indent=2,
    )

    human_msg = (
        f"Policy Rule:\n{rule_text}\n\n"
        f"Flagged Records ({len(records)}):\n{records_text}\n\n"
        "Validate each record. Return JSON only."
    )

    try:
        response = _invoke_validator_llm(llm, _SYSTEM_PROMPT, human_msg)
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        log.warning(f"violation_validator LLM call failed after retries: {exc}")
        return []

    return _parse_response(raw)


def _parse_response(raw: str) -> List[Dict[str, Any]]:
    """Extract results array from LLM response, robust to markdown fences."""
    # Strip fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    # Find the JSON object
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not m:
        log.warning("violation_validator: no JSON object found in LLM response")
        return []
    try:
        data = json.loads(m.group(0))
        return data.get("results", [])
    except json.JSONDecodeError as exc:
        log.warning(f"violation_validator: JSON parse error: {exc}")
        return []


def _extract_column_value(record: Dict[str, Any]) -> Any:
    """Pull the actual cell value from the violating_data JSON stored in the DB."""
    raw = record.get("violating_data") or record.get("violating_record") or "{}"
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    elif isinstance(raw, dict):
        data = raw
    else:
        return str(raw)
    # Return first non-pk column value as a hint
    for k, v in data.items():
        if k.lower() not in ("rowid", "id"):
            return v
    return None


def _slim_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a concise view of the violation for the LLM prompt."""
    raw = record.get("violating_data") or "{}"
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    else:
        data = raw or {}
    # Keep only first 5 columns to stay within token budget
    items = list(data.items())[:5]
    return dict(items)


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def violation_validator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: validate sampled violations with an LLM to reduce false positives.

    Reads from state
    ----------------
    - scan_id
    - violations_db_path
    - structured_rules
    - scan_summary

    Writes to state
    ---------------
    - validation_summary : {total_validated, confirmed, false_positives, skipped, by_rule}
    - current_stage      : 'validation_complete' | 'validation_skipped'
    """
    scan_id = state.get("scan_id", "")
    violations_db_path = state.get("violations_db_path", "violations.db")
    structured_rules = state.get("structured_rules", [])

    if not scan_id:
        log.warning("violation_validator_node: no scan_id — skipping")
        return {
            "validation_summary": {"skipped": True, "reason": "no scan_id"},
            "current_stage": "validation_skipped",
        }

    db_path = Path(violations_db_path)
    if not db_path.exists():
        log.warning(f"violation_validator_node: violations DB not found at {db_path}")
        return {
            "validation_summary": {"skipped": True, "reason": "no violations DB"},
            "current_stage": "validation_skipped",
        }

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        log.warning("violation_validator_node: GROQ_API_KEY not set — skipping validation")
        return {
            "validation_summary": {"skipped": True, "reason": "no GROQ_API_KEY"},
            "current_stage": "validation_skipped",
        }

    # Build a quick lookup: rule_id → {rule_type, rule_text}
    rule_lookup: Dict[str, Any] = {}
    for rule in structured_rules:
        rid = rule.rule_id if hasattr(rule, "rule_id") else rule.get("rule_id", "")
        rtype = rule.rule_type if hasattr(rule, "rule_type") else rule.get("rule_type", "")
        rtext = rule.rule_text if hasattr(rule, "rule_text") else rule.get("rule_text", "")
        rule_lookup[rid] = {"rule_type": rtype, "rule_text": rtext}

    llm = ChatGroq(
        model=_MODEL,
        api_key=api_key,
        temperature=0,
        timeout=30,
        max_retries=0,
    )  # type: ignore

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    total_validated = 0
    total_confirmed  = 0
    total_fp         = 0
    total_skipped    = 0
    by_rule: Dict[str, Dict[str, int]] = {}

    with Session(engine) as session:
        for rule_id, info in rule_lookup.items():
            rule_type = info["rule_type"]
            rule_text = info["rule_text"]

            if rule_type not in _VALIDATE_RULE_TYPES:
                total_skipped += 1
                by_rule[rule_id] = {"skipped": 1}
                continue

            violations_batch = get_violations_sample_for_validation(
                session=session,
                scan_id=scan_id,
                rule_id=rule_id,
                confidence_ceiling=_CONFIDENCE_CEILING,
                limit=_MAX_SAMPLE_PER_RULE,
            )

            if not violations_batch:
                by_rule[rule_id] = {"validated": 0, "confirmed": 0, "false_positives": 0}
                continue

            confirmed_ids:  List[int] = []
            fp_ids:         List[int] = []

            # Process in sub-batches of _BATCH_SIZE
            for i in range(0, len(violations_batch), _BATCH_SIZE):
                chunk = violations_batch[i : i + _BATCH_SIZE]
                results = _call_llm(llm, rule_text, chunk)

                result_map = {r.get("violation_id"): r for r in results if "violation_id" in r}

                for record in chunk:
                    vid = record.get("id")
                    verdict_data = result_map.get(vid)
                    if verdict_data is None:
                        # LLM didn't return a verdict — leave as pending
                        continue
                    verdict = str(verdict_data.get("verdict", "")).lower()
                    reason  = str(verdict_data.get("reason", ""))

                    if verdict == "false_positive":
                        fp_ids.append(vid)
                    else:
                        confirmed_ids.append(vid)

            # Bulk update statuses
            if confirmed_ids:
                update_violation_status(session, confirmed_ids, "confirmed")
            if fp_ids:
                update_violation_status(
                    session, fp_ids, "false_positive",
                    reviewer_notes="LLM validator classified as false positive"
                )

            rule_count = len(violations_batch)
            total_validated += rule_count
            total_confirmed  += len(confirmed_ids)
            total_fp         += len(fp_ids)
            by_rule[rule_id] = {
                "validated":      rule_count,
                "confirmed":      len(confirmed_ids),
                "false_positives": len(fp_ids),
                "unresolved":     rule_count - len(confirmed_ids) - len(fp_ids),
            }
            log.info(
                f"violation_validator: rule '{rule_id}' — "
                f"{len(confirmed_ids)} confirmed, {len(fp_ids)} false_positives "
                f"out of {rule_count} sampled"
            )

    summary: Dict[str, Any] = {
        "total_validated":  total_validated,
        "confirmed":        total_confirmed,
        "false_positives":  total_fp,
        "rules_skipped":    total_skipped,
        "by_rule":          by_rule,
    }
    log.info(
        f"violation_validator_node: done — "
        f"{total_validated} validated, "
        f"{total_confirmed} confirmed, "
        f"{total_fp} false positives"
    )

    return {
        "validation_summary": summary,
        "current_stage": "validation_complete",
    }
