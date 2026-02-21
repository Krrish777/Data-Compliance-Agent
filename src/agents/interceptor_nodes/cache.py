"""
3-Layer Decision Cache for the Interceptor.

Layer 1 — Exact:    SHA-256 of normalised query + user role.  TTL 1 hour.
Layer 2 — Fuzzy:    Levenshtein similarity >95%.  TTL 1 hour.
Layer 3 — Semantic: Embedding cosine similarity >0.85.  TTL 6 hours.

Cache entries hold the full decision payload so a cache hit bypasses
the entire LangGraph pipeline.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
EXACT_TTL = 3600       # 1 hour
FUZZY_TTL = 3600       # 1 hour
SEMANTIC_TTL = 21600   # 6 hours
FUZZY_THRESHOLD = 0.95
SEMANTIC_THRESHOLD = 0.92
MAX_CACHE_SIZE = 10_000


# ── Levenshtein helper (pure Python, no deps) ────────────────────────────────

def _levenshtein_ratio(s1: str, s2: str) -> float:
    """Return similarity ratio in [0, 1] based on Levenshtein distance."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Optimise: if length difference alone rules out 95% match, skip
    max_len = max(len1, len2)
    if abs(len1 - len2) / max_len > (1 - FUZZY_THRESHOLD):
        return 0.0

    # Two-row DP
    prev = list(range(len2 + 1))
    for i in range(1, len1 + 1):
        curr = [i] + [0] * len2
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr

    distance = prev[len2]
    return 1.0 - distance / max_len


# ── Cosine similarity helper ─────────────────────────────────────────────────

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return dot / norm if norm > 0 else 0.0


# ── Cache entry ──────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    key: str                              # SHA-256 hash
    normalised_query: str
    user_role: str
    decision_payload: Dict[str, Any]
    embedding: Optional[np.ndarray] = None
    created_at: float = field(default_factory=time.time)
    ttl: float = EXACT_TTL
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


# ── Decision Cache ───────────────────────────────────────────────────────────

class DecisionCache:
    """
    In-memory 3-layer decision cache.

    Thread-safety: single-threaded LangGraph execution — no locking needed.
    In production replace with Redis-backed implementation for durability.
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE):
        self.max_size = max_size
        self._entries: Dict[str, CacheEntry] = {}       # hash → entry
        self._embeddings: List[Tuple[str, np.ndarray]] = []  # (hash, vec)
        self._encoder = None

        # Stats
        self.hits = {"exact": 0, "fuzzy": 0, "semantic": 0}
        self.misses = 0

    # ── Public API ────────────────────────────────────────────────────────

    def lookup(
        self,
        query: str,
        user_role: str,
        query_embedding: Optional[np.ndarray] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Try all three cache layers.

        Returns (decision_payload, layer_name) or (None, None).
        """
        normalised = _normalise_query(query)

        # Layer 1: Exact match
        exact_key = _exact_hash(normalised, user_role)
        entry = self._entries.get(exact_key)
        if entry and not entry.expired:
            entry.hit_count += 1
            self.hits["exact"] += 1
            log.info(f"Cache HIT (exact): {exact_key[:12]}…")
            return entry.decision_payload, "exact"

        # Layer 2: Fuzzy match
        for ent in self._entries.values():
            if ent.expired or ent.user_role != user_role:
                continue
            ratio = _levenshtein_ratio(normalised, ent.normalised_query)
            if ratio >= FUZZY_THRESHOLD:
                ent.hit_count += 1
                self.hits["fuzzy"] += 1
                log.info(f"Cache HIT (fuzzy): ratio={ratio:.3f}")
                return ent.decision_payload, "fuzzy"

        # Layer 3: Semantic match (same role only)
        if query_embedding is not None and len(self._embeddings) > 0:
            best_score = 0.0
            best_key: Optional[str] = None
            for key, emb in self._embeddings:
                ent = self._entries.get(key)
                if ent is None or ent.expired or ent.user_role != user_role:
                    continue
                sim = _cosine_similarity(query_embedding, emb)
                if sim > best_score:
                    best_score = sim
                    best_key = key
            if best_score >= SEMANTIC_THRESHOLD and best_key:
                entry = self._entries[best_key]
                entry.hit_count += 1
                self.hits["semantic"] += 1
                log.info(f"Cache HIT (semantic): score={best_score:.3f}")
                return entry.decision_payload, "semantic"

        self.misses += 1
        return None, None

    def store(
        self,
        query: str,
        user_role: str,
        decision_payload: Dict[str, Any],
        query_embedding: Optional[np.ndarray] = None,
    ) -> None:
        """Store a decision in the cache."""
        self._evict_expired()
        if len(self._entries) >= self.max_size:
            self._evict_lru()

        normalised = _normalise_query(query)
        key = _exact_hash(normalised, user_role)

        entry = CacheEntry(
            key=key,
            normalised_query=normalised,
            user_role=user_role,
            decision_payload=decision_payload,
            embedding=query_embedding,
            ttl=SEMANTIC_TTL if query_embedding is not None else EXACT_TTL,
        )
        self._entries[key] = entry

        if query_embedding is not None:
            self._embeddings.append((key, query_embedding))

        log.debug(f"Cache STORE: {key[:12]}… (total={len(self._entries)})")

    def invalidate_all(self) -> None:
        self._entries.clear()
        self._embeddings.clear()
        log.info("Cache: invalidated all entries")

    @property
    def stats(self) -> Dict[str, Any]:
        total = sum(self.hits.values()) + self.misses
        return {
            "total_lookups": total,
            "hits": dict(self.hits),
            "misses": self.misses,
            "hit_rate": sum(self.hits.values()) / total if total else 0.0,
            "size": len(self._entries),
        }

    # ── Eviction ──────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        expired_keys = [k for k, v in self._entries.items() if v.expired]
        for k in expired_keys:
            del self._entries[k]
        self._embeddings = [
            (k, e) for k, e in self._embeddings if k in self._entries
        ]

    def _evict_lru(self) -> None:
        """Remove the least-recently-used 10% of entries."""
        if not self._entries:
            return
        n_remove = max(1, len(self._entries) // 10)
        sorted_keys = sorted(
            self._entries.keys(),
            key=lambda k: (self._entries[k].hit_count, self._entries[k].created_at),
        )
        for k in sorted_keys[:n_remove]:
            del self._entries[k]
        self._embeddings = [
            (k, e) for k, e in self._embeddings if k in self._entries
        ]


# ── Module-level singleton ───────────────────────────────────────────────────
_CACHE: Optional[DecisionCache] = None


def get_decision_cache() -> DecisionCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = DecisionCache()
    return _CACHE


# ── Utilities ────────────────────────────────────────────────────────────────

def _normalise_query(sql: str) -> str:
    """Lowercase, collapse whitespace, strip trailing semicolons."""
    import re
    sql = sql.strip().rstrip(";").lower()
    sql = re.sub(r"\s+", " ", sql)
    return sql


def _exact_hash(normalised_query: str, user_role: str) -> str:
    payload = f"{normalised_query}|{user_role}"
    return hashlib.sha256(payload.encode()).hexdigest()
