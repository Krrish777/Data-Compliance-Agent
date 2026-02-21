"""
Immutable Audit Logger for the Interceptor.

Writes every interceptor decision to an append-only SQLite database.
Supports querying for compliance reporting and debugging.

Design:
  - WORM (Write Once, Read Many) — no UPDATE or DELETE operations
  - Full context reconstruction for replay/debugging
  - Cost and latency tracking per decision
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger

log = setup_logger(__name__)

DEFAULT_AUDIT_DB = "data/interceptor_audit.db"


class AuditLogger:
    """Append-only audit log backed by SQLite."""

    def __init__(self, db_path: str = DEFAULT_AUDIT_DB):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id          TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                created_at      TEXT NOT NULL,

                -- Input
                query           TEXT NOT NULL,
                user_id         TEXT,
                user_role       TEXT,
                stated_purpose  TEXT,

                -- Decision
                decision        TEXT NOT NULL,
                reasoning       TEXT,
                cited_policies  TEXT,
                sensitive_cols  TEXT,
                required_ctrls  TEXT,

                -- Cache info
                cache_hit       INTEGER DEFAULT 0,
                cache_layer     TEXT,

                -- Cost & performance
                total_cost_usd  REAL DEFAULT 0.0,
                processing_ms   REAL DEFAULT 0.0,

                -- Full stage outputs (JSON blob for replay)
                stage_outputs   TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_session
            ON audit_log(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_user
            ON audit_log(user_id, created_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_decision
            ON audit_log(decision, created_at)
        """)
        conn.commit()
        log.info(f"AuditLogger: schema ready at {self.db_path}")

    # ── Write ─────────────────────────────────────────────────────────────

    def log_decision(self, state: Dict[str, Any]) -> str:
        """
        Write an immutable audit record from the final interceptor state.

        Returns the generated log_id.
        """
        log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        context = state.get("context_bundle", {})
        verdict = state.get("verdict", {})
        session_id = state.get("session_id", "")
        start_time = state.get("processing_start_time", now)

        # Calculate processing time
        processing_ms = 0.0
        try:
            t0 = datetime.fromisoformat(start_time)
            t1 = datetime.now(timezone.utc)
            processing_ms = (t1 - t0).total_seconds() * 1000
        except Exception:
            pass

        # Collect all stage outputs for replay
        stage_outputs = {
            "context_bundle": context,
            "intent_result": state.get("intent_result"),
            "policy_mapping": state.get("policy_mapping"),
            "verdict": verdict,
            "audit_result": state.get("audit_result"),
        }

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO audit_log (
                log_id, session_id, created_at,
                query, user_id, user_role, stated_purpose,
                decision, reasoning, cited_policies, sensitive_cols, required_ctrls,
                cache_hit, cache_layer,
                total_cost_usd, processing_ms,
                stage_outputs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                session_id,
                now,
                state.get("query", ""),
                state.get("user_id", ""),
                state.get("user_role", ""),
                state.get("stated_purpose"),
                state.get("final_decision", verdict.get("decision", "BLOCK")),
                verdict.get("reasoning", state.get("block_reason", "")),
                json.dumps(verdict.get("cited_policies", [])),
                json.dumps(verdict.get("sensitive_columns", [])),
                json.dumps(verdict.get("required_controls", [])),
                1 if state.get("cache_hit") else 0,
                state.get("cache_layer"),
                state.get("total_cost_usd", 0.0),
                processing_ms,
                json.dumps(stage_outputs, default=str),
            ),
        )
        conn.commit()
        log.info(f"AuditLogger: logged decision {log_id} ({state.get('final_decision', '?')})")
        return log_id

    # ── Read ──────────────────────────────────────────────────────────────

    def get_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM audit_log WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_user(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate statistics for dashboard."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE decision = 'APPROVE'"
        ).fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE decision = 'BLOCK'"
        ).fetchone()[0]
        cache_hits = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE cache_hit = 1"
        ).fetchone()[0]
        avg_cost = conn.execute(
            "SELECT AVG(total_cost_usd) FROM audit_log WHERE cache_hit = 0"
        ).fetchone()[0] or 0.0
        avg_latency = conn.execute(
            "SELECT AVG(processing_ms) FROM audit_log WHERE cache_hit = 0"
        ).fetchone()[0] or 0.0

        return {
            "total_decisions": total,
            "approved": approved,
            "blocked": blocked,
            "escalated": total - approved - blocked,
            "cache_hit_rate": cache_hits / total if total else 0.0,
            "avg_cost_usd": round(avg_cost, 4),
            "avg_latency_ms": round(avg_latency, 1),
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Module-level singleton ───────────────────────────────────────────────────
_LOGGER: Optional[AuditLogger] = None


def get_audit_logger(db_path: str = DEFAULT_AUDIT_DB) -> AuditLogger:
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = AuditLogger(db_path)
    return _LOGGER
