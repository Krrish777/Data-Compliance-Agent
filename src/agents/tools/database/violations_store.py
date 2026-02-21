"""
Violations log storage for compliance scanning.

Stores discovered violations in a dedicated table instead of LangGraph state,
keeping state small and enabling efficient querying for reporting.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlmodel import Session, text

from src.utils.logger import setup_logger

log = setup_logger(__name__)


def create_violations_table(session: Session, db_type: str) -> None:
    """
    Create the violations_log table if it does not exist.

    Args:
        session: Active database session
        db_type: Either 'sqlite' or 'postgresql'
    """
    if db_type == "postgresql":
        create_sql = text("""
            CREATE TABLE IF NOT EXISTS violations_log (
                id SERIAL PRIMARY KEY,
                scan_id TEXT NOT NULL,
                scan_timestamp TIMESTAMP NOT NULL,
                rule_id TEXT NOT NULL,
                rule_text TEXT,
                rule_source TEXT,
                table_name TEXT NOT NULL,
                record_primary_key TEXT NOT NULL,
                violating_data JSONB,
                confidence REAL NOT NULL,
                violation_type TEXT,
                detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                review_status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                reviewer_notes TEXT
            )
        """)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_violations_scan_id ON violations_log(scan_id)",
            "CREATE INDEX IF NOT EXISTS idx_violations_rule_id ON violations_log(rule_id)",
            "CREATE INDEX IF NOT EXISTS idx_violations_table ON violations_log(table_name)",
            "CREATE INDEX IF NOT EXISTS idx_violations_confidence ON violations_log(confidence)",
            "CREATE INDEX IF NOT EXISTS idx_violations_status ON violations_log(review_status)",
            "CREATE INDEX IF NOT EXISTS idx_violations_detected_at ON violations_log(detected_at)",
        ]
    elif db_type == "sqlite":
        create_sql = text("""
            CREATE TABLE IF NOT EXISTS violations_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                scan_timestamp TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_text TEXT,
                rule_source TEXT,
                table_name TEXT NOT NULL,
                record_primary_key TEXT NOT NULL,
                violating_data TEXT,
                confidence REAL NOT NULL,
                violation_type TEXT,
                detected_at TEXT NOT NULL DEFAULT (datetime('now')),
                review_status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT,
                reviewer_notes TEXT
            )
        """)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_violations_scan_id ON violations_log(scan_id)",
            "CREATE INDEX IF NOT EXISTS idx_violations_rule_id ON violations_log(rule_id)",
            "CREATE INDEX IF NOT EXISTS idx_violations_table ON violations_log(table_name)",
            "CREATE INDEX IF NOT EXISTS idx_violations_confidence ON violations_log(confidence)",
            "CREATE INDEX IF NOT EXISTS idx_violations_status ON violations_log(review_status)",
            "CREATE INDEX IF NOT EXISTS idx_violations_detected_at ON violations_log(detected_at)",
        ]
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    session.exec(create_sql) # type: ignore
    log.info(f"Created violations_log table for {db_type}")

    for index_sql in indexes:
        try:
            session.exec(text(index_sql)) # type: ignore
        except Exception as e:
            log.debug(f"Index may already exist: {e}")

    session.commit()
    log.info(f"Created {len(indexes)} indexes on violations_log")


def log_violation(
    session: Session,
    scan_id: str,
    rule_id: str,
    rule_text: str,
    rule_source: str,
    table_name: str,
    record_pk: str,
    violating_record: Dict[str, Any],
    confidence: float,
    violation_type: str,
    db_type: str,
) -> int:
    """
    Insert a violation record into the violations_log table.

    Returns:
        The ID of the inserted violation record
    """
    record_json = json.dumps(violating_record, default=str)
    scan_ts = datetime.now(timezone.utc)
    detected_ts = datetime.now(timezone.utc)

    insert_sql = text("""
        INSERT INTO violations_log (
            scan_id, scan_timestamp, rule_id, rule_text, rule_source,
            table_name, record_primary_key, violating_data,
            confidence, violation_type, detected_at
        ) VALUES (
            :scan_id, :scan_timestamp, :rule_id, :rule_text, :rule_source,
            :table_name, :record_pk, :violating_data,
            :confidence, :violation_type, :detected_at
        )
    """)

    params = {
        "scan_id": scan_id,
        "scan_timestamp": scan_ts,
        "rule_id": rule_id,
        "rule_text": rule_text,
        "rule_source": rule_source,
        "table_name": table_name,
        "record_pk": str(record_pk),
        "violating_data": record_json,
        "confidence": confidence,
        "violation_type": violation_type,
        "detected_at": detected_ts,
    }

    session.exec(insert_sql, params=params) # type: ignore
    session.commit()

    if db_type == "postgresql":
        result = session.exec(text("SELECT lastval()")).fetchone() # type: ignore
        violation_id = result[0] if result else 0
    else:
        result = session.exec(text("SELECT last_insert_rowid()")).fetchone() # type: ignore
        violation_id = result[0] if result else 0

    log.debug(f"Logged violation {violation_id} for rule '{rule_id}' in table '{table_name}'")
    return violation_id


def update_violation_status(
    session: Session,
    violation_ids: List[int],
    status: str,          # 'confirmed' | 'false_positive' | 'pending'
    reviewer_notes: str = "",
) -> int:
    """
    Bulk-update review_status for a list of violation IDs.

    Returns:
        Number of rows updated.
    """
    if not violation_ids:
        return 0
    reviewed_ts = datetime.now(timezone.utc)
    ids_csv = ",".join(str(i) for i in violation_ids)
    sql = text(f"""
        UPDATE violations_log
           SET review_status = :status,
               reviewer_notes = :notes,
               reviewed_at = :reviewed_at
         WHERE id IN ({ids_csv})
    """)
    session.exec(sql, params={  # type: ignore
        "status": status,
        "notes": reviewer_notes,
        "reviewed_at": reviewed_ts,
    })
    session.commit()
    log.debug(f"update_violation_status: {len(violation_ids)} rows → '{status}'")
    return len(violation_ids)


def create_explanations_table(session: Session) -> None:
    """Create rule_explanations table for Stage 5 LLM-generated explanations."""
    sql = text("""
        CREATE TABLE IF NOT EXISTS rule_explanations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            violation_count INTEGER DEFAULT 0,
            severity TEXT DEFAULT 'MEDIUM',
            explanation TEXT,
            policy_clause TEXT,
            remediation_steps TEXT,
            risk_description TEXT,
            generated_at TEXT NOT NULL,
            UNIQUE(scan_id, rule_id)
        )
    """)
    session.exec(sql)  # type: ignore
    session.commit()
    log.info("Created rule_explanations table")


def store_rule_explanation(
    session: Session,
    scan_id: str,
    rule_id: str,
    violation_count: int,
    severity: str,
    explanation: str,
    policy_clause: str,
    remediation_steps: List[str],
    risk_description: str,
) -> None:
    """Upsert an LLM-generated explanation for a rule into rule_explanations."""
    remediation_json = json.dumps(remediation_steps)
    now = datetime.now(timezone.utc).isoformat()
    sql = text("""
        INSERT INTO rule_explanations
            (scan_id, rule_id, violation_count, severity, explanation,
             policy_clause, remediation_steps, risk_description, generated_at)
        VALUES
            (:scan_id, :rule_id, :violation_count, :severity, :explanation,
             :policy_clause, :remediation_steps, :risk_description, :generated_at)
        ON CONFLICT(scan_id, rule_id) DO UPDATE SET
            violation_count  = excluded.violation_count,
            severity         = excluded.severity,
            explanation      = excluded.explanation,
            policy_clause    = excluded.policy_clause,
            remediation_steps= excluded.remediation_steps,
            risk_description = excluded.risk_description,
            generated_at     = excluded.generated_at
    """)
    session.exec(sql, params={  # type: ignore
        "scan_id": scan_id,
        "rule_id": rule_id,
        "violation_count": violation_count,
        "severity": severity,
        "explanation": explanation,
        "policy_clause": policy_clause,
        "remediation_steps": remediation_json,
        "risk_description": risk_description,
        "generated_at": now,
    })
    session.commit()


def get_rule_explanations(session: Session, scan_id: str) -> List[Dict[str, Any]]:
    """Fetch all LLM-generated explanations for a scan."""
    sql = text("""
        SELECT * FROM rule_explanations
        WHERE scan_id = :scan_id
        ORDER BY severity DESC, violation_count DESC
    """)
    result = session.exec(sql, params={"scan_id": scan_id})  # type: ignore
    rows = result.fetchall()
    if not rows:
        return []
    keys = list(result.keys()) if hasattr(result, "keys") else [
        "id", "scan_id", "rule_id", "violation_count", "severity",
        "explanation", "policy_clause", "remediation_steps",
        "risk_description", "generated_at",
    ]
    return [dict(zip(keys, row)) for row in rows]


def get_violations_sample_for_validation(
    session: Session,
    scan_id: str,
    rule_id: str,
    confidence_ceiling: float = 0.85,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Return a sample of violations for a given rule that are candidates for
    LLM false-positive validation (lower-confidence, still pending review).
    """
    sql = text("""
        SELECT id, rule_id, rule_text, table_name,
               record_primary_key, violating_data, confidence
          FROM violations_log
         WHERE scan_id     = :scan_id
           AND rule_id     = :rule_id
           AND confidence  < :ceiling
           AND review_status = 'pending'
         ORDER BY confidence ASC
         LIMIT :limit
    """)
    result = session.exec(sql, params={  # type: ignore
        "scan_id": scan_id,
        "rule_id": rule_id,
        "ceiling": confidence_ceiling,
        "limit": limit,
    })
    return _rows_to_dicts(result)


def _rows_to_dicts(result) -> List[Dict[str, Any]]:
    """Convert SQLAlchemy Result rows to list of dicts."""
    rows = result.fetchall()
    if not rows:
        return []
    keys = list(result.keys()) if hasattr(result, "keys") else []
    if not keys and rows:
        keys = [f"column_{i}" for i in range(len(rows[0]))]
    return [dict(zip(keys, row)) for row in rows]


def get_violations_by_scan(session: Session, scan_id: str) -> List[Dict[str, Any]]:
    """Get all violations for a specific scan."""
    query = text("""
        SELECT * FROM violations_log
        WHERE scan_id = :scan_id
        ORDER BY confidence DESC, detected_at ASC
    """)
    result = session.exec(query, params={"scan_id": scan_id}) # type: ignore
    return _rows_to_dicts(result)


def get_violations_by_table(
    session: Session, scan_id: str, table_name: str
) -> List[Dict[str, Any]]:
    """Get all violations for a specific table in a scan."""
    query = text("""
        SELECT * FROM violations_log
        WHERE scan_id = :scan_id AND table_name = :table_name
        ORDER BY confidence DESC
    """)
    result = session.exec(query, params={"scan_id": scan_id, "table_name": table_name}) # type: ignore
    return _rows_to_dicts(result)


