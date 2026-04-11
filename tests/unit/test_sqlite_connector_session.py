import pytest
from sqlalchemy import text, create_engine
from src.agents.tools.database.sqlite_connector import SQLiteConnector


def test_session_alive_after_discover_schema(tmp_path):
    db = tmp_path / "t.db"
    # Create a trivial table so discover_schema has something to find
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        c.commit()

    conn = SQLiteConnector(db_path=str(db))
    conn.connect()
    try:
        conn.discover_schema()
        # After discovery, the session must still be usable for scanning
        result = conn.session.exec(text("SELECT 1")).scalar()
        assert result == 1, "self.session was closed by discover_schema"
    finally:
        conn.close()
