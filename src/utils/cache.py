
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

# Module-level cache (shared across all instances)
_GLOBAL_CACHE: Dict[str, Dict[str, Any]] = {}

class SchemaCache:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
    
    def get(self, db_type: str, db_name: str) -> Optional[Dict]:
        key = f"{db_type}:{db_name}"
        if key in _GLOBAL_CACHE:  # ← Use global cache
            entry = _GLOBAL_CACHE[key]
            if datetime.now() < entry['expires_at']:
                return entry['schema']
            del _GLOBAL_CACHE[key]
        return None
    
    def set(self, db_type: str, db_name: str, schema: Dict):
        key = f"{db_type}:{db_name}"
        _GLOBAL_CACHE[key] = {  # ← Use global cache
            'schema': schema,
            'cached_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=self.ttl_seconds)
        }