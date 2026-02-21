"""
Report generation node for the LangGraph compliance pipeline.

Produces PDF and HTML audit reports from the violation_report and
rule_explanations produced by upstream nodes.  Delegates to
``src.stages.report_generator.generate_reports()``.
"""
from __future__ import annotations

from typing import Any, Dict

from src.stages.report_generator import generate_reports
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def report_generation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: generate PDF + HTML compliance audit reports.

    Reads from state
    ----------------
    - violation_report   : structured violation data
    - rule_explanations  : per-rule explanation text
    - scan_id            : unique scan identifier

    Writes to state
    ---------------
    - report_paths    : {"pdf": str, "html": str} — absolute paths
    - current_stage   : 'reports_generated' | 'report_generation_failed'
    """
    violation_report = state.get("violation_report", {})

    if not violation_report or violation_report.get("error"):
        log.warning("report_generation_node: no valid violation_report — skipping")
        return {
            "report_paths": {},
            "current_stage": "report_generation_skipped",
        }

    try:
        paths = generate_reports(state, output_dir="data")
        log.info(
            "report_generation_node: reports generated — "
            f"pdf={paths.get('pdf', 'N/A')}, html={paths.get('html', 'N/A')}"
        )
        return {
            "report_paths": paths,
            "current_stage": "reports_generated",
        }
    except Exception as exc:
        log.error(f"report_generation_node failed: {exc}", exc_info=True)
        errors = list(state.get("errors", []))
        errors.append(f"report_generation: {exc}")
        return {
            "report_paths": {},
            "current_stage": "report_generation_failed",
            "errors": errors,
        }
