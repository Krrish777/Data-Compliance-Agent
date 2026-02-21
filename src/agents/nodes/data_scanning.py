"""
Data scanning node for the LangGraph compliance pipeline.

Thin wrapper around src/stages/data_scanning.py so the existing,
well-tested scanning logic plugs into the graph without modification.
"""
from typing import Any, Dict

from src.stages.data_scanning import data_scanning_stage
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# Default path for the violations log DB. Override via state["violations_db_path"].
DEFAULT_VIOLATIONS_DB = "violations.db"


def data_scanning_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: scan the target database for compliance violations.

    Reads from state
    ----------------
    - structured_rules      : List[StructuredRule] — produced by rule_structuring
    - schema_metadata       : Dict — produced by schema_discovery
    - db_config             : connection parameters
    - db_type               : 'sqlite' | 'postgresql'
    - violations_db_path    : (optional) path for violations log DB
    - batch_size            : (optional) rows per page, default 1000
    - max_batches_per_table : (optional) safety cap, default None

    Writes to state
    ---------------
    - scan_id       : unique ID for this scan run
    - scan_summary  : {total_violations, tables_scanned, rules_processed, ...}
    - current_stage : 'scanning_complete' | 'scanning_failed'
    - errors        : appends on failure
    """
    structured_rules = state.get("structured_rules", [])

    if not structured_rules:
        log.warning("data_scanning_node: no structured_rules in state — skipping scan")
        return {
            "scan_id": "",
            "scan_summary": {"total_violations": 0, "status": "skipped", "reason": "no structured rules"},
            "current_stage": "scanning_skipped",
        }

    # Build the sub-state expected by the underlying stage function.
    scan_state = {
        "structured_rules": structured_rules,
        "schema_metadata": state.get("schema_metadata", {}),
        "db_config": state.get("db_config", {}),
        "db_type": state.get("db_type", "sqlite"),
        "violations_db_path": state.get("violations_db_path", DEFAULT_VIOLATIONS_DB),
        "batch_size": state.get("batch_size", 1000),
        "max_batches_per_table": state.get("max_batches_per_table"),
    }

    log.info(
        f"data_scanning_node: starting scan with {len(structured_rules)} rules "
        f"on {len(scan_state['schema_metadata'])} tables"
    )

    try:
        result = data_scanning_stage(scan_state)
        return {
            "scan_id": result.get("scan_id", ""),
            "scan_summary": result.get("scan_summary", {}),
            "current_stage": result.get("current_stage", "scanning_complete"),
        }
    except Exception as e:
        log.error(f"data_scanning_node failed: {e}")
        return {
            "scan_id": "",
            "scan_summary": {"total_violations": 0, "status": "failed"},
            "current_stage": "scanning_failed",
            "errors": [f"data_scanning: {e}"],
        }
