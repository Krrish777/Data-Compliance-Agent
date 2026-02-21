"""
Executor Node — runs approved queries or returns block messages.

After the auditor passes the verdict, the executor:
- APPROVE → executes query on the target database, returns results
- BLOCK   → returns block message with reasoning and guidance

Also updates the decision cache and writes to the audit log.
"""
from __future__ import annotations

from typing import Any, Dict

from src.agents.interceptor_nodes.cache import get_decision_cache
from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)

MAX_RESULT_ROWS = 1000  # Safety cap on returned rows


def executor_node(state: InterceptorState) -> Dict[str, Any]:
    """
    Execute or block the query based on the verdict.

    Reads from state:
        verdict, context_bundle, query, db_config, db_type

    Writes to state:
        final_decision, block_reason, guidance, query_results
    """
    verdict = state.get("verdict") or {}
    decision = verdict.get("decision", "BLOCK")
    context = state.get("context_bundle") or {}
    query = state.get("query", "")
    db_type = state.get("db_type", "sqlite")
    db_config = state.get("db_config") or {}
    cost = state.get("total_cost_usd", 0.0) or 0.0

    if decision == "APPROVE":
        result = _handle_approve(dict(state), verdict, query, db_type, db_config, context, cost)
    else:
        result = _handle_block(dict(state), verdict, context, cost)

    # Log to immutable audit log
    _log_audit({**dict(state), **result})
    return result


def _handle_approve(
    state: Dict[str, Any],
    verdict: Dict[str, Any],
    query: str,
    db_type: str,
    db_config: Dict[str, Any],
    context: Dict[str, Any],
    cost: float,
) -> Dict[str, Any]:
    """Execute the approved query and return results."""
    results = None
    try:
        if db_type == "sqlite":
            from src.agents.tools.database.sqlite_connector import SQLiteConnector
            db_path = db_config.get("db_path", "")
            conn = SQLiteConnector(db_path)
        else:
            from src.agents.tools.database.postgres_connector import PostgresConnector
            conn = PostgresConnector(
                host=db_config.get('host', 'localhost'),
                port=int(db_config.get('port', 5432)),
                database=db_config.get('database', ''),
                user=db_config.get('user', ''),
                password=db_config.get('password', ''),
            )

        conn.connect()
        from sqlmodel import text
        result_proxy = conn.session.execute(text(query))  # type: ignore
        rows = result_proxy.fetchmany(MAX_RESULT_ROWS)
        columns = list(result_proxy.keys()) if hasattr(result_proxy, "keys") else []
        results = {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": len(rows) == MAX_RESULT_ROWS,
        }
        conn.close()
        log.info(f"executor: APPROVE — returned {len(rows)} rows")
    except Exception as e:
        log.error(f"executor: query execution failed: {e}")
        results = {"error": str(e), "rows": [], "row_count": 0}

    # Update cache
    _update_cache(state, verdict)

    controls = verdict.get("required_controls", [])
    guidance = None
    if controls:
        guidance = "Applied controls: " + ", ".join(controls)

    return {
        "final_decision": "APPROVE",
        "block_reason": None,
        "guidance": guidance,
        "query_results": results,
        "current_stage": "executed",
        "total_cost_usd": cost,
    }


def _handle_block(
    state: Dict[str, Any],
    verdict: Dict[str, Any],
    context: Dict[str, Any],
    cost: float,
) -> Dict[str, Any]:
    """Return block message with reasoning and remediation guidance."""
    reasoning = verdict.get("reasoning", "Query blocked by compliance policy.")
    sensitive = verdict.get("sensitive_columns", [])
    controls = verdict.get("required_controls", [])

    guidance_lines = ["To gain access, consider the following:"]
    if "mask_pii" in controls:
        guidance_lines.append("- Request only anonymised/masked columns")
    if "log_access" in controls:
        guidance_lines.append("- Ensure audit logging is enabled for your session")
    if sensitive:
        guidance_lines.append(
            f"- Avoid requesting sensitive columns: {', '.join(sensitive)}"
        )
    guidance_lines.append("- Provide a specific business justification")
    guidance_lines.append("- Contact the compliance team for access elevation")

    # Update cache
    _update_cache(state, verdict)

    log.info(f"executor: BLOCK — {reasoning[:80]}…")

    return {
        "final_decision": "BLOCK",
        "block_reason": reasoning,
        "guidance": "\n".join(guidance_lines),
        "query_results": None,
        "current_stage": "blocked",
        "total_cost_usd": cost,
    }


def _log_audit(state: Dict[str, Any]) -> None:
    """Write an immutable audit log entry."""
    try:
        from src.agents.interceptor_nodes.audit_logger import get_audit_logger
        logger = get_audit_logger()
        logger.log_decision(state)
    except Exception as e:
        log.warning(f"executor: audit log write failed: {e}")


def _update_cache(state: Dict[str, Any], verdict: Dict[str, Any]) -> None:
    """Store the decision in the 3-layer cache."""
    try:
        cache = get_decision_cache()
        query = state.get("query", "")
        user_role = state.get("user_role", "analyst")

        decision_payload = {
            "final_decision": verdict.get("decision", "BLOCK"),
            "reasoning": verdict.get("reasoning", ""),
            "cited_policies": verdict.get("cited_policies", []),
            "sensitive_columns": verdict.get("sensitive_columns", []),
            "required_controls": verdict.get("required_controls", []),
            "block_reason": verdict.get("reasoning", ""),
        }

        # Try to get embedding for semantic cache layer
        query_embedding = None
        try:
            from fastembed import TextEmbedding
            import numpy as np
            encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
            query_embedding = np.array(
                list(encoder.embed([query]))[0], dtype=np.float32
            )
        except Exception:
            pass

        cache.store(query, user_role, decision_payload, query_embedding)
    except Exception as e:
        log.warning(f"executor: cache update failed: {e}")
