from typing import Dict, Any
from sqlmodel import text
from src.agents.tools.database.baseconnector import BaseDatabaseConnector
from src.utils.cache import SchemaCache
from src.utils.logger import setup_logger

log = setup_logger(__name__)

class PostgresConnector(BaseDatabaseConnector):
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        super().__init__(connection_string)
        self.db_name = database
        self.cache = SchemaCache()
    
    def discover_schema(self) -> Dict[str, Dict[str, Any]]:
        cache_key = f"{self.db_name}"
        cached = self.cache.get("postgresql", cache_key)
        if cached:
            log.info("Using cached schema")
            return cached
        
        if not self.session:
            raise Exception("Database not connected")
        
        schema = {}
        
        # Get tables - safe parameterized query
        tables_query = text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        tables = self.session.exec(tables_query).fetchall() # type: ignore
        
        for (table_name,) in tables:
            # Get columns - parameterized
            columns_query = text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table_name
                ORDER BY ordinal_position
            """)
            columns_result = self.session.exec(columns_query, {"table_name": table_name}).fetchall()  # type: ignore

            columns = []
            for col in columns_result:
                columns.append({
                    'column_name': col[0],
                    'data_type': col[1],
                    'nullable': (col[2] == 'YES'),
                })

            # Get primary key columns from pg_index
            try:
                pk_result = self.session.exec(
                    text("""
                        SELECT a.attname
                        FROM pg_index i
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = ('public.' || :table_name)::regclass
                          AND i.indisprimary
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                        ORDER BY array_position(i.indkey, a.attnum)
                    """),
                    {"table_name": table_name},
                ).fetchall()  # type: ignore
                if len(pk_result) == 0:
                    primary_key = None
                elif len(pk_result) == 1:
                    primary_key = pk_result[0][0]
                else:
                    primary_key = tuple(row[0] for row in pk_result)
            except Exception as e:
                log.warning(f"Could not detect primary key for table '{table_name}': {e}")
                primary_key = None

            # Get row count - use identifier quoting
            count_query = text(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = self.session.exec(count_query).fetchone()[0]  # type: ignore

            schema[table_name] = {
                'columns': columns,
                'row_count': row_count,
                'primary_key': primary_key,
            }
            log.debug(f"Table '{table_name}': {len(columns)} columns, PK={primary_key}, {row_count} rows")
        
        self.cache.set("postgresql", cache_key, schema)
        log.info(f"Discovered schema: {len(schema)} tables")
        return schema