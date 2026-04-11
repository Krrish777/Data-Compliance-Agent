import logging
import pytest
from unittest.mock import patch, MagicMock
from src.agents.tools.database.postgres_connector import PostgresConnector


def test_connection_string_password_masked_in_log(caplog):
    pc = PostgresConnector(
        host="localhost",
        port=5432,
        user="alice",
        password="hunter2secret",
        database="appdb",
    )
    # The custom logger has propagate=False, so we temporarily enable propagation
    # so that caplog (which attaches to the root logger) can capture records.
    logger = logging.getLogger("src.agents.tools.database.baseconnector")
    original_propagate = logger.propagate
    logger.propagate = True

    try:
        # Mock create_engine and Session so connect() reaches the log.info line
        mock_engine = MagicMock()
        mock_session = MagicMock()
        with patch("src.agents.tools.database.baseconnector.create_engine", return_value=mock_engine), \
             patch("src.agents.tools.database.baseconnector.Session", return_value=mock_session), \
             caplog.at_level(logging.INFO, logger="src.agents.tools.database.baseconnector"):
            try:
                pc.connect()
            except Exception:
                pass
    finally:
        logger.propagate = original_propagate

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "hunter2secret" not in logged, "password leaked into log output"
    assert "***" in logged, "expected masked credential marker"
