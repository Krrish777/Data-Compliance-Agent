"""
Unit tests for Postgres Database Connector

Tests connection, schema discovery, and sensitive column identification
Note: These tests can run in two modes:
1. With actual Postgres database (if available)
2. With mock (if no database is available)
"""
import pytest
from unittest.mock import MagicMock

from src.agents.tools.database.postgres_connector import PostgresConnector
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# Set this to True if you have a local Postgres database for testing
POSTGRES_AVAILABLE = False

# If POSTGRES_AVAILABLE is True, set these credentials
POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'test_db',
    'user': 'test_user',
    'password': 'test_password'
}


@pytest.fixture
def postgres_connector():
    """Create a Postgres connector instance"""
    return PostgresConnector(
        host=POSTGRES_CONFIG['host'],
        port=POSTGRES_CONFIG['port'],
        database=POSTGRES_CONFIG['database'],
        user=POSTGRES_CONFIG['user'],
        password=POSTGRES_CONFIG['password']
    )


@pytest.fixture
def mock_session():
    """Create a mock session for testing without actual database"""
    session = MagicMock()
    return session


@pytest.fixture
def sample_schema():
    """Sample schema for testing"""
    return {
        'users': {
            'columns': [
                {'column_name': 'id', 'data_type': 'integer', 'nullable': False},
                {'column_name': 'email', 'data_type': 'character varying', 'nullable': False},
                {'column_name': 'phone_number', 'data_type': 'character varying', 'nullable': True},
                {'column_name': 'first_name', 'data_type': 'character varying', 'nullable': False},
                {'column_name': 'last_name', 'data_type': 'character varying', 'nullable': False},
                {'column_name': 'password_hash', 'data_type': 'character varying', 'nullable': False},
            ],
            'row_count': 100
        },
        'products': {
            'columns': [
                {'column_name': 'id', 'data_type': 'integer', 'nullable': False},
                {'column_name': 'name', 'data_type': 'character varying', 'nullable': False},
                {'column_name': 'price', 'data_type': 'numeric', 'nullable': False},
                {'column_name': 'stock_quantity', 'data_type': 'integer', 'nullable': True},
            ],
            'row_count': 50
        },
        'customers': {
            'columns': [
                {'column_name': 'id', 'data_type': 'integer', 'nullable': False},
                {'column_name': 'ssn', 'data_type': 'character varying', 'nullable': False},
                {'column_name': 'credit_card_number', 'data_type': 'character varying', 'nullable': True},
                {'column_name': 'street_address', 'data_type': 'text', 'nullable': True},
                {'column_name': 'salary', 'data_type': 'numeric', 'nullable': True},
            ],
            'row_count': 75
        }
    }


class TestPostgresConnectorInitialization:
    """Test suite for Postgres Connector initialization"""
    
    def test_01_initialization(self, postgres_connector):
        """Test connector initialization"""
        print(f"\n{'='*60}")
        print("🧪 TEST 1: Initialization")
        print(f"{'='*60}")
        
        print("✅ Connector initialized successfully")
        print(f"📍 Database: {postgres_connector.db_name}")
        print(f"🔗 Connection String: postgresql://{POSTGRES_CONFIG['user']}:***@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")
        
        assert postgres_connector.db_name == POSTGRES_CONFIG['database']
        assert postgres_connector.session is None
        assert postgres_connector.engine is None
        
        print("✅ All initialization assertions passed")
        print(f"{'='*60}\n")


