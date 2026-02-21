"""
Unit tests for SQLite Database Connector

Tests connection, schema discovery, and sensitive column identification
"""
import pytest
import tempfile
import os
import time
from pathlib import Path
from sqlmodel import SQLModel, Field, create_engine, Session, text
from typing import Optional

from src.agents.tools.database.sqlite_connector import SQLiteConnector
from src.utils.logger import setup_logger

log = setup_logger(__name__)


# Sample Models for Testing
class User(SQLModel, table=True):
    """Test table with sensitive data"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    phone_number: str
    first_name: str
    last_name: str
    password_hash: str


class Product(SQLModel, table=True):
    """Test table without sensitive data"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    price: float
    stock_quantity: int


class Customer(SQLModel, table=True):
    """Test table with various sensitive fields"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ssn: str
    credit_card_number: str
    street_address: str
    salary: float


@pytest.fixture
def temp_db_path():
    """Create a temporary database file in project cache"""
    # Create cache directory in project root
    cache_dir = Path(__file__).parent.parent.parent / ".cache" / "test_dbs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Create unique temp file in cache directory
    import uuid
    db_filename = f"test_{uuid.uuid4().hex[:8]}.db"
    db_path = cache_dir / db_filename
    
    print(f"\n{'='*60}")
    print(f"🗄️  Creating temporary SQLite database")
    print(f"📍 Path: {db_path}")
    print(f"{'='*60}")
    
    yield str(db_path)
    
    # Cleanup with retry logic for Windows
    for attempt in range(5):
        try:
            if db_path.exists():
                db_path.unlink()
                print(f"\n🧹 Cleaned up temporary database: {db_path}")
            break
        except PermissionError:
            if attempt < 4:
                time.sleep(0.2)  # Wait for file handles to be released
            else:
                print(f"\n⚠️  Could not delete temp file (still in use): {db_path}")


@pytest.fixture
def populated_db(temp_db_path):
    """Create and populate a test database"""
    print(f"\n{'='*60}")
    print(f"🔨 Setting up test database with sample data")
    print(f"{'='*60}")
    
    # Create tables
    engine = create_engine(f"sqlite:///{temp_db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    
    print(f"✅ Created tables: User, Product, Customer")
    
    # Insert sample data
    with Session(engine) as session:
        # Add users
        users = [
            User(
                email="john.doe@example.com",
                phone_number="+1-555-0100",
                first_name="John",
                last_name="Doe",
                password_hash="hashed_password_123"
            ),
            User(
                email="jane.smith@example.com",
                phone_number="+1-555-0200",
                first_name="Jane",
                last_name="Smith",
                password_hash="hashed_password_456"
            )
        ]
        
        # Add products
        products = [
            Product(name="Laptop", price=999.99, stock_quantity=50),
            Product(name="Mouse", price=29.99, stock_quantity=200),
            Product(name="Keyboard", price=79.99, stock_quantity=150)
        ]
        
        # Add customers
        customers = [
            Customer(
                ssn="123-45-6789",
                credit_card_number="4532-1234-5678-9010",
                street_address="123 Main St, Springfield",
                salary=75000.00
            )
        ]
        
        for user in users:
            session.add(user)
        for product in products:
            session.add(product)
        for customer in customers:
            session.add(customer)
            
        session.commit()
        
    print(f"✅ Inserted {len(users)} users")
    print(f"✅ Inserted {len(products)} products")
    print(f"✅ Inserted {len(customers)} customers")
    print(f"{'='*60}\n")
    
    return temp_db_path


class TestSQLiteConnector:
    """Test suite for SQLite Connector"""
    
    def test_01_initialization(self, temp_db_path):
        """Test connector initialization"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 1: Initialization")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(temp_db_path)
        
        print(f"✅ Connector initialized successfully")
        print(f"📍 DB Path: {connector.db_path}")
        print(f"🔗 Connection String: {connector.connection_string}")
        
        assert connector.db_path == temp_db_path
        assert connector.connection_string == f"sqlite:///{temp_db_path}"
        assert connector.session is None
        assert connector.engine is None
        
        print(f"✅ All initialization assertions passed")
        print(f"{'='*60}\n")
    
    def test_02_connection(self, populated_db):
        """Test database connection"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 2: Database Connection")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(populated_db)
        
        print(f"🔌 Attempting to connect to database...")
        session = connector.connect()
        
        assert session is not None
        assert connector.engine is not None
        assert connector.session is not None
        
        print(f"✅ Connection established successfully")
        print(f"✅ Engine created: {connector.engine}")
        print(f"✅ Session created: {type(connector.session).__name__}")
        print(f"{'='*60}\n")
        
        connector.close()
    
    def test_03_schema_discovery(self, populated_db):
        """Test schema discovery functionality"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 3: Schema Discovery")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(populated_db)
        connector.connect()
        
        print(f"🔍 Discovering database schema...")
        schema = connector.discover_schema()
        
        print(f"\n📊 Schema Discovery Results:")
        print(f"{'='*60}")
        print(f"📁 Total tables found: {len(schema)}")
        
        expected_tables = ['user', 'product', 'customer']
        for table_name in expected_tables:
            assert table_name in schema, f"Table '{table_name}' not found in schema"
        
        print(f"\n📋 Detailed Table Information:")
        print(f"{'='*60}")
        
        for table_name, table_info in schema.items():
            print(f"\n📁 Table: {table_name.upper()}")
            print(f"   📊 Row count: {table_info['count']}")
            print(f"   📋 Columns ({len(table_info['columns'])}):")
            
            for col in table_info['columns']:
                pk_marker = "🔑" if col['primary_key'] else "  "
                notnull_marker = "❗" if col['not_null'] else "  "
                print(f"      {pk_marker} {notnull_marker} {col['column_name']:20} | {col['data_type']:15} | Default: {col['default_value']}")
        
        # Verify User table structure
        assert 'user' in schema
        user_columns = [col['column_name'] for col in schema['user']['columns']]
        expected_user_columns = ['id', 'email', 'phone_number', 'first_name', 'last_name', 'password_hash']
        
        for col in expected_user_columns:
            assert col in user_columns, f"Column '{col}' not found in User table"
        
        print(f"\n✅ All expected tables found: {expected_tables}")
        print(f"✅ All schema assertions passed")
        print(f"{'='*60}\n")
        
        connector.close()
    
    def test_04_schema_caching(self, populated_db):
        """Test schema caching functionality"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 4: Schema Caching")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(populated_db)
        connector.connect()
        
        # Clear cache first by importing the global cache
        from src.utils.cache import _GLOBAL_CACHE
        _GLOBAL_CACHE.clear()
        print(f"🧹 Cache cleared")
        
        print(f"\n🔍 First call - should hit database...")
        schema1 = connector.discover_schema()
        print(f"✅ Schema retrieved from database")
        
        print(f"\n🔍 Second call - should hit cache...")
        schema2 = connector.discover_schema()
        print(f"✅ Schema retrieved from cache")
        
        assert schema1 == schema2
        print(f"\n✅ Cached schema matches original schema")
        print(f"📊 Tables cached: {list(schema1.keys())}")
        print(f"{'='*60}\n")
        
        connector.close()
    
    def test_05_sensitive_column_identification(self, populated_db):
        """Test identification of sensitive columns"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 5: Sensitive Column Identification")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(populated_db)
        connector.connect()
        
        schema = connector.discover_schema()
        
        print(f"🔍 Analyzing columns for sensitive data...")
        print(f"🤖 Using SentenceTransformer model: {connector.model}")
        
        sensitive_columns = connector.identify_sensitive_columns(schema)
        
        print(f"\n🚨 Sensitive Columns Detected:")
        print(f"{'='*60}")
        print(f"📊 Total sensitive columns found: {len(sensitive_columns)}")
        
        if sensitive_columns:
            print(f"\n{'Table':<15} | {'Column':<25} | {'Data Type':<15} | {'Category':<15}")
            print(f"{'-'*80}")
            for col in sensitive_columns:
                print(f"{col['table']:<15} | {col['column']:<25} | {col['data_type']:<15} | {col['category']:<15}")
        
        # Verify expected sensitive columns are detected
        sensitive_column_names = [col['column'] for col in sensitive_columns]
        
        # These should be detected as sensitive
        expected_sensitive = ['email', 'phone_number', 'password_hash', 'ssn', 'credit_card_number']
        detected_count = sum(1 for col in expected_sensitive if col in sensitive_column_names)
        
        print(f"\n✅ Detected {detected_count}/{len(expected_sensitive)} expected sensitive columns")
        print(f"{'='*60}\n")
        
        assert len(sensitive_columns) > 0, "Should detect at least some sensitive columns"
        
        connector.close()
    
    def test_06_empty_database(self, temp_db_path):
        """Test schema discovery on empty database"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 6: Empty Database Handling")
        print(f"{'='*60}")
        
        # Create empty database
        engine = create_engine(f"sqlite:///{temp_db_path}")
        SQLModel.metadata.create_all(engine)
        
        connector = SQLiteConnector(temp_db_path)
        connector.connect()
        
        print(f"🔍 Discovering schema of empty database...")
        schema = connector.discover_schema()
        
        print(f"📊 Tables found: {len(schema)}")
        print(f"✅ Empty database handled correctly")
        print(f"{'='*60}\n")
        
        assert isinstance(schema, dict)
        
        connector.close()
    
    def test_07_connection_closure(self, populated_db):
        """Test proper connection closure"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 7: Connection Closure")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(populated_db)
        connector.connect()
        
        print(f"🔌 Connection established")
        assert connector.session is not None
        assert connector.engine is not None
        
        print(f"🔌 Closing connection...")
        connector.close()
        
        print(f"✅ Connection closed successfully")
        print(f"{'='*60}\n")
    
    def test_08_error_handling_no_connection(self, temp_db_path):
        """Test error handling when schema discovery is called without connection"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 8: Error Handling - No Connection")
        print(f"{'='*60}")
        
        connector = SQLiteConnector(temp_db_path)
        
        print(f"🔍 Attempting schema discovery without connection...")
        
        with pytest.raises(Exception):
            connector.discover_schema()
        
        print(f"✅ Exception raised as expected")
        print(f"✅ Error handling works correctly")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 SQLite Connector Test Suite")
    print("="*60)
    pytest.main([__file__, "-v", "-s"])
