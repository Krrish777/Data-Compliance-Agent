"""
Complex Rule Executor — Stage 4A.

Handles rules that cannot be expressed as a single SQL WHERE clause and
were classified with rule_complexity != "simple" by the rule_structuring_node.

Supported complexity types
--------------------------
between     : value="1000,10000"  → lo < cast(row[col]) < hi
regex       : value="^\\d{4}-…"  → re.search(pattern, str(row[col]))
cross_field : second_column set   → row[col] op row[second_column]
date_math   : value contains NOW()/ INTERVAL / timedelta keywords
              → datetime arithmetic evaluated in Python

For all types the executor:
  1. Fetches every row in the target table in keyset-batched pages.
  2. Evaluates the condition per row in Python.
  3. Calls log_violation() for each row that fails the check.

The row fetch query is intentionally simple:
  SELECT "rowid", * FROM "table" WHERE "pk" > :last_pk ORDER BY "pk" LIMIT n
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, text

from src.agents.tools.database.violations_store import log_violation
from src.models.structured_rule import StructuredRule
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Row fetching helpers
# ---------------------------------------------------------------------------

def _fetch_batch(
    session: Session,
    table_name: str,
    pk_column: str,
    last_pk: Optional[str],
    batch_size: int,
    db_type: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Fetch one keyset page of rows from *table_name*.

    Returns (rows_as_dicts, new_last_pk_or_None).
    """
    if pk_column.lower() == "rowid":
        select_cols = '"rowid", *'
    else:
        select_cols = "*"

    if last_pk is None:
        where = f'WHERE "{pk_column}" IS NOT NULL'
        params: Dict[str, Any] = {}
    else:
        where = f'WHERE "{pk_column}" IS NOT NULL AND "{pk_column}" > :last_pk'
        params = {"last_pk": last_pk}

    sql = f'''
        SELECT {select_cols} FROM "{table_name}"
        {where}
        ORDER BY "{pk_column}" ASC
        LIMIT {batch_size}
    '''
    try:
        result = session.exec(text(sql), params=params)  # type: ignore
        rows = result.fetchall()
        if not rows:
            return [], None
        keys = list(result.keys()) if hasattr(result, "keys") else []
        dicts = [dict(zip(keys, r)) for r in rows]
        new_pk = str(dicts[-1].get(pk_column, ""))
        return dicts, new_pk or None
    except Exception as exc:
        log.error(f"complex_executor._fetch_batch error on '{table_name}': {exc}")
        return [], None


# ---------------------------------------------------------------------------
# Per-complexity evaluators
# ---------------------------------------------------------------------------

def _cast_numeric(val: Any) -> Optional[float]:
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return None


