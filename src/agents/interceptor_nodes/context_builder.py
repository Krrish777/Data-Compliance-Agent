"""
Context Builder Node (Stage 0) — deterministic metadata assembly.

Connects to the target database, discovers schema for the queried tables,
fetches basic user context, and assembles a ContextBundle with a
deterministic hash.  No LLM calls.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.models.interceptor_models import (
    ColumnMetadata,
    ContextBundle,
    SchemaSnapshot,
    UserContext,
)
from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ── Simple SQL parser (no deps) ──────────────────────────────────────────────

_TABLE_PATTERN = re.compile(
    r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)|\bINTO\s+(\w+)|\bUPDATE\s+(\w+)",
    re.IGNORECASE,
)
_COLUMN_PATTERN = re.compile(
    r"\bSELECT\s+(.*?)\s+FROM", re.IGNORECASE | re.DOTALL
)

_SENSITIVE_KEYWORDS = {
    "email", "phone", "ssn", "social_security", "credit_card", "card_number",
    "password", "name", "first_name", "last_name", "address", "dob",
    "date_of_birth", "salary", "income", "account_number",
}


def _parse_tables(sql: str) -> List[str]:
    """Extract table names from SQL."""
    tables: List[str] = []
    for m in _TABLE_PATTERN.finditer(sql):
        tbl = next((g for g in m.groups() if g), None)
        if tbl and tbl.lower() not in ("select", "where", "set"):
            tables.append(tbl.lower())
    return list(dict.fromkeys(tables))  # unique, order-preserved


_AGG_PATTERN = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT)\s*\(", re.IGNORECASE
)
_QUOTED_COL = re.compile(r'"([^"]+)"')  # double-quoted identifiers


def _parse_columns(sql: str) -> List[str]:
    """Extract column names from SELECT clause.  Returns ['*'] for SELECT *."""
    m = _COLUMN_PATTERN.search(sql)
    if not m:
        return []
    select_clause = m.group(1).strip()
    if select_clause == "*":
        return ["*"]

    cols: List[str] = []
    for token in select_clause.split(","):
        token = token.strip()
        # Skip pure aggregate functions — they reference *, not specific cols
        if _AGG_PATTERN.match(token) and "*" in token:
            continue
        # Extract quoted identifiers like "Amount Received"
        quoted = _QUOTED_COL.findall(token)
        if quoted:
            cols.extend(q.lower() for q in quoted)
            continue
        # Unquoted column: take last word (handles aliases)
        part = token.split(".")[-1].split(" ")[-1]
        # Strip remaining aggregate wrappers
        part = re.sub(r"^\w+\(", "", part).rstrip(")")
        if part and part != "*":
            cols.append(part.lower())
    return cols


def _is_pii(col_name: str) -> bool:
    normalised = col_name.lower().replace(" ", "_")
    return normalised in _SENSITIVE_KEYWORDS or any(
        kw in normalised for kw in ("account", "name", "ssn", "email", "phone")
    )


def _normalise_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";").lower()
    return re.sub(r"\s+", " ", sql)


# ── Node ──────────────────────────────────────────────────────────────────────

def context_builder_node(state: InterceptorState) -> Dict[str, Any]:
    """
    Stage 0: Build ContextBundle from database schema + user identity.

    Pure data retrieval — no LLM, no cost.

    Reads from state:
        query, user_id, user_role, stated_purpose, db_config, db_type

    Writes to state:
        context_bundle  (serialised ContextBundle dict)
    """
    query: str = state.get("query", "")
    user_id: str = state.get("user_id", "unknown")
    user_role: str = state.get("user_role", "analyst")
    stated_purpose: Optional[str] = state.get("stated_purpose")
    db_type: str = state.get("db_type", "sqlite")
    db_config: Dict[str, Any] = state.get("db_config", {})

    normalised = _normalise_sql(query)
    tables = _parse_tables(query)
    columns = _parse_columns(query)

    # ── Discover schema for queried tables ──────────────────────────────
    schema_metadata: Dict[str, Dict[str, Any]] = {}
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
        schema_metadata = conn.discover_schema()
        conn.close()
    except Exception as e:
        log.warning(f"context_builder: schema discovery failed: {e}")

    # ── Build column metadata ───────────────────────────────────────────
    col_meta: List[ColumnMetadata] = []
    has_pii = False
    queried_tables = tables or list(schema_metadata.keys())

    for tbl in queried_tables:
        tbl_info = schema_metadata.get(tbl, {})
        tbl_columns = tbl_info.get("columns", [])
        for col_info in tbl_columns:
            cname = col_info.get("column_name", "")
            # If SELECT *, include all columns.
            # If specific columns parsed, include only those that match.
            # If NO parsed columns match anything, we'll fall back later.
            if columns != ["*"] and columns and cname.lower() not in columns:
                continue
            pii = _is_pii(cname)
            if pii:
                has_pii = True
            col_meta.append(ColumnMetadata(
                column_name=cname,
                table_name=tbl,
                data_type=col_info.get("data_type", "string"),
                is_pii=pii,
                pii_categories=_detect_pii_categories(cname),
                classification="confidential" if pii else "internal",
            ))

    # Fallback: if specific columns were requested but NONE matched the schema,
    # include ALL schema columns (conservative for compliance).
    if columns and columns != ["*"] and not col_meta:
        log.info("context_builder: no parsed columns matched schema — including all columns")
        for tbl in queried_tables:
            tbl_info = schema_metadata.get(tbl, {})
            for col_info in tbl_info.get("columns", []):
                cname = col_info.get("column_name", "")
                pii = _is_pii(cname)
                if pii:
                    has_pii = True
                col_meta.append(ColumnMetadata(
                    column_name=cname,
                    table_name=tbl,
                    data_type=col_info.get("data_type", "string"),
                    is_pii=pii,
                    pii_categories=_detect_pii_categories(cname),
                    classification="confidential" if pii else "internal",
                ))

    max_class = "restricted" if has_pii else "internal"
    schema_snap = SchemaSnapshot(
        queried_tables=queried_tables,
        queried_columns=col_meta,
        has_pii=has_pii,
        has_multi_jurisdiction=False,
        max_classification=max_class,
    )

    user_ctx = UserContext(
        user_id=user_id,
        role=user_role,
        department="unknown",
        jurisdiction="unknown",
        approved_purposes=[],
        data_access_level=_role_to_access_level(user_role),
    )

    bundle = ContextBundle(
        query=query,
        normalized_query=normalised,
        user_context=user_ctx,
        schema_snapshot=schema_snap,
        stated_purpose=stated_purpose,
    )
    bundle.compute_hash()

    log.info(
        f"context_builder_node: tables={queried_tables}, "
        f"cols={len(col_meta)}, pii={has_pii}, hash={bundle.bundle_hash[:12]}…"
    )

    return {
        "context_bundle": bundle.model_dump(mode="json"),
        "current_stage": "context_built",
        "total_cost_usd": state.get("total_cost_usd", 0.0),  # no cost
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_pii_categories(col_name: str) -> List[str]:
    """Basic keyword-based PII categorisation."""
    cn = col_name.lower()
    cats: List[str] = []
    if any(k in cn for k in ("email", "mail")):
        cats.append("email")
    if any(k in cn for k in ("phone", "mobile", "cell")):
        cats.append("phone")
    if "ssn" in cn or "social_security" in cn:
        cats.append("ssn")
    if any(k in cn for k in ("credit_card", "card_number", "card_num")):
        cats.append("credit_card")
    if any(k in cn for k in ("name", "first_name", "last_name")):
        cats.append("name")
    if any(k in cn for k in ("address", "street", "city", "zip")):
        cats.append("address")
    if any(k in cn for k in ("password", "secret", "token")):
        cats.append("password")
    if any(k in cn for k in ("salary", "income", "balance", "amount")):
        cats.append("financial")
    return cats


def _role_to_access_level(role: str) -> int:
    """Map common roles to data access levels 1-5."""
    role_map = {
        "admin": 5,
        "compliance_officer": 5,
        "data_engineer": 4,
        "analyst": 3,
        "developer": 3,
        "marketing": 2,
        "support": 2,
        "viewer": 1,
        "intern": 1,
    }
    return role_map.get(role.lower(), 2)