def get_low_confidence_violations(
    session: Session, scan_id: str, threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """Get violations that need human review."""
    query = text("""
        SELECT * FROM violations_log
        WHERE scan_id = :scan_id
        AND confidence < :threshold
        AND review_status = 'pending'
        ORDER BY confidence ASC
    """)
    result = session.exec(query, params={"scan_id": scan_id, "threshold": threshold}) # type: ignore
    return _rows_to_dicts(result)


def get_scan_summary(session: Session, scan_id: str) -> Dict[str, Any]:
    """Get summary statistics for a scan."""
    query = text("""
        SELECT
            COUNT(*) as total_violations,
            COUNT(DISTINCT table_name) as tables_with_violations,
            COUNT(DISTINCT rule_id) as rules_violated,
            AVG(confidence) as avg_confidence,
            MIN(detected_at) as scan_start,
            MAX(detected_at) as scan_end
        FROM violations_log
        WHERE scan_id = :scan_id
    """)
    result = session.exec(query, params={"scan_id": scan_id}).fetchone() # type: ignore

    if not result:
        return {
            "total_violations": 0,
            "tables_with_violations": 0,
            "rules_violated": 0,
            "avg_confidence": 0.0,
            "scan_start": None,
            "scan_end": None,
        }

    return {
        "total_violations": result[0] or 0,
        "tables_with_violations": result[1] or 0,
        "rules_violated": result[2] or 0,
        "avg_confidence": float(result[3]) if result[3] is not None else 0.0,
        "scan_start": result[4],
        "scan_end": result[5],
    }
