"""
Integration tests for data scanning pipeline.
"""
import tempfile
from pathlib import Path

import pytest
from sqlmodel import Session, create_engine, text

from src.agents.tools.database.violations_store import create_violations_table, get_scan_summary
from src.stages.data_scanning import data_scanning_stage


@pytest.fixture
def test_db_with_violations():
    """Create SQLite test DB with users table and known violations."""
    cache_dir = Path(__file__).parent.parent / ".cache" / "test_dbs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = cache_dir / "test_scan.db"
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        session.exec(
            text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT,
                deleted_at TEXT,
                created_at TEXT
            )
        """)
        )
        session.exec(
            text("""
            INSERT INTO users (id, email, deleted_at, created_at) VALUES
            (1, 'old@example.com', '2020-01-01', '2019-01-01'),
            (2, 'invalid-email', NULL, '2024-01-01'),
            (3, 'valid@example.com', NULL, '2024-06-01')
        """)
        )
        session.commit()

    yield str(db_path)
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


@pytest.fixture
def violations_db_path():
    """Temp path for violations DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def test_data_scanning_stage_finds_violations(test_db_with_violations, violations_db_path):
    """Test that data_scanning_stage finds violations and writes to violations_log."""
    state = {
        "db_type": "sqlite",
        "db_config": {"db_path": test_db_with_violations},
        "schema_metadata": {
            "users": {
                "columns": [
                    {"column_name": "id", "data_type": "INTEGER"},
                    {"column_name": "email", "data_type": "TEXT"},
                    {"column_name": "deleted_at", "data_type": "TEXT"},
                    {"column_name": "created_at", "data_type": "TEXT"},
                ],
                "primary_key": "id",
                "row_count": 3,
            }
        },
        "structured_rules": [
            {
                "rule_id": "retention_90d",
                "rule_text": "Data must be deleted within 90 days",
                "source": "Test",
                "rule_type": "retention",
                "target_column": "deleted_at",
                "operator": "<",
                "value": "datetime('now', '-90 days')",
                "data_type": "datetime",
                "confidence": 1.0,
            },
            {
                "rule_id": "email_format",
                "rule_text": "Emails must be valid",
                "source": "Test",
                "rule_type": "quality",
                "target_column": "email",
                "operator": "NOT LIKE",
                "value": "%@%.%",
                "data_type": "string",
                "confidence": 1.0,
            },
        ],
        "violations_db_path": violations_db_path,
        "batch_size": 100,
    }

    result = data_scanning_stage(state)

    assert "scan_id" in result
    assert "scan_summary" in result
    summary = result["scan_summary"]
    assert summary["status"] == "completed"
    assert summary["tables_scanned"] >= 1
    assert summary["rules_processed"] >= 1
    assert result["current_stage"] == "scanning_complete"
