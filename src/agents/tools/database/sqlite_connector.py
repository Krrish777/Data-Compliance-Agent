from typing import Dict, Any
from sqlmodel import text
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
        
    def discover_schema(self) -> Dict[str, Dict[str, Any]]:
        cached = self.schema_cache.get("sqlite", self.db_path)
        if cached:
            log.info(f"Using cached schema for SQLite database: {self.db_path}")
            return cached
        if not self.session:
            log.error("Database session is not established. Call connect() first.")
            raise
        # Discover schema using SQLModel
        with self.session as session:
            table_query = text("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in session.exec(table_query).fetchall()] # type: ignore
            
            schema = {}
            for table in tables:
                column_query = text(f"PRAGMA table_info({table})")
                column_results = session.exec(column_query) # type: ignore
                columns = []
                for col in column_results.fetchall():
                    columns.append({
                        'column_name': col[1],
                        'data_type': col[2],
                        'not_null': bool(col[3]),
                        'default_value': col[4],
                        'primary_key': bool(col[5])
                    })
                    
                count_query = text(f"SELECT COUNT(*) FROM {table}")
                count_result = session.exec(count_query).fetchone()[0] # type: ignore
                schema[table] = {
                    'columns': columns,
                    'count': count_result
                }
                
        self.schema_cache.set("sqlite", self.db_path, schema)
        log.info(f"Discovered schema : {len(tables)} tables")
        return schema