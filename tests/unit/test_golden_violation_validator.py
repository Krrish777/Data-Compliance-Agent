"""
Golden test for violation_validator_node.

Stands up a minimal violations DB with three synthetic records (two genuine,
one obvious false positive) and checks the validator returns a
validation_summary dict of the expected shape.

Skipped if GROQ_API_KEY is unset.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlmodel import Session, create_engine, text

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("GROQ_API_KEY"),
        reason="GROQ_API_KEY not set — skipping live LLM golden test",
    ),
    pytest.mark.slow,
]


@pytest.fixture
def synthetic_violations_db(tmp_path: Path) -> str:
    """Create a fresh violations DB with 3 sample rows for one rule."""
    from src.agents.tools.database.violations_store import create_violations_table
    db_path = tmp_path / "violations.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    with Session(engine) as session:
        create_violations_table(session, "sqlite")
        now = "2026-04-17T12:00:00+00:00"
        # Rule under test: "Payment Format must not be NULL or empty"
        samples = [
            # record 1 — actually empty: genuine violation
            ("scan_golden", "FMT-001", "Payment Format not empty", "pdf_extraction",
             "transactions", "1", json.dumps({"id": 1, "Payment Format": ""}),
             0.6, "data_quality"),
            # record 2 — Bitcoin: not a violation of "not empty"; false positive
            ("scan_golden", "FMT-001", "Payment Format not empty", "pdf_extraction",
             "transactions", "2", json.dumps({"id": 2, "Payment Format": "Bitcoin"}),
             0.6, "data_quality"),
            # record 3 — NULL: genuine violation
            ("scan_golden", "FMT-001", "Payment Format not empty", "pdf_extraction",
             "transactions", "3", json.dumps({"id": 3, "Payment Format": None}),
             0.6, "data_quality"),
        ]
        for sample in samples:
            session.exec(  # type: ignore
                text(
                    "INSERT INTO violations_log "
                    "(scan_id, rule_id, rule_text, rule_source, table_name, "
                    "record_primary_key, violating_data, confidence, violation_type, "
                    "review_status, logged_at) "
                    "VALUES (:scan_id, :rule_id, :rule_text, :rule_source, :table_name, "
                    ":pk, :data, :conf, :vtype, 'pending', :ts)"
                ),
                params={
                    "scan_id": sample[0], "rule_id": sample[1], "rule_text": sample[2],
                    "rule_source": sample[3], "table_name": sample[4], "pk": sample[5],
                    "data": sample[6], "conf": sample[7], "vtype": sample[8], "ts": now,
                },
            )
        session.commit()
    return str(db_path)


def test_validator_produces_summary_shape(synthetic_violations_db: str):
    """validation_summary must have the documented keys even for tiny inputs."""
    from src.agents.nodes.violation_validator import violation_validator_node

    state = {
        "scan_id": "scan_golden",
        "violations_db_path": synthetic_violations_db,
        "structured_rules": [
            {
                "rule_id": "FMT-001",
                "rule_type": "data_quality",
                "rule_text": "Payment Format must not be NULL or empty",
            }
        ],
        "scan_summary": {"violations_by_rule": {"FMT-001": 3}},
    }
    result = violation_validator_node(state)
    assert result["current_stage"] in {"validation_complete", "validation_skipped"}
    summary = result["validation_summary"]
    assert isinstance(summary, dict)
    # If not skipped, the key contract must hold.
    if not summary.get("skipped"):
        for key in ("total_validated", "confirmed", "false_positives", "by_rule"):
            assert key in summary, f"missing key {key!r} in validation_summary"
        assert isinstance(summary["by_rule"], dict)