class TestPostgresConnectorWithMock:
    """Test suite using mocked database"""
    
    def test_02_schema_discovery_mock(self, postgres_connector, sample_schema):
        """Test schema discovery with mocked data"""
        print(f"\n{'='*60}")
        print("🧪 TEST 2: Schema Discovery (Mocked)")
        print(f"{'='*60}")
        
        # Mock the session and its methods
        mock_session = MagicMock()
        
        # Mock table query results
        mock_tables = [('users',), ('products',), ('customers',)]
        mock_table_result = MagicMock()
        mock_table_result.fetchall.return_value = mock_tables
        
        # Mock column query results for each table
        mock_users_columns = [
            ('id', 'integer', 'NO'),
            ('email', 'character varying', 'NO'),
            ('phone_number', 'character varying', 'YES'),
            ('first_name', 'character varying', 'NO'),
            ('last_name', 'character varying', 'NO'),
            ('password_hash', 'character varying', 'NO'),
        ]
        
        mock_products_columns = [
            ('id', 'integer', 'NO'),
            ('name', 'character varying', 'NO'),
            ('price', 'numeric', 'NO'),
            ('stock_quantity', 'integer', 'YES'),
        ]
        
        mock_customers_columns = [
            ('id', 'integer', 'NO'),
            ('ssn', 'character varying', 'NO'),
            ('credit_card_number', 'character varying', 'YES'),
            ('street_address', 'text', 'YES'),
            ('salary', 'numeric', 'YES'),
        ]
        
        # Setup mock to return different results based on call
        def mock_exec(query, params=None):
            result = MagicMock()
            if params is None:
                # Table query
                result.fetchall.return_value = mock_tables
            elif params.get('table_name') == 'users':
                result.fetchall.return_value = mock_users_columns
            elif params.get('table_name') == 'products':
                result.fetchall.return_value = mock_products_columns
            elif params.get('table_name') == 'customers':
                result.fetchall.return_value = mock_customers_columns
            else:
                # Count query
                result.fetchone.return_value = (100,)
            return result
        
        mock_session.exec.side_effect = mock_exec
        postgres_connector.session = mock_session
        
        # Clear cache
        from src.utils.cache import _GLOBAL_CACHE
        _GLOBAL_CACHE.clear()
        
        print("🔍 Discovering database schema (mocked)...")
        schema = postgres_connector.discover_schema()
        
        print("\n📊 Schema Discovery Results:")
        print(f"{'='*60}")
        print(f"📁 Total tables found: {len(schema)}")
        
        print("\n📋 Detailed Table Information:")
        print(f"{'='*60}")
        
        for table_name, table_info in schema.items():
            print(f"\n📁 Table: {table_name.upper()}")
            print(f"   📊 Row count: {table_info['row_count']}")
            print(f"   📋 Columns ({len(table_info['columns'])}):")
            
            for col in table_info['columns']:
                nullable_marker = "✓" if col['nullable'] else "✗"
                print(f"      [{nullable_marker}] {col['column_name']:25} | {col['data_type']:20}")
        
        assert len(schema) == 3
        assert 'users' in schema
        assert 'products' in schema
        assert 'customers' in schema
        
        print("\n✅ All expected tables found")
        print("✅ Schema structure validated")
        print(f"{'='*60}\n")
    
    def test_03_sensitive_column_identification_mock(self, postgres_connector, sample_schema):
        """Test sensitive column identification with mocked schema"""
        print(f"\n{'='*60}")
        print("🧪 TEST 3: Sensitive Column Identification (Mocked)")
        print(f"{'='*60}")
        
        print(f"🔍 Analyzing columns for sensitive data...")
        print(f"🤖 Using SentenceTransformer model: {postgres_connector.model}")
        
        sensitive_columns = postgres_connector.identify_sensitive_columns(sample_schema)
        
        print(f"\n🚨 Sensitive Columns Detected:")
        print(f"{'='*60}")
        print(f"📊 Total sensitive columns found: {len(sensitive_columns)}")
        
        if sensitive_columns:
            print(f"\n{'Table':<15} | {'Column':<25} | {'Data Type':<20} | {'Category':<15}")
            print(f"{'-'*85}")
            for col in sensitive_columns:
                print(f"{col['table']:<15} | {col['column']:<25} | {col['data_type']:<20} | {col['category']:<15}")
        
        # Verify expected sensitive columns are detected
        sensitive_column_names = [col['column'] for col in sensitive_columns]
        
        print(f"\n🔍 Expected sensitive columns to detect:")
        expected_sensitive = ['email', 'phone_number', 'password_hash', 'ssn', 'credit_card_number', 'street_address', 'salary']
        for col in expected_sensitive:
            detected = "✅" if col in sensitive_column_names else "⚠️"
            print(f"   {detected} {col}")
        
        detected_count = sum(1 for col in expected_sensitive if col in sensitive_column_names)
        print(f"\n✅ Detected {detected_count}/{len(expected_sensitive)} expected sensitive columns")
        print(f"{'='*60}\n")
        
        assert len(sensitive_columns) > 0, "Should detect at least some sensitive columns"
    
    def test_04_schema_caching_mock(self, postgres_connector):
        """Test schema caching functionality"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 4: Schema Caching (Mocked)")
        print(f"{'='*60}")
        
        # Create mock schema
        mock_schema = {
            'test_table': {
                'columns': [{'column_name': 'id', 'data_type': 'integer', 'nullable': False}],
                'row_count': 10
            }
        }
        
        # Clear cache
        from src.utils.cache import _GLOBAL_CACHE
        _GLOBAL_CACHE.clear()
        print(f"🧹 Cache cleared")
        
        # Set schema in cache
        cache_key = f"{postgres_connector.db_name}"
        postgres_connector.cache.set("postgresql", cache_key, mock_schema)
        print(f"💾 Schema manually cached")
        
        # Mock session to verify it's not called
        postgres_connector.session = MagicMock()
        
        print(f"\n🔍 Calling discover_schema - should hit cache...")
        schema = postgres_connector.discover_schema()
        
        # Session.exec should not be called if cache is hit
        postgres_connector.session.exec.assert_not_called()
        
        assert schema == mock_schema
        print(f"✅ Schema retrieved from cache (database not queried)")
        print(f"📊 Cached tables: {list(schema.keys())}")
        print(f"{'='*60}\n")
    
    def test_05_connection_string_format(self, postgres_connector):
        """Test connection string is correctly formatted"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 5: Connection String Format")
        print(f"{'='*60}")
        
        expected = f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}"
        
        print(f"🔗 Expected format: postgresql://user:password@host:port/database")
        print(f"✅ Connection string format is correct")
        
        assert postgres_connector.connection_string == expected
        print(f"{'='*60}\n")
    
    def test_06_error_handling_no_connection(self, postgres_connector):
        """Test error handling when schema discovery is called without connection"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 6: Error Handling - No Connection")
        print(f"{'='*60}")
        
        # Clear cache to force database query
        from src.utils.cache import _GLOBAL_CACHE
        _GLOBAL_CACHE.clear()
        
        # Ensure session is None
        postgres_connector.session = None
        
        print(f"🔍 Attempting schema discovery without connection...")
        
        with pytest.raises(Exception) as exc_info:
            postgres_connector.discover_schema()
        
        print(f"✅ Exception raised as expected: {exc_info.value}")
        print(f"✅ Error handling works correctly")
        print(f"{'='*60}\n")


@pytest.mark.skipif(not POSTGRES_AVAILABLE, reason="Postgres database not available")
class TestPostgresConnectorLive:
    """Test suite with actual Postgres database (skipped if not available)"""
    
    def test_07_live_connection(self, postgres_connector):
        """Test actual database connection"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 7: Live Database Connection")
        print(f"{'='*60}")
        
        print(f"🔌 Attempting to connect to live Postgres database...")
        session = postgres_connector.connect()
        
        assert session is not None
        assert postgres_connector.engine is not None
        assert postgres_connector.session is not None
        
        print(f"✅ Live connection established successfully")
        print(f"✅ Engine created: {postgres_connector.engine}")
        print(f"✅ Session created: {type(postgres_connector.session).__name__}")
        print(f"{'='*60}\n")
        
        postgres_connector.close()
    
    def test_08_live_schema_discovery(self, postgres_connector):
        """Test schema discovery on actual database"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 8: Live Schema Discovery")
        print(f"{'='*60}")
        
        postgres_connector.connect()
        from src.utils.cache import _GLOBAL_CACHE
        _GLOBAL_CACHE.clear()
        
        print(f"🔍 Discovering schema from live database...")
        schema = postgres_connector.discover_schema()
        
        print(f"\n📊 Schema Discovery Results:")
        print(f"{'='*60}")
        print(f"📁 Total tables found: {len(schema)}")
        
        for table_name, table_info in schema.items():
            print(f"\n📁 Table: {table_name}")
            print(f"   📊 Row count: {table_info['row_count']}")
            print(f"   📋 Columns: {len(table_info['columns'])}")
        
        assert isinstance(schema, dict)
        print(f"\n✅ Live schema discovery successful")
        print(f"{'='*60}\n")
        
        postgres_connector.close()


def test_summary():
    """Print test summary"""
    print(f"\n{'='*60}")
    print(f"📋 TEST CONFIGURATION")
    print(f"{'='*60}")
    print(f"Postgres Available: {POSTGRES_AVAILABLE}")
    if POSTGRES_AVAILABLE:
        print(f"Host: {POSTGRES_CONFIG['host']}")
        print(f"Port: {POSTGRES_CONFIG['port']}")
        print(f"Database: {POSTGRES_CONFIG['database']}")
    else:
        print(f"ℹ️  Live database tests will be skipped")
        print(f"ℹ️  To enable live tests, set POSTGRES_AVAILABLE = True")
        print(f"ℹ️  and configure POSTGRES_CONFIG with valid credentials")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    test_summary()
    print("\n" + "="*60)
    print("🧪 Postgres Connector Test Suite")
    print("="*60)
    pytest.main([__file__, "-v", "-s"])
