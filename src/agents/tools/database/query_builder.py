"""
Keyset pagination query builder for compliance scanning.

Generates efficient cursor-based queries instead of OFFSET-based pagination.
"""
from typing import Any, Dict, Optional, Tuple

from src.models.structured_rule import StructuredRule
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def build_keyset_query(
    rule: StructuredRule,
    table_name: str,
    pk_column: str,
    last_pk_value: Optional[str] = None,
    batch_size: int = 1000,
    db_type: str = "sqlite",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Build a keyset pagination query for a compliance rule.

    Returns:
        Tuple of (SQL query string or None, parameter dict).
        Returns (None, {}) when the rule condition cannot be built
        (unsupported operator) so callers can skip the scan safely.
    """
    rule_condition = _build_rule_condition(rule, db_type)

    # Unsupported operator — return None so the caller skips this rule/table.
    if rule_condition is None:
        return (None, {})

    if last_pk_value is None:
        pagination_condition = f'"{pk_column}" IS NOT NULL'
        params: Dict[str, Any] = {}
    else:
        pagination_condition = f'"{pk_column}" IS NOT NULL AND "{pk_column}" > :last_pk'
        params = {"last_pk": last_pk_value}

    if rule_condition:
        where_clause = f"WHERE {rule_condition} AND {pagination_condition}"
    else:
        where_clause = f"WHERE {pagination_condition}"

    # SQLite's implicit rowid is NOT included in SELECT * — select it explicitly
    select_cols = f'"{pk_column}", *' if pk_column.lower() == "rowid" else "*"

    query = f'''
        SELECT {select_cols} FROM "{table_name}"
        {where_clause}
        ORDER BY "{pk_column}" ASC
        LIMIT {batch_size}
    '''
    log.debug(f"Built keyset query for rule '{rule.rule_id}' on table '{table_name}'")
    return (query.strip(), params)


def _build_rule_condition(rule: StructuredRule, db_type: str) -> Optional[str]:
    """Convert StructuredRule to SQL WHERE condition fragment."""
    column = rule.target_column
    operator = rule.operator.upper().strip()
    value = rule.value
    data_type = (rule.data_type or "string").lower()

    if operator == "IS NULL":
        return f'"{column}" IS NULL'
    if operator == "IS NOT NULL":
        return f'"{column}" IS NOT NULL'

    if operator in ("LIKE", "NOT LIKE"):
        if value is None:
            return None
        escaped = str(value).replace("'", "''")
        return f'"{column}" {operator} \'{escaped}\''

    if operator in ("~", "!~"):
        if db_type != "postgresql":
            log.warning(f"Regex operator '{operator}' not supported in {db_type}")
            return None
        if value is None:
            return None
        escaped = str(value).replace("'", "''")
        return f'"{column}" {operator} \'{escaped}\''

    if operator in ("IN", "NOT IN"):
        if value is None:
            return None
        # Value may be a comma-separated string: "Bitcoin, Cash, Wire"
        raw = str(value)
        # Strip surrounding brackets if present
        raw = raw.strip("[]").strip()
        items = [v.strip().strip("'\"[]") for v in raw.split(",") if v.strip()]
        if not items:
            return None
        placeholders = ", ".join(f"'{item.replace(chr(39), chr(39)+chr(39))}'" for item in items)
        return f'"{column}" {operator} ({placeholders})'

    if operator in ("=", "!=", ">", "<", ">=", "<="):
        if value is None:
            return None
        value_str = str(value).strip()
        if data_type == "datetime" and (
            "NOW()" in value_str.upper()
            or "INTERVAL" in value_str.upper()
            or "datetime(" in value_str.lower()
        ):
            return f'"{column}" {operator} {value_str}'
        if data_type == "number":
            try:
                float(value_str)
                # SQLite stores amounts as TEXT; use CAST for correct numeric comparison
                if db_type == "sqlite":
                    return f'CAST("{column}" AS REAL) {operator} {value_str}'
                return f'"{column}" {operator} {value_str}'
            except ValueError:
                pass
        escaped = value_str.replace("'", "''")
        return f'"{column}" {operator} \'{escaped}\''

    log.warning(f"Unsupported operator '{operator}' for rule '{rule.rule_id}'")
    return None


def extract_last_pk(results: list, pk_column: str) -> Optional[str]:
    """Extract primary key value from the last row of results."""
    if not results:
        return None
    last_row = results[-1]
    if isinstance(last_row, dict):
        pk_value = last_row.get(pk_column)
    else:
        pk_value = getattr(last_row, pk_column, None)
    if pk_value is None:
        log.warning(f"Last row has NULL primary key in column '{pk_column}'")
        return None
    return str(pk_value)
