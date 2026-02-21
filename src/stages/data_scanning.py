"""
Data scanning stage: scan database tables for compliance violations using keyset pagination.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.agents.tools.database.postgres_connector import PostgresConnector
from src.agents.tools.database.query_executor import execute_scan_query
from src.agents.tools.database.sqlite_connector import SQLiteConnector
from src.agents.tools.database.violations_store import (
    create_violations_table,
    log_violation,
)
from src.models.structured_rule import StructuredRule
from src.stages.rule_structuring import rule_from_dict
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def data_scanning_stage(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scan database tables for compliance violations.

    Input state requires:
    - structured_rules: List of StructuredRule or dict
    - schema_metadata: Dict of table schemas with primary_key
    - db_config: Connection config (db_path for SQLite, or host/port/database/user/password for Postgres)
    - db_type: 'sqlite' or 'postgresql'

    Output:
    - scan_id, scan_summary, current_stage
    """
    structured_rules = state.get("structured_rules", [])
    schema = state.get("schema_metadata", {})
    db_config = state.get("db_config", {})
    db_type = state.get("db_type", "sqlite")
    violations_db_path = state.get("violations_db_path", "violations.db")
    batch_size = state.get("batch_size", 1000)
    max_batches_per_table = state.get("max_batches_per_table")

    if not structured_rules:
        log.warning("No structured rules to scan")
        return {
            "scan_summary": {"total_violations": 0, "error": "No rules to scan"},
            "current_stage": "scanning_skipped",
        }

    if not schema:
        log.error("No schema metadata available for scanning")
        return {
            "scan_summary": {"total_violations": 0, "error": "No schema available"},
            "current_stage": "scanning_failed",
        }

    rules = [_ensure_structured_rule(r) for r in structured_rules]
    rules = [r for r in rules if r and r.target_column]

    if not rules:
        log.warning("No valid structured rules after conversion")
        return {
            "scan_summary": {"total_violations": 0, "error": "No valid rules"},
            "current_stage": "scanning_skipped",
        }

    scan_id = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    log.info(f"Starting scan {scan_id} with {len(rules)} rules across {len(schema)} tables")

    if db_type == "sqlite":
        target_conn = SQLiteConnector(db_config.get("db_path", ""))
    else:
        target_conn = PostgresConnector(
            host=db_config.get("host", "localhost"),
            port=int(db_config.get("port", 5432)),
            database=db_config.get("database", ""),
            user=db_config.get("user", ""),
            password=db_config.get("password", ""),
        )

    violations_conn = SQLiteConnector(str(Path(violations_db_path).absolute()))

    target_conn.connect()
    violations_conn.connect()

    if violations_conn.session is None:
        log.error("Failed to connect to violations database")
        raise RuntimeError("Failed to connect to violations database")
    create_violations_table(violations_conn.session, "sqlite")

    scan_summary: Dict[str, Any] = {
        "scan_id": scan_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_violations": 0,
        "tables_scanned": 0,
        "tables_skipped": 0,
        "rules_processed": 0,
        "rules_failed": 0,
        "violations_by_table": {},
        "violations_by_rule": {},
        "failed_rules": [],
    }

    try:
        for rule in rules:
            target_tables = find_target_tables(rule, schema)
            if not target_tables:
                log.warning(f"Rule '{rule.rule_id}' has no applicable tables")
                scan_summary["rules_failed"] += 1
                continue

            rule_violations = 0
            for table in target_tables:
                pk_column = schema[table].get("primary_key")
                if pk_column is None:
                    log.warning(f"Table '{table}' has no primary key, skipping")
                    scan_summary["tables_skipped"] += 1
                    continue
                if isinstance(pk_column, tuple):
                    log.warning(f"Table '{table}' has composite primary key, skipping")
                    scan_summary["tables_skipped"] += 1
                    continue

                count = scan_table_batched(
                    session=target_conn.session,
                    violations_session=violations_conn.session,
                    rule=rule,
                    table=table,
                    pk_column=pk_column,
                    scan_id=scan_id,
                    db_type=db_type,
                    batch_size=batch_size,
                    max_batches=max_batches_per_table,
                )
                rule_violations += count
                scan_summary["total_violations"] += count
                scan_summary["tables_scanned"] += 1
                scan_summary["violations_by_table"][table] = (
                    scan_summary["violations_by_table"].get(table, 0) + count
                )
                if count:
                    log.info(f"Found {count} violations in table '{table}' for rule '{rule.rule_id}'")

            scan_summary["violations_by_rule"][rule.rule_id] = rule_violations
            scan_summary["rules_processed"] += 1

        scan_summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        scan_summary["status"] = "completed"
        log.info(
            f"Scan {scan_id} complete: {scan_summary['total_violations']} violations "
            f"across {scan_summary['tables_scanned']} tables"
        )

    except Exception as e:
        log.error(f"Scan {scan_id} failed: {e}")
        scan_summary["status"] = "failed"
        scan_summary["error"] = str(e)
        raise
    finally:
        target_conn.close()
        violations_conn.close()

    return {
        "scan_id": scan_id,
        "scan_summary": scan_summary,
        "current_stage": "scanning_complete",
    }


def _ensure_structured_rule(r: Union[StructuredRule, Dict[str, Any]]) -> Optional[StructuredRule]:
    if isinstance(r, StructuredRule):
        return r
    if isinstance(r, dict):
        return rule_from_dict(r)
    return None


def find_target_tables(rule: StructuredRule, schema: Dict[str, Any]) -> List[str]:
    """Find tables that this rule should be applied to."""
    if rule.applies_to_tables:
        return [t for t in rule.applies_to_tables if t in schema]

    target_tables = []
    for table_name, table_info in schema.items():
        has_column = any(
            col.get("column_name") == rule.target_column
            for col in table_info.get("columns", [])
        )
        if not has_column:
            continue
        if rule.requires_pii:
            if "has_pii" not in table_info:
                log.debug(
                    f"Table '{table_name}' has no PII metadata; including for rule '{rule.rule_id}'"
                )
            elif not table_info["has_pii"]:
                continue
        target_tables.append(table_name)
    return target_tables


def scan_table_batched(
    session,
    violations_session,
    rule: StructuredRule,
    table: str,
    pk_column: str,
    scan_id: str,
    db_type: str,
    batch_size: int = 1000,
    max_batches: Optional[int] = None,
) -> int:
    """Scan a single table in batches using keyset pagination."""
    total_violations = 0
    last_pk: Optional[str] = None
    batch_num = 0

    while True:
        batch_num += 1
        if max_batches and batch_num > max_batches:
            log.warning(f"Reached max batches ({max_batches}) for table '{table}'")
            break

        results, new_last_pk, error_msg = execute_scan_query(
            session=session,
            rule=rule,
            table_name=table,
            pk_column=pk_column,
            last_pk_value=last_pk,
            batch_size=batch_size,
            db_type=db_type,
        )

        if error_msg:
            log.error(f"Skipping table '{table}' due to error: {error_msg}")
            break

        if not results:
            log.debug(f"Completed scanning table '{table}' after {batch_num} batches")
            break

        for row in results:
            row_dict = dict(row) if not isinstance(row, dict) else row
            log_violation(
                session=violations_session,
                scan_id=scan_id,
                rule_id=rule.rule_id,
                rule_text=rule.rule_text,
                rule_source=rule.source,
                table_name=table,
                record_pk=str(row_dict.get(pk_column, "")),
                violating_record=row_dict,
                confidence=rule.confidence,
                violation_type=rule.rule_type,
                db_type="sqlite",
            )
            total_violations += 1

        last_pk = new_last_pk

    return total_violations
