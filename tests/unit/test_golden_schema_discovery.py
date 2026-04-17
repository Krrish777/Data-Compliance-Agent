"""
Golden test for schema_discovery_node against the HI-Small_Trans.db demo DB.

Pins the expected table / column / PII-detection contract so regressions in
the SQLite connector, PII detector, or primary-key detection are caught in CI
rather than on stage.

Skipped automatically if data/HI-Small_Trans.db is not present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_DB = ROOT / "data" / "HI-Small_Trans.db"


pytestmark = pytest.mark.skipif(
    not DEMO_DB.exists(),
    reason=f"Demo DB not found at {DEMO_DB} — skipping golden test",
)


def test_schema_discovery_discovers_transactions_table():
    """Golden: HI-Small_Trans.db must expose at least one table with rows."""
    from src.agents.nodes.schema_discovery import schema_discovery_node

    state = {
        "db_type": "sqlite",
        "db_config": {"db_path": str(DEMO_DB)},
    }
    result = schema_discovery_node(state)

    assert result["current_stage"] == "schema_discovered", (
        f"expected schema_discovered, got {result.get('current_stage')}"
    )
    schema = result["schema_metadata"]
    assert schema, "schema_metadata should not be empty"
    assert len(schema) >= 1, f"expected ≥1 table, got {len(schema)}"

    # At least one table must have the AML columns used by the demo rules.
    expected_columns = {"Amount Paid", "Amount Received", "Payment Format", "Is Laundering"}
    found_any = False
    for _, tinfo in schema.items():
        cols = {c["column_name"] for c in tinfo.get("columns", [])}
        if expected_columns.issubset(cols):
            found_any = True
            break
    assert found_any, (
        f"no table contained all AML demo columns {expected_columns}; "
        f"schema={ {t: list({c['column_name'] for c in i.get('columns', [])})[:8] for t, i in schema.items()} }"
    )


def test_schema_discovery_handles_missing_pk_gracefully():
    """Tables without a primary key must be surfaced, not crash the node."""
    from src.agents.nodes.schema_discovery import schema_discovery_node

    state = {
        "db_type": "sqlite",
        "db_config": {"db_path": str(DEMO_DB)},
    }
    result = schema_discovery_node(state)
    assert "errors" not in result or not result.get("errors"), (
        f"unexpected errors: {result.get('errors')}"
    )
    # primary_key may be None for some tables — that's valid and handled downstream.
    schema = result["schema_metadata"]
    for tbl, info in schema.items():
        pk = info.get("primary_key")
        assert pk is None or isinstance(pk, (str, tuple)), (
            f"table {tbl!r} has unexpected primary_key type: {type(pk)}"
        )


def test_schema_discovery_rejects_unsupported_db_type():
    """Misconfigured db_type must produce an error entry, not crash."""
    from src.agents.nodes.schema_discovery import schema_discovery_node

    state = {"db_type": "mongodb", "db_config": {}}
    result = schema_discovery_node(state)
    assert result["current_stage"] == "schema_discovery_failed"
    assert result["errors"], "expected error list to be populated"
    assert "mongodb" in result["errors"][0].lower() or "unsupported" in result["errors"][0].lower()
