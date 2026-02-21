"""
Unit tests for Document Cache System

Tests both Redis and in-memory caching for:
- Document chunk caching
- Embedding caching  
- Cache statistics
- Cache invalidation
"""

import pytest
import numpy as np
from pathlib import Path
import tempfile
import time

from src.utils.document_cache import (
    CacheManager,
    InMemoryCache,
    RedisCache,
)
from src.docs_processing.docs_processor import DocumentChunk
from src.utils.logger import setup_logger

log = setup_logger(__name__)


class TestInMemoryCache:
    """Test in-memory cache functionality"""
    
    def test_01_initialization(self):
        """Test in-memory cache initialization"""
        print(f"\n{'='*60}")
        print("TEST 1: InMemoryCache Initialization")
        print(f"{'='*60}")
        
        cache = InMemoryCache(max_size_mb=100)
        
        assert cache.max_size_bytes == 100 * 1024 * 1024
        assert cache.current_size == 0
        assert len(cache.cache) == 0
        
        print("Cache initialized with max size: 100MB")
        print(f"Current size: {cache.current_size} bytes")
        print(f"{'='*60}\n")
    
    def test_02_set_and_get(self):
        """Test basic set and get operations"""
        print(f"\n{'='*60}")
        print(f"TEST 2: Set and Get Operations")
        print(f"{'='*60}")
        
        cache = InMemoryCache(max_size_mb=10)
        
        # Set value
        key = "test_key"
        value = b"test_value_12345"
        cache.set(key, value, ttl=60)
        
        print(f"Set key: {key}")
        print(f"Value size: {len(value)} bytes")
        
        # Get value
        retrieved = cache.get(key)
        
        assert retrieved == value
        assert cache.current_size == len(value)
        
        print(f"✅ Retrieved value matches")
        print(f"✅ Cache size updated: {cache.current_size} bytes")
        print(f"{'='*60}\n")
    
    def test_03_expiration(self):
        """Test TTL expiration"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 3: TTL Expiration")
        print(f"{'='*60}")
        
        cache = InMemoryCache(max_size_mb=10)
        
        key = "expire_test"
        value = b"will_expire"
        cache.set(key, value, ttl=1)  # 1 second TTL
        
        # Should exist immediately
        assert cache.get(key) == value
        print(f"✅ Value accessible immediately")
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Should be expired
        assert cache.get(key) is None
        assert cache.current_size == 0
        
        print(f"✅ Value expired after TTL")
        print(f"✅ Cache size reset to 0")
        print(f"{'='*60}\n")
    
    def test_04_eviction(self):
        """Test LRU eviction on capacity"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 4: LRU Eviction")
        print(f"{'='*60}")
        
        cache = InMemoryCache(max_size_mb=0.001)  # Very small: ~1KB
        
        # Add items until eviction occurs
        for i in range(10):
            key = f"key_{i}"
            value = b"x" * 200  # 200 bytes each
            cache.set(key, value, ttl=600)
            print(f"➕ Added {key}: {len(value)} bytes, total: {cache.current_size} bytes")
        
        # Should have evicted some items
        assert len(cache.cache) < 10
        assert cache.current_size <= cache.max_size_bytes
        
        print(f"✅ Eviction triggered")
        print(f"✅ Final cache size: {cache.current_size}/{cache.max_size_bytes} bytes")
        print(f"✅ Items in cache: {len(cache.cache)}")
        print(f"{'='*60}\n")


