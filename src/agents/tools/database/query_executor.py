"""
Query execution with error handling for compliance scanning.
"""
from typing import Any, Dict, List, Optional

from sqlmodel import Session, text

from src.agents.tools.database.query_builder import build_keyset_query
from src.models.structured_rule import StructuredRule
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def execute_scan_query(
    session: Session,
    rule: StructuredRule,
    table_name: str,
    pk_column: str,
    last_pk_value: Optional[str],
    batch_size: int,
    db_type: str,
    query_timeout_seconds: int = 30,
) -> tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Execute a scan query with error handling.

    Returns:
        Tuple of (results, last_pk, error_message)
        - results: List of violating rows (empty on error)
        - last_pk: Primary key of last row (None if no results or error)
        - error_message: Error description (None if success)
    """
    try:
        query, params = build_keyset_query(
            rule=rule,
            table_name=table_name,
            pk_column=pk_column,
            last_pk_value=last_pk_value,
            batch_size=batch_size,
            db_type=db_type,
        )

        if db_type == "postgresql":
            try:
                session.exec(text(f"SET statement_timeout = {query_timeout_seconds * 1000}")) # type: ignore
            except Exception:
                pass

        result = session.exec(text(query), params=params) # type: ignore
        rows = result.fetchall()
        keys = list(result.keys()) if hasattr(result, "keys") else []
        results = [dict(zip(keys, row)) for row in rows] if rows else []

        last_pk = str(results[-1][pk_column]) if results else None
        log.debug(f"Query returned {len(results)} rows for rule '{rule.rule_id}' on table '{table_name}'")
        return (results, last_pk, None)

    except Exception as e:
        error_str = str(e).lower()
        if "column" in error_str and ("does not exist" in error_str or "no such column" in error_str):
            msg = f"Column '{rule.target_column}' does not exist in table '{table_name}'"
            log.error(f"Syntax error in rule '{rule.rule_id}': {msg}")
            return ([], None, msg)
        if "permission denied" in error_str or "access denied" in error_str:
            msg = f"Permission denied for table '{table_name}'"
            log.error(f"Permission error in rule '{rule.rule_id}': {msg}")
            return ([], None, msg)
        if "timeout" in error_str or "canceled" in error_str or "cancelled" in error_str:
            msg = f"Query timeout after {query_timeout_seconds}s on table '{table_name}'"
            log.error(f"Timeout error in rule '{rule.rule_id}': {msg}")
            return ([], None, msg)
        if "syntax" in error_str or "sqlite" in error_str:
            msg = f"SQL syntax error: {str(e)}"
            log.error(f"Syntax error in rule '{rule.rule_id}': {msg}")
            return ([], None, msg)
        msg = f"Unexpected error: {str(e)}"
        log.error(f"Unexpected error in rule '{rule.rule_id}' on table '{table_name}': {e}")
        return ([], None, msg)
