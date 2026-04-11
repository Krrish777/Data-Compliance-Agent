import pytest
from src.agents.tools.database.sqlite_connector import SQLiteConnector


def test_discover_schema_without_connect_raises_clear_error(tmp_path):
    conn = SQLiteConnector(db_path=str(tmp_path / "unused.db"))
    # Intentionally do NOT call connect()
    with pytest.raises(RuntimeError, match="session"):
        conn.discover_schema()