class TestCacheManager:
    """Test CacheManager functionality"""
    
    @pytest.fixture
    def cache_manager(self):
        """Create cache manager with memory-only backend"""
        # Use memory cache only (no Redis needed for basic tests)
        manager = CacheManager(
            user_id="test_user",
            redis_host="nonexistent",  # Force Redis failure
            use_memory_fallback=True
        )
        yield manager
        manager.close()
    
    @pytest.fixture
    def temp_pdf(self):
        """Create a temporary test file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pdf') as f:
            f.write("test content")
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
    
    def test_05_document_chunk_caching(self, cache_manager, temp_pdf):
        """Test document chunk caching"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 5: Document Chunk Caching")
        print(f"{'='*60}")
        
        # Create test chunks
        chunks = [
            DocumentChunk(
                content=f"Chunk {i}",
                source_file="test.pdf",
                page_number=1,
                chunk_index=i
            )
            for i in range(3)
        ]
        
        # Set chunks in cache
        cache_manager.set_document_chunks(
            file_path=temp_pdf,
            chunks=chunks,
            chunk_size=1000,
            chunk_overlap=200
        )
        
        print(f"💾 Cached {len(chunks)} chunks")
        
        # Retrieve chunks
        retrieved_chunks = cache_manager.get_document_chunks(
            file_path=temp_pdf,
            chunk_size=1000,
            chunk_overlap=200
        )
        
        assert retrieved_chunks is not None
        assert len(retrieved_chunks) == len(chunks)
        assert retrieved_chunks[0].content == chunks[0].content
        
        print(f"✅ Retrieved {len(retrieved_chunks)} chunks from cache")
        print(f"✅ Content matches original")
        print(f"{'='*60}\n")
    
    def test_06_embedding_caching(self, cache_manager):
        """Test embedding caching"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 6: Embedding Caching")
        print(f"{'='*60}")
        
        content = "This is a test document for embedding"
        model_name = "test-model"
        embedding = np.random.rand(384).astype(np.float32)
        
        # Cache embedding
        cache_manager.set_embedding(
            content=content,
            embedding=embedding,
            model_name=model_name
        )
        
        print(f"💾 Cached embedding: {embedding.shape}")
        
        # Retrieve embedding
        retrieved = cache_manager.get_embedding(
            content=content,
            model_name=model_name
        )
        
        assert retrieved is not None
        assert np.allclose(retrieved, embedding)
        
        print(f"✅ Retrieved embedding from cache")
        print(f"✅ Embedding values match (within tolerance)")
        print(f"{'='*60}\n")
    
    def test_07_batch_embedding_cache(self, cache_manager):
        """Test batch embedding caching"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 7: Batch Embedding Caching")
        print(f"{'='*60}")
        
        contents = [f"Document {i}" for i in range(5)]
        embeddings = [np.random.rand(384).astype(np.float32) for _ in range(5)]
        model_name = "test-model"
        
        # Cache batch
        cache_manager.set_embeddings_batch(
            contents=contents,
            embeddings=embeddings,
            model_name=model_name
        )
        
        print(f"💾 Cached {len(embeddings)} embeddings")
        
        # Retrieve batch (should get all)
        cached = cache_manager.get_embeddings_batch(
            contents=contents,
            model_name=model_name
        )
        
        assert len(cached) == len(contents)
        for idx, embedding in cached.items():
            assert np.allclose(embedding, embeddings[idx])
        
        print(f"✅ Retrieved {len(cached)}/{len(contents)} embeddings")
        print(f"✅ All embeddings match")
        print(f"{'='*60}\n")
    
    def test_08_cache_stats(self, cache_manager):
        """Test cache statistics tracking"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 8: Cache Statistics")
        print(f"{'='*60}")
        
        # Perform some operations
        content = "test content"
        embedding = np.random.rand(384).astype(np.float32)
        model_name = "test-model"
        
        # Miss (first access)
        result = cache_manager.get_embedding(content, model_name)
        assert result is None
        
        # Set
        cache_manager.set_embedding(content, embedding, model_name)
        
        # Hit (second access)
        result = cache_manager.get_embedding(content, model_name)
        assert result is not None
        
        # Check stats
        stats = cache_manager.get_stats()
        
        print(f"\n📊 Cache Statistics:")
        print(f"{'='*60}")
        for key, value in stats.items():
            if isinstance(value, dict):
                print(f"{key}:")
                for k, v in value.items():
                    print(f"  {k}: {v}")
            else:
                print(f"{key}: {value}")
        
        assert stats['hits'] > 0
        assert stats['misses'] > 0
        assert stats['sets'] > 0
        
        print(f"\n✅ Hit rate: {stats['hit_rate']}")
        print(f"✅ Total requests: {stats['total_requests']}")
        print(f"{'='*60}\n")
    
    def test_09_cache_invalidation(self, cache_manager, temp_pdf):
        """Test cache invalidation on file modification"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 9: Cache Invalidation")
        print(f"{'='*60}")
        
        # Create and cache chunks
        chunks = [DocumentChunk(content="test", source_file="test.pdf", chunk_index=0)]
        
        cache_manager.set_document_chunks(
            file_path=temp_pdf,
            chunks=chunks,
            chunk_size=1000,
            chunk_overlap=200
        )
        
        # Should retrieve from cache
        retrieved = cache_manager.get_document_chunks(
            file_path=temp_pdf,
            chunk_size=1000,
            chunk_overlap=200
        )
        assert retrieved is not None
        print(f"✅ Initial cache hit")
        
        # Modify file (change mtime)
        time.sleep(0.1)
        Path(temp_pdf).touch()
        
        # Should miss cache (due to mtime change)
        retrieved_after = cache_manager.get_document_chunks(
            file_path=temp_pdf,
            chunk_size=1000,
            chunk_overlap=200
        )
        assert retrieved_after is None
        
        print(f"✅ Cache invalidated after file modification")
        print(f"{'='*60}\n")
    
    def test_10_user_isolation(self):
        """Test cache isolation between users"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 10: User Isolation")
        print(f"{'='*60}")
        
        # Create two cache managers for different users
        cache_user1 = CacheManager(
            user_id="user1",
            redis_host="nonexistent",
            use_memory_fallback=True
        )
        
        cache_user2 = CacheManager(
            user_id="user2",
            redis_host="nonexistent",
            use_memory_fallback=True
        )
        
        content = "shared content"
        model = "model"
        embedding1 = np.ones(384, dtype=np.float32)
        embedding2 = np.zeros(384, dtype=np.float32)
        
        # User 1 caches embedding
        cache_user1.set_embedding(content, embedding1, model)
        print(f"👤 User1 cached embedding")
        
        # User 2 caches different embedding for same content
        cache_user2.set_embedding(content, embedding2, model)
        print(f"👤 User2 cached embedding")
        
        # Each user should get their own embedding
        retrieved1 = cache_user1.get_embedding(content, model)
        retrieved2 = cache_user2.get_embedding(content, model)
        
        assert retrieved1 is not None
        assert retrieved2 is not None
        assert np.allclose(retrieved1, embedding1)
        assert np.allclose(retrieved2, embedding2)
        assert not np.allclose(retrieved1, retrieved2)
        
        print(f"✅ User1 retrieved their embedding")
        print(f"✅ User2 retrieved their embedding")
        print(f"✅ Caches are isolated")
        print(f"{'='*60}\n")
        
        cache_user1.close()
        cache_user2.close()


@pytest.mark.skipif(True, reason="Requires Redis server running")
class TestRedisCache:
    """Test Redis cache (requires running Redis server)"""
    
    def test_11_redis_connection(self):
        """Test Redis connection"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST 11: Redis Connection")
        print(f"{'='*60}")
        
        redis_cache = RedisCache(host='localhost', port=6379)
        
        assert redis_cache.connected
        print(f"✅ Connected to Redis: localhost:6379")
        
        # Test ping
        redis_cache.client.ping()  # type: ignore
        print(f"✅ Redis ping successful")
        
        redis_cache.close()
        print(f"{'='*60}\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 Document Cache System Test Suite")
    print("="*60)
    pytest.main([__file__, "-v", "-s"])
