from typing import Dict, Any
from sqlmodel import Session, text
from src.agents.tools.database.baseconnector import BaseDatabaseConnector
from src.utils.cache import SchemaCache
from src.utils.logger import setup_logger

log = setup_logger(__name__)

class SQLiteConnector(BaseDatabaseConnector):
    def __init__(self, db_path: str):
        connection_string = f"sqlite:///{db_path}"
        super().__init__(connection_string)
        self.db_path = db_path
        self.schema_cache = SchemaCache()

    def _get_connect_args(self) -> dict:
        return {"timeout": 30}
        
    def discover_schema(self) -> Dict[str, Dict[str, Any]]:
        """Discover schema with primary key detection for keyset pagination."""
        cached = self.schema_cache.get("sqlite", self.db_path)
        if cached:
            log.info(f"Using cached schema for SQLite database: {self.db_path}")
            return cached
        if not self.session:
            log.error("Database session is not established. Call connect() first.")
            raise RuntimeError(
                "SQLiteConnector.session is not established — call connect() first."
            )
        # Discover schema using SQLModel
        with Session(self.engine) as session:
            table_query = text("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in session.exec(table_query).fetchall()]  # type: ignore

            schema = {}
            for table in tables:
                column_query = text(f"PRAGMA table_info('{table}')")
                column_results = session.exec(column_query)  # type: ignore
                columns = []
                primary_key = None
                pk_columns = []

                for col in column_results.fetchall():
                    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
                    is_pk = col[5] == 1
                    columns.append({
                        'column_name': col[1],
                        'data_type': col[2],
                        'not_null': bool(col[3]),
                        'default_value': col[4],
                        'primary_key': is_pk,
                    })
                    if is_pk:
                        pk_columns.append(col[1])

                # Table-level primary key for keyset pagination
                if len(pk_columns) == 1:
                    primary_key = pk_columns[0]
                elif len(pk_columns) > 1:
                    primary_key = tuple(pk_columns)
                else:
                    # No declared PK — fall back to SQLite's built-in rowid.
                    # Every non-WITHOUT-ROWID table has an implicit rowid that
                    # is stable and suitable for keyset pagination.
                    primary_key = "rowid"
                    columns.append({
                        'column_name': 'rowid',
                        'data_type': 'INTEGER',
                        'not_null': True,
                        'default_value': None,
                        'primary_key': True,
                    })
                    log.debug(f"Table '{table}' has no declared PK — using rowid")

                count_query = text(f"SELECT COUNT(*) FROM \"{table}\"")
                count_result = session.exec(count_query).fetchone()[0]  # type: ignore
                schema[table] = {
                    'columns': columns,
                    'count': count_result,
                    'row_count': count_result,
                    'primary_key': primary_key,
                }
                log.debug(f"Table '{table}': {len(columns)} columns, PK={primary_key}, {count_result} rows")

        self.schema_cache.set("sqlite", self.db_path, schema)
        log.info(f"Discovered schema: {len(tables)} tables")
        return schema