"""
Document Processing Cache System

Provides multi-layer caching for:
- Parsed document chunks (Layer 1)
- Generated embeddings (Layer 2)
- Vector DB existence checks (Layer 3)

Uses Redis as primary backend with in-memory fallback.
Designed for SaaS with per-user cache isolation.
"""

import hashlib
import pickle
import time
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import numpy as np
import redis
from dataclasses import dataclass

from src.utils.logger import setup_logger

log = setup_logger(__name__)


@dataclass
class CacheStats:
    """Cache performance statistics"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    errors: int = 0
    total_size_bytes: int = 0
    
    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'errors': self.errors,
            'hit_rate': f"{self.hit_rate:.2f}%",
            'total_requests': self.hits + self.misses,
            'total_size_mb': f"{self.total_size_bytes / 1024 / 1024:.2f}"
        }


class InMemoryCache:
    """Fallback in-memory cache with LRU eviction"""
    
    def __init__(self, max_size_mb: int = 500):
        self.cache: Dict[str, Tuple[bytes, float]] = {}  # key -> (value, expires_at)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.current_size = 0
        log.info(f"InMemoryCache initialized with max size: {max_size_mb}MB")
    
    def get(self, key: str) -> Optional[bytes]:
        if key in self.cache:
            value, expires_at = self.cache[key]
            if time.time() < expires_at:
                return value
            else:
                # Expired
                self._remove(key)
        return None
    
    def set(self, key: str, value: bytes, ttl: int):
        # Check capacity
        value_size = len(value)
        if value_size > self.max_size_bytes:
            log.warning(f"Value too large for cache: {value_size} bytes")
            return
        
        # Evict if needed
        while self.current_size + value_size > self.max_size_bytes and self.cache:
            self._evict_oldest()
        
        # Remove old value if exists
        if key in self.cache:
            self._remove(key)
        
        expires_at = time.time() + ttl
        self.cache[key] = (value, expires_at)
        self.current_size += value_size
    
    def delete(self, key: str):
        self._remove(key)
    
    def exists(self, key: str) -> bool:
        if key in self.cache:
            _, expires_at = self.cache[key]
            if time.time() < expires_at:
                return True
            self._remove(key)
        return False
    
    def clear(self):
        self.cache.clear()
        self.current_size = 0
        log.info("InMemoryCache cleared")
    
    def _remove(self, key: str):
        if key in self.cache:
            value, _ = self.cache[key]
            self.current_size -= len(value)
            del self.cache[key]
    
    def _evict_oldest(self):
        """Evict entry with earliest expiration"""
        if not self.cache:
            return
        oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
        self._remove(oldest_key)
        log.debug(f"Evicted key: {oldest_key}")


class RedisCache:
    """Redis-based cache with connection pooling"""
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50
    ):
        self.host = host
        self.port = port
        self.db = db
        self.connected = False
        
        try:
            self.pool = redis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                decode_responses=False  # We handle bytes
            )
            self.client = redis.Redis(connection_pool=self.pool)
            
            # Test connection
            self.client.ping()
            self.connected = True
            log.info(f"RedisCache connected: {host}:{port}/{db}")
            
        except Exception as e:
            log.error(f"Failed to connect to Redis: {e}")
            self.connected = False
            self.client = None
    
    def get(self, key: str) -> Optional[bytes]:
        if not self.connected:
            return None
        try:
            value = self.client.get(key)  # type: ignore
            return value # type: ignore
        except Exception as e:
            log.error(f"Redis GET error: {e}")
            return None
    
    def set(self, key: str, value: bytes, ttl: int):
        if not self.connected:
            return
        try:
            self.client.setex(key, ttl, value)  # type: ignore
        except Exception as e:
            log.error(f"Redis SET error: {e}")
    
    def delete(self, key: str):
        if not self.connected:
            return
        try:
            self.client.delete(key)  # type: ignore
        except Exception as e:
            log.error(f"Redis DELETE error: {e}")
    
    def exists(self, key: str) -> bool:
        if not self.connected:
            return False
        try:
            return bool(self.client.exists(key))  # type: ignore
        except Exception as e:
            log.error(f"Redis EXISTS error: {e}")
            return False
    
    def clear_pattern(self, pattern: str):
        """Clear all keys matching pattern"""
        if not self.connected:
            return
        try:
            keys = self.client.keys(pattern)  # type: ignore
            if keys:
                self.client.delete(*keys)  # type: ignore
                log.info(f"Cleared {len(keys)} keys matching pattern: {pattern}") # type: ignore
        except Exception as e:
            log.error(f"Redis CLEAR error: {e}")
    
    def get_info(self) -> Dict[str, Any]:
        """Get Redis server info"""
        if not self.connected:
            return {}
        try:
            return self.client.info()  # type: ignore
        except Exception as e:
            log.error(f"Redis INFO error: {e}")
            return {}
    
    def close(self):
        if self.connected and self.client:
            self.client.close()  # type: ignore
            log.info("Redis connection closed")


class CacheManager:
    """
    Orchestrates caching for document processing pipeline
    Uses Redis as primary, in-memory as fallback
    Provides per-user cache isolation for SaaS
    """
    
    # Cache key prefixes
    PREFIX_DOC = "dca:doc"      # Document chunks
    PREFIX_EMB = "dca:emb"      # Embeddings
    PREFIX_META = "dca:meta"    # Metadata
    
    # Default TTLs
    TTL_DOCUMENT = 7 * 24 * 3600      # 7 days
    TTL_EMBEDDING = 30 * 24 * 3600    # 30 days
    TTL_METADATA = 1 * 24 * 3600      # 1 day
    
    def __init__(
        self,
        user_id: Optional[str] = None,
        redis_host: str = 'localhost',
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        use_memory_fallback: bool = True,
        memory_cache_size_mb: int = 500
    ):
        self.user_id = user_id or "default"
        self.stats = CacheStats()
        
        # Initialize Redis
        self.redis = RedisCache(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password
        )
        
        # Initialize fallback
        self.memory_cache: Optional[InMemoryCache] = None
        if use_memory_fallback:
            self.memory_cache = InMemoryCache(max_size_mb=memory_cache_size_mb)
            log.info("Memory fallback cache enabled")
        
        log.info(f"CacheManager initialized for user: {self.user_id}")
    
    def _make_key(self, prefix: str, identifier: str) -> str:
        """Create namespaced cache key"""
        return f"{prefix}:{self.user_id}:{identifier}"
    
    def _hash_content(self, *args) -> str:
        """Create deterministic hash from arguments"""
        content = "|".join(str(arg) for arg in args)
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get(self, key: str) -> Optional[bytes]:
        """Get from cache with fallback"""
        # Try Redis first
        value = self.redis.get(key)
        if value:
            self.stats.hits += 1
            return value
        
        # Try memory fallback
        if self.memory_cache:
            value = self.memory_cache.get(key)
            if value:
                self.stats.hits += 1
                return value
        
        self.stats.misses += 1
        return None
    
    def _set(self, key: str, value: bytes, ttl: int):
        """Set in cache with fallback"""
        self.stats.sets += 1
        self.stats.total_size_bytes += len(value)
        
        # Set in Redis
        self.redis.set(key, value, ttl)
        
        # Set in memory fallback
        if self.memory_cache:
            self.memory_cache.set(key, value, ttl)
    
    # ==================== Document Chunk Caching ====================
    
    def get_document_chunks(
        self,
        file_path: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> Optional[List[Any]]:
        """
        Get cached document chunks
        Cache key based on: file_path + mtime + chunk config
        Auto-invalidates on file modification
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return None
            
            # Include file mtime for auto-invalidation
            file_mtime = path.stat().st_mtime
            file_hash = self._hash_content(
                str(path.absolute()),
                file_mtime,
                chunk_size,
                chunk_overlap
            )
            
            key = self._make_key(self.PREFIX_DOC, file_hash)
            log.debug(f"Looking for cached chunks: {path.name}")
            
            value = self._get(key)
            if value:
                chunks = pickle.loads(value)
                log.info(f"✓ Cache HIT: {path.name} ({len(chunks)} chunks)")
                return chunks
            
            log.debug(f"✗ Cache MISS: {path.name}")
            return None
            
        except Exception as e:
            log.error(f"Error getting cached chunks: {e}")
            self.stats.errors += 1
            return None
    
    def set_document_chunks(
        self,
        file_path: str,
        chunks: List[Any],
        chunk_size: int,
        chunk_overlap: int,
        ttl: Optional[int] = None
    ):
        """Cache document chunks"""
        try:
            path = Path(file_path)
            file_mtime = path.stat().st_mtime
            file_hash = self._hash_content(
                str(path.absolute()),
                file_mtime,
                chunk_size,
                chunk_overlap
            )
            
            key = self._make_key(self.PREFIX_DOC, file_hash)
            value = pickle.dumps(chunks)
            
            self._set(key, value, ttl or self.TTL_DOCUMENT)
            log.info(f"✓ Cached {len(chunks)} chunks for: {path.name}")
            
        except Exception as e:
            log.error(f"Error caching chunks: {e}")
            self.stats.errors += 1
    
    # ==================== Embedding Caching ====================
    
    def get_embedding(
        self,
        content: str,
        model_name: str
    ) -> Optional[np.ndarray]:
        """Get cached embedding for content"""
        try:
            content_hash = self._hash_content(content, model_name)
            key = self._make_key(self.PREFIX_EMB, content_hash)
            
            value = self._get(key)
            if value:
                embedding = np.frombuffer(value, dtype=np.float32)
                log.debug(f"✓ Embedding cache HIT: {content_hash[:8]}")
                return embedding
            
            log.debug(f"✗ Embedding cache MISS: {content_hash[:8]}")
            return None
            
        except Exception as e:
            log.error(f"Error getting cached embedding: {e}")
            self.stats.errors += 1
            return None
    
    def set_embedding(
        self,
        content: str,
        embedding: np.ndarray,
        model_name: str,
        ttl: Optional[int] = None
    ):
        """Cache embedding"""
        try:
            content_hash = self._hash_content(content, model_name)
            key = self._make_key(self.PREFIX_EMB, content_hash)
            value = embedding.astype(np.float32).tobytes()
            
            self._set(key, value, ttl or self.TTL_EMBEDDING)
            log.debug(f"✓ Cached embedding: {content_hash[:8]}")
            
        except Exception as e:
            log.error(f"Error caching embedding: {e}")
            self.stats.errors += 1
    
    def get_embeddings_batch(
        self,
        contents: List[str],
        model_name: str
    ) -> Dict[int, np.ndarray]:
        """
        Get cached embeddings in batch
        Returns dict: {index: embedding} for cached items
        """
        cached = {}
        for idx, content in enumerate(contents):
            embedding = self.get_embedding(content, model_name)
            if embedding is not None:
                cached[idx] = embedding
        
        if cached:
            log.info(f"✓ Found {len(cached)}/{len(contents)} cached embeddings")
        
        return cached
    
    def set_embeddings_batch(
        self,
        contents: List[str],
        embeddings: List[np.ndarray],
        model_name: str,
        ttl: Optional[int] = None
    ):
        """Cache embeddings in batch"""
        if len(contents) != len(embeddings):
            log.error("Contents and embeddings length mismatch")
            return
        
        for content, embedding in zip(contents, embeddings):
            self.set_embedding(content, embedding, model_name, ttl)
        
        log.info(f"✓ Cached {len(embeddings)} embeddings")
    
    # ==================== Metadata & Stats ====================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = self.stats.to_dict()
        
        # Add Redis info if available
        if self.redis.connected:
            redis_info = self.redis.get_info()
            stats['redis'] = {
                'connected': True,
                'used_memory_mb': redis_info.get('used_memory', 0) / 1024 / 1024,
                'total_keys': redis_info.get('db0', {}).get('keys', 0)
            }
        else:
            stats['redis'] = {'connected': False}
        
        # Add memory cache info
        if self.memory_cache:
            stats['memory_cache'] = {
                'size_mb': self.memory_cache.current_size / 1024 / 1024,
                'items': len(self.memory_cache.cache)
            }
        
        return stats
    
    def reset_stats(self):
        """Reset performance statistics"""
        self.stats = CacheStats()
        log.info("Cache statistics reset")
    
    def clear_user_cache(self):
        """Clear all cache for current user"""
        pattern = f"*:{self.user_id}:*"
        self.redis.clear_pattern(pattern)
        
        if self.memory_cache:
            self.memory_cache.clear()
        
        log.info(f"Cleared cache for user: {self.user_id}")
    
    def clear_all_cache(self):
        """Clear entire cache (admin only)"""
        self.redis.clear_pattern("dca:*")
        
        if self.memory_cache:
            self.memory_cache.clear()
        
        log.warning("Cleared ALL cache")
    
    def invalidate_document(self, file_path: str):
        """Manually invalidate specific document cache"""
        path = Path(file_path)
        # We'd need to know all chunk configs to invalidate properly
        # For now, clear all doc caches for this user
        pattern = f"{self.PREFIX_DOC}:{self.user_id}:*"
        self.redis.clear_pattern(pattern)
        log.info(f"Invalidated document cache: {path.name}")
    
    def close(self):
        """Close cache connections"""
        self.redis.close()
        log.info("CacheManager closed")


# Singleton instance for convenience
_default_cache_manager: Optional[CacheManager] = None


def get_cache_manager(
    user_id: Optional[str] = None,
    **kwargs
) -> CacheManager:
    """Get or create default cache manager"""
    global _default_cache_manager
    
    if _default_cache_manager is None:
        _default_cache_manager = CacheManager(user_id=user_id, **kwargs)
    
    return _default_cache_manager
