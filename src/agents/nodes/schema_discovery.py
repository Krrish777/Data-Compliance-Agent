"""
Schema discovery node for the LangGraph compliance pipeline.

Connects to the target database, runs discover_schema(), and writes
schema_metadata into state. This is purely deterministic — no LLM involved.
"""
from typing import Any, Dict

from src.agents.tools.database.postgres_connector import PostgresConnector
from src.agents.tools.database.sqlite_connector import SQLiteConnector
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def schema_discovery_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: discover the target database schema.

    Reads from state
    ----------------
    - db_type       : 'sqlite' | 'postgresql'
    - db_config     : connection parameters dict

    Writes to state
    ---------------
    - schema_metadata : {table_name: {columns, primary_key, row_count}}
    - current_stage   : 'schema_discovered'
    - errors          : appends on failure (does not raise — graph continues)
    """
    db_type = state.get("db_type", "sqlite")
    db_config = state.get("db_config", {})

    log.info(f"schema_discovery_node: connecting to {db_type} database")

    try:
        if db_type == "sqlite":
            db_path = db_config.get("db_path", "")
            if not db_path:
                raise ValueError("db_config.db_path is required for sqlite")
            connector = SQLiteConnector(db_path)
        elif db_type == "postgresql":
            required = ["host", "port", "database", "user", "password"]
            missing = [k for k in required if k not in db_config]
            if missing:
                raise ValueError(f"db_config missing keys for postgresql: {missing}")
            connector = PostgresConnector(
                host=db_config["host"],
                port=int(db_config["port"]),
                database=db_config["database"],
                user=db_config["user"],
                password=db_config["password"],
            )
        else:
            raise ValueError(f"Unsupported db_type: '{db_type}'")

        connector.connect()
        schema = connector.discover_schema()
        connector.close()

        table_count = len(schema)
        col_count = sum(len(t.get("columns", [])) for t in schema.values())
        pk_missing = [t for t, info in schema.items() if info.get("primary_key") is None]

        log.info(
            f"schema_discovery_node: found {table_count} tables, "
            f"{col_count} columns total"
        )
        if pk_missing:
            log.warning(
                f"schema_discovery_node: {len(pk_missing)} table(s) have no "
                f"primary key and will be skipped during scanning: {pk_missing}"
            )

        return {
            "schema_metadata": schema,
            "current_stage": "schema_discovered",
        }

    except Exception as e:
        log.error(f"schema_discovery_node failed: {e}")
        return {
            "schema_metadata": {},
            "current_stage": "schema_discovery_failed",
            "errors": [f"schema_discovery: {e}"],
        }
