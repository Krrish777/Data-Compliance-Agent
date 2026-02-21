"""
Violation reporting node for the LangGraph compliance pipeline.

Reads the violations_log table (written by the data_scanning node) and
produces a structured report keyed by rule, table, and confidence band.
No LLM involved — pure SQL aggregation + Python formatting.
"""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sqlmodel import Session, create_engine

from src.agents.tools.database.violations_store import (
    get_low_confidence_violations,
    get_rule_explanations,
    get_scan_summary,
    get_violations_by_scan,
)
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# Violations with confidence below this go into the "needs_review" bucket.
REVIEW_THRESHOLD = 0.7


def violation_reporting_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: read violations_log and produce violation_report.

    Reads from state
    ----------------
    - scan_id            : unique scan identifier
    - violations_db_path : path to the SQLite violations log DB
    - scan_summary       : dict already in state (used to enrich report)

    Writes to state
    ---------------
    - violation_report : structured report dict (see schema below)
    - current_stage    : 'reporting_complete' | 'reporting_failed'
    - errors           : appends on failure

    Report schema
    -------------
    {
      "scan_id": str,
      "generated_at": ISO-8601 str,
      "summary": {
          total, tables_with_violations, rules_violated, avg_confidence,
          compliance_score, compliance_grade,
          total_rules_checked, rules_passing, rules_failing
      },
      "by_rule": {
          rule_id: {
              rule_text, count, violations: [...],
              severity, explanation, policy_clause,
              remediation_steps, risk_description
          }
      },
      "by_table": {table_name: {count, violations: [...]}},
      "needs_review": [...],       # confidence < 0.7
      "high_confidence": [...],    # confidence >= 0.7
    }
    """
    scan_id = state.get("scan_id", "")
    violations_db_path = state.get("violations_db_path", "violations.db")
    structured_rules = state.get("structured_rules", [])
    rule_explanations_state: Dict[str, Any] = state.get("rule_explanations", {})

    if not scan_id:
        log.warning("violation_reporting_node: no scan_id in state — skipping report")
        return {
            "violation_report": {"error": "no scan_id", "total_violations": 0},
            "current_stage": "reporting_skipped",
        }

    db_path = Path(violations_db_path)
    if not db_path.exists():
        log.warning(f"violation_reporting_node: violations DB not found at {db_path}")
        return {
            "violation_report": {"error": f"violations DB not found: {db_path}", "total_violations": 0},
            "current_stage": "reporting_failed",
            "errors": [f"violation_reporting: DB not found at {db_path}"],
        }

    log.info(f"violation_reporting_node: generating report for scan_id='{scan_id}'")

    try:
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        with Session(engine) as session:
            summary = get_scan_summary(session, scan_id)
            all_violations = get_violations_by_scan(session, scan_id)
            needs_review = get_low_confidence_violations(session, scan_id, REVIEW_THRESHOLD)
            db_explanations: list = get_rule_explanations(session, scan_id)

        # -- Group by rule --------------------------------------------------------
        by_rule: Dict[str, Any] = defaultdict(lambda: {"rule_text": "", "count": 0, "violations": []})
        for v in all_violations:
            rid = v.get("rule_id", "unknown")
            by_rule[rid]["rule_text"] = v.get("rule_text", "")
            by_rule[rid]["count"] += 1
            by_rule[rid]["violations"].append(_slim(v))

        # -- Enrich by_rule with explanations ------------------------------------
        # Prefer DB explanations (stored by explanation_generator), fall back to
        # the in-state dict from the same node.
        expl_by_rule: Dict[str, Any] = {}
        for ex in db_explanations:
            rid = ex.get("rule_id", "")
            if rid:
                expl_by_rule[rid] = ex
        # Overlay state explanations for any rule not yet in DB results
        for rid, ex in rule_explanations_state.items():
            if rid not in expl_by_rule:
                expl_by_rule[rid] = ex

        for rid, entry in by_rule.items():
            ex = expl_by_rule.get(rid, {})
            entry["severity"]          = ex.get("severity", "")
            entry["explanation"]       = ex.get("explanation", "")
            entry["policy_clause"]     = ex.get("policy_clause", "")
            entry["remediation_steps"] = ex.get("remediation_steps", [])
            entry["risk_description"]  = ex.get("risk_description", "")

        # -- Group by table -------------------------------------------------------
        by_table: Dict[str, Any] = defaultdict(lambda: {"count": 0, "violations": []})
        for v in all_violations:
            tbl = v.get("table_name", "unknown")
            by_table[tbl]["count"] += 1
            by_table[tbl]["violations"].append(_slim(v))

        # -- Confidence split -----------------------------------------------------
        high_confidence = [_slim(v) for v in all_violations if float(v.get("confidence", 1.0)) >= REVIEW_THRESHOLD]
        needs_review_slim = [_slim(v) for v in needs_review]

        # -- Compliance score (6A) ------------------------------------------------
        # Determine the total number of rules that were actually checked.
        # Priority:
        #   1. len(structured_rules) — full list from state (includes passing)
        #   2. state["scan_summary"]["rules_processed"] — from data_scanning stage
        #   3. len(by_rule) — fallback (only rules WITH violations, least accurate)
        scan_summary_state = state.get("scan_summary", {}) or {}
        if structured_rules:
            total_rules_checked = len(structured_rules)
        elif scan_summary_state.get("rules_processed"):
            total_rules_checked = int(scan_summary_state["rules_processed"])
        else:
            total_rules_checked = len(by_rule)

        rules_failing  = len([rid for rid, entry in by_rule.items() if entry["count"] > 0])
        rules_passing  = max(0, total_rules_checked - rules_failing)
        if total_rules_checked > 0:
            compliance_score = round((rules_passing / total_rules_checked) * 100, 1)
        else:
            compliance_score = 0.0

        if compliance_score >= 90:
            compliance_grade = "A"
        elif compliance_score >= 75:
            compliance_grade = "B"
        elif compliance_score >= 60:
            compliance_grade = "C"
        elif compliance_score >= 45:
            compliance_grade = "D"
        else:
            compliance_grade = "F"

        # Inject score fields into summary
        summary["compliance_score"]    = compliance_score
        summary["compliance_grade"]    = compliance_grade
        summary["total_rules_checked"] = total_rules_checked
        summary["rules_passing"]       = rules_passing
        summary["rules_failing"]       = rules_failing

        report = {
            "scan_id": scan_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "by_rule": dict(by_rule),
            "by_table": dict(by_table),
            "high_confidence": high_confidence,
            "needs_review": needs_review_slim,
        }

        log.info(
            f"violation_reporting_node: report ready — "
            f"{summary['total_violations']} violations, "
            f"score={compliance_score}% grade={compliance_grade}, "
            f"{len(needs_review_slim)} need review"
        )

        return {
            "violation_report": report,
            "current_stage": "reporting_complete",
        }

    except Exception as e:
        log.error(f"violation_reporting_node failed: {e}")
        return {
            "violation_report": {"error": str(e), "total_violations": 0},
            "current_stage": "reporting_failed",
            "errors": [f"violation_reporting: {e}"],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slim(v: Dict[str, Any]) -> Dict[str, Any]:
    """Return a leaner violation dict — exclude heavy JSON blob from report lists."""
    return {
        "id": v.get("id"),
        "rule_id": v.get("rule_id"),
        "table_name": v.get("table_name"),
        "record_primary_key": v.get("record_primary_key"),
        "confidence": v.get("confidence"),
        "violation_type": v.get("violation_type"),
        "review_status": v.get("review_status"),
        "detected_at": v.get("detected_at"),
    }


def print_report(report: Dict[str, Any]) -> None:
    """
    Pretty-print a violation report to stdout.
    Call this from your agent's final step or a CLI entrypoint.
    """
    summary = report.get("summary", {})
    score   = summary.get("compliance_score", "?")
    grade   = summary.get("compliance_grade", "?")
    passing = summary.get("rules_passing", "?")
    failing = summary.get("rules_failing", "?")
    total_r = summary.get("total_rules_checked", "?")

    print("\n" + "=" * 60)
    print(f"  COMPLIANCE SCAN REPORT — {report.get('scan_id', 'unknown')}")
    print("=" * 60)
    print(f"  Generated: {report.get('generated_at', '')}")
    print(f"  Total violations : {summary.get('total_violations', 0)}")
    print(f"  Tables affected  : {summary.get('tables_with_violations', 0)}")
    print(f"  Rules triggered  : {summary.get('rules_violated', 0)}")
    print(f"  Avg confidence   : {summary.get('avg_confidence', 0.0):.2f}")
    print()
    print(f"  Compliance Score : {score}%  (Grade {grade})")
    print(f"  Rules passing    : {passing} / {total_r}")
    print(f"  Rules failing    : {failing} / {total_r}")
    print()

    by_rule = report.get("by_rule", {})
    if by_rule:
        print("  BY RULE")
        print("  " + "-" * 40)
        for rule_id, info in sorted(by_rule.items(), key=lambda x: -x[1]["count"]):
            sev = f"  [{info.get('severity', '')}]" if info.get("severity") else ""
            print(f"  [{info['count']:>4}]  {rule_id}{sev}  —  {info['rule_text'][:60]}")

    by_table = report.get("by_table", {})
    if by_table:
        print()
        print("  BY TABLE")
        print("  " + "-" * 40)
        for table, info in sorted(by_table.items(), key=lambda x: -x[1]["count"]):
            print(f"  [{info['count']:>4}]  {table}")

    needs_review = report.get("needs_review", [])
    if needs_review:
        print()
        print(f"  NEEDS HUMAN REVIEW ({len(needs_review)} violations, confidence < {REVIEW_THRESHOLD})")
        print("  " + "-" * 40)
        for v in needs_review[:10]:
            print(
                f"  rule={v['rule_id']}  table={v['table_name']}  "
                f"pk={v['record_primary_key']}  conf={v['confidence']:.2f}"
            )
        if len(needs_review) > 10:
            print(f"  ... and {len(needs_review) - 10} more")

    print("=" * 60 + "\n")
