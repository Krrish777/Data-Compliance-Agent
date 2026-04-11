import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session
from src.agents.tools.database.violations_store import (
    create_violations_table,
    log_violation,
    update_violation_status,
)


@pytest.fixture
def session(tmp_path):
    db = tmp_path / "violations.db"
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        create_violations_table(s, db_type="sqlite")
        for i in range(3):
            log_violation(
                session=s,
                scan_id="test-scan",
                rule_id=f"r{i}",
                rule_text="test rule",
                rule_source="test",
                table_name="t",
                record_pk=str(i),
                violating_record={"col": "val"},
                confidence=0.9,
                violation_type="data_quality",
                db_type="sqlite",
            )
        s.commit()
        yield s


def test_update_violation_status_rejects_injection(session):
    malicious_id = "1); DROP TABLE violations_log; --"
    try:
        update_violation_status(
            session=session,
            violation_ids=[malicious_id, 2],
            status="reviewed",
            reviewer_notes="test",
        )
    except Exception:
        pass
    rows = session.exec(text("SELECT count(*) FROM violations_log")).scalar()
    assert rows == 3, "violations_log was tampered with — injection succeeded"