_OP_FUNCS = {
    "=":  lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def _eval_between(rule: StructuredRule, row: Dict[str, Any]) -> bool:
    """Returns True if the row IS a violation (value outside the allowed range)."""
    raw_val = row.get(rule.target_column)
    if raw_val is None:
        return False  # NULL handled separately by IS NULL rules
    val = _cast_numeric(raw_val)
    if val is None:
        return False
    parts = str(rule.value or "").split(",")
    if len(parts) != 2:
        log.warning(f"BETWEEN rule '{rule.rule_id}' has malformed value '{rule.value}'")
        return False
    try:
        lo, hi = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return False
    # Convention: rule says "must be between lo and hi" → violation if outside
    return not (lo <= val <= hi)


def _eval_regex(rule: StructuredRule, row: Dict[str, Any]) -> bool:
    """Returns True if the row IS a violation (value does NOT match the pattern)."""
    raw_val = row.get(rule.target_column)
    if raw_val is None:
        return False
    pattern = str(rule.value or "")
    if not pattern:
        return False
    try:
        match = re.search(pattern, str(raw_val))
        return match is None  # no match → violation
    except re.error as exc:
        log.warning(f"Invalid regex in rule '{rule.rule_id}': {exc}")
        return False


def _eval_cross_field(rule: StructuredRule, row: Dict[str, Any]) -> bool:
    """
    Returns True if row IS a violation.
    Compares row[target_column] <operator> row[second_column].
    Convention: rule states the ALLOWED condition, so we negate.
    e.g. rule says "Amount Paid MUST EQUAL Amount Received" → op "="
         violation = row['Amount Paid'] != row['Amount Received']
    """
    if not rule.second_column:
        return False
    left  = _cast_numeric(row.get(rule.target_column))
    right = _cast_numeric(row.get(rule.second_column))
    if left is None or right is None:
        # Fall back to string comparison
        left  = str(row.get(rule.target_column, ""))
        right = str(row.get(rule.second_column, ""))
    op_fn = _OP_FUNCS.get(rule.operator, None)
    if op_fn is None:
        return False
    # Rule states the *constraint* (what must be true) — violation = negation
    try:
        constraint_satisfied = op_fn(left, right)
        return not constraint_satisfied
    except Exception:
        return False


def _eval_date_math(rule: StructuredRule, row: Dict[str, Any]) -> bool:
    """
    Returns True if row IS a violation.
    Parses value expressions like:
      "datetime('now', '-90 days')"  → NOW - 90d
      "NOW() - INTERVAL 90 DAYS"    → NOW - 90d
    """
    raw_val = row.get(rule.target_column)
    if raw_val is None:
        return False

    # Parse threshold from rule value
    threshold = _parse_date_threshold(str(rule.value or ""))
    if threshold is None:
        return False

    # Parse the cell value
    row_dt = _parse_date_value(str(raw_val))
    if row_dt is None:
        return False

    op_fn = _OP_FUNCS.get(rule.operator, None)
    if op_fn is None:
        return False
    try:
        return op_fn(row_dt, threshold)
    except Exception:
        return False


_DAYS_RE = re.compile(r"-?\s*(\d+)\s*days?", re.IGNORECASE)
_NOW_VARIANTS = ("NOW()", "NOW", "CURRENT_TIMESTAMP", "CURRENT_DATE")


def _parse_date_threshold(value_str: str) -> Optional[datetime]:
    """
    Convert rule value string to an absolute datetime threshold.
    Handles: "datetime('now', '-90 days')", "NOW() - INTERVAL 90 DAYS", etc.
    """
    now = datetime.now(timezone.utc)
    v = value_str.upper().strip()

    # Simple "NOW()" or "CURRENT_DATE" with no offset → just now
    if v in _NOW_VARIANTS:
        return now

    # Look for a day offset  (e.g. "-90 days")
    m = _DAYS_RE.search(value_str)
    if m:
        days = int(m.group(1))
        # If the raw text has a leading minus sign, subtract; otherwise we check
        # the operator direction at call-time and just return the boundary
        sign = -1 if value_str.replace(" ", "").find("-") != -1 else 1
        return now + timedelta(days=sign * days)

    # Try direct parse
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_date_value(raw: str) -> Optional[datetime]:
    """Try to parse a cell value string as a datetime."""
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_EVALUATORS = {
    "between":    _eval_between,
    "regex":      _eval_regex,
    "cross_field": _eval_cross_field,
    "date_math":  _eval_date_math,
}


def scan_complex_rule(
    session: Session,
    violations_session: Session,
    rule: StructuredRule,
    table: str,
    pk_column: str,
    scan_id: str,
    db_type: str,
    batch_size: int = 1000,
    max_batches: Optional[int] = None,
) -> int:
    """
    Scan *table* for violations of *rule* using Python-side evaluation.

    Returns:
        Number of violations found.
    """
    evaluator = _EVALUATORS.get(rule.rule_complexity)
    if evaluator is None:
        log.warning(
            f"scan_complex_rule: no evaluator for complexity "
            f"'{rule.rule_complexity}' (rule '{rule.rule_id}')"
        )
        return 0

    total_violations = 0
    last_pk: Optional[str] = None
    batch_num = 0

    log.info(
        f"scan_complex_rule: scanning '{table}' for rule '{rule.rule_id}' "
        f"[complexity={rule.rule_complexity}]"
    )

    while True:
        batch_num += 1
        if max_batches and batch_num > max_batches:
            log.warning(
                f"scan_complex_rule: hit max_batches={max_batches} for "
                f"rule '{rule.rule_id}' on table '{table}'"
            )
            break

        rows, new_pk = _fetch_batch(
            session=session,
            table_name=table,
            pk_column=pk_column,
            last_pk=last_pk,
            batch_size=batch_size,
            db_type=db_type,
        )

        if not rows:
            break

        for row in rows:
            try:
                is_violation = evaluator(rule, row)
            except Exception as exc:
                log.debug(f"Evaluator error on row pk={row.get(pk_column)}: {exc}")
                is_violation = False

            if is_violation:
                log_violation(
                    session=violations_session,
                    scan_id=scan_id,
                    rule_id=rule.rule_id,
                    rule_text=rule.rule_text,
                    rule_source=rule.source,
                    table_name=table,
                    record_pk=str(row.get(pk_column, "")),
                    violating_record=row,
                    confidence=rule.confidence,
                    violation_type=rule.rule_type,
                    db_type=db_type,
                )
                total_violations += 1

        if new_pk is None or new_pk == last_pk:
            break
        last_pk = new_pk

    log.info(
        f"scan_complex_rule: finished '{table}' — "
        f"{total_violations} violations for rule '{rule.rule_id}'"
    )
    return total_violations
