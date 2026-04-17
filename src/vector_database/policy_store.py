"""
Policy rule ingestion into the Vector DB.

After the scanner extracts and structures rules, this module embeds them
into Qdrant so the *interceptor* mode can retrieve relevant policies via
RAG at query time.

This bridges the two modes:
  Scanner  →  extracts & structures rules  →  stores in Qdrant
  Interceptor  →  queries Qdrant  →  maps policies to incoming queries
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from qdrant_client import QdrantClient, models

from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
POLICY_COLLECTION = "policy_rules"
EMBEDDING_DIM = 384  # BGE-small-en-v1.5

# Anchor the local Qdrant dir at the project root so ingest (upsert) and
# query (search) always hit the same on-disk store regardless of the cwd
# the process happens to be launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = str(_PROJECT_ROOT / "qdrant_db")


def _rule_uuid(rule_id: str) -> str:
    """Deterministic UUID from rule_id."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, rule_id))


# ── Process-wide singleton ────────────────────────────────────────────────────
# Qdrant's local (file-based) client holds an exclusive lock on the storage
# directory. Opening a second QdrantClient(path=...) in the same process while
# the first is still alive fails (or, worse, silently routes to a different
# on-disk location). The interceptor graph calls PolicyRuleStore() on every
# policy_mapper_node invocation, so we memoise a single instance per (db_path,
# collection) pair to prevent lock contention and "initialized but data not
# fetching" symptoms.
_STORE_SINGLETONS: Dict[str, "PolicyRuleStore"] = {}


def get_policy_store(
    db_path: Optional[str] = None,
    collection_name: str = POLICY_COLLECTION,
    embedding_dim: int = EMBEDDING_DIM,
) -> "PolicyRuleStore":
    """Return a cached PolicyRuleStore for the given db_path/collection."""
    resolved_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    key = f"{resolved_path}::{collection_name}"
    existing = _STORE_SINGLETONS.get(key)
    if existing is not None and existing.client is not None:
        return existing
    store = PolicyRuleStore(
        db_path=resolved_path,
        collection_name=collection_name,
        embedding_dim=embedding_dim,
    )
    _STORE_SINGLETONS[key] = store
    return store


class PolicyRuleStore:
    """
    Manages the Qdrant collection that holds embedded compliance rules.

    Each point stores:
      - vector: embedding of rule text + metadata
      - payload: rule_id, rule_text, rule_type, target_column, operator,
                 value, confidence, source, framework, concepts
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        collection_name: str = POLICY_COLLECTION,
        embedding_dim: int = EMBEDDING_DIM,
    ):
        # Always resolve to an absolute path so ingest and query hit the same
        # on-disk collection regardless of the caller's cwd.
        self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self.client: Optional[QdrantClient] = None
        self._encoder = None
        self._ensure_client()
        self._ensure_collection()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _ensure_client(self) -> None:
        if self.client is None:
            self.client = QdrantClient(path=self.db_path)
            log.info(f"PolicyRuleStore: Qdrant client → {self.db_path}")

    def _ensure_collection(self) -> None:
        assert self.client is not None
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            log.info(f"PolicyRuleStore: created collection '{self.collection_name}'")
        else:
            log.info(f"PolicyRuleStore: collection '{self.collection_name}' exists")

    def _get_encoder(self):
        """Lazy-load FastEmbed encoder."""
        if self._encoder is None:
            from fastembed import TextEmbedding
            self._encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
        return self._encoder

    def close(self) -> None:
        if self.client and hasattr(self.client, "close"):
            try:
                self.client.close()
            except Exception as e:
                log.warning(f"PolicyRuleStore.close: {e}")
        # Null out the client reference so the local-mode file lock is
        # released before any subsequent QdrantClient(path=...) in this
        # process. Also drop the singleton entry (if any) for this path.
        self.client = None
        key = f"{self.db_path}::{self.collection_name}"
        _STORE_SINGLETONS.pop(key, None)

    # ── Ingestion ─────────────────────────────────────────────────────────

    def ingest_structured_rules(
        self,
        structured_rules: List[Any],
        framework: str = "AML",
    ) -> int:
        """
        Embed and upsert a list of StructuredRule objects.

        Returns the number of points upserted.
        """
        if not structured_rules:
            log.info("PolicyRuleStore.ingest: nothing to ingest (0 rules)")
            return 0

        encoder = self._get_encoder()
        texts: List[str] = []
        payloads: List[Dict[str, Any]] = []
        point_ids: List[str] = []

        for rule in structured_rules:
            rid = getattr(rule, "rule_id", "") or ""
            text = getattr(rule, "rule_text", "") or ""
            rtype = getattr(rule, "rule_type", "") or ""
            col = getattr(rule, "target_column", "") or ""
            op = getattr(rule, "operator", "") or ""
            val = getattr(rule, "value", None)
            conf = getattr(rule, "confidence", 0.5)
            source = getattr(rule, "source", "pdf_extraction")
            complexity = getattr(rule, "rule_complexity", "simple")

            # Build a rich text for embedding
            embed_text = (
                f"Compliance rule: {text}. "
                f"Type: {rtype}. Column: {col}. "
                f"Operator: {op}. Value: {val}."
            )
            texts.append(embed_text)

            payloads.append({
                "rule_id": rid,
                "rule_text": text,
                "rule_type": rtype,
                "target_column": col,
                "operator": op,
                "value": str(val) if val is not None else "",
                "confidence": conf,
                "source": source,
                "framework": framework,
                "rule_complexity": complexity,
                "concepts": _extract_concepts(text, rtype),
            })
            point_ids.append(_rule_uuid(rid))

        # Generate embeddings
        embeddings = list(encoder.embed(texts))
        vectors = [np.array(e, dtype=np.float32).tolist() for e in embeddings]

        # Build Qdrant points
        points = [
            models.PointStruct(id=pid, vector=vec, payload=pay)
            for pid, vec, pay in zip(point_ids, vectors, payloads)
        ]

        assert self.client is not None
        self.client.upsert(collection_name=self.collection_name, points=points)
        log.info(f"PolicyRuleStore.ingest: upserted {len(points)} policy rules")
        return len(points)

    # ── Retrieval (used by interceptor policy_mapper) ─────────────────────

    def search_policies(
        self,
        query_text: str,
        top_k: int = 10,
        min_score: float = 0.0,
        framework_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for policy rules matching a query.

        Returns list of dicts with keys: chunk_id, score, payload.
        """
        encoder = self._get_encoder()
        query_vec = list(encoder.embed([query_text]))[0]
        query_vec = np.array(query_vec, dtype=np.float32).tolist()

        # Optional filter by framework
        qfilter = None
        if framework_filter:
            qfilter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="framework",
                        match=models.MatchValue(value=framework_filter),
                    )
                ]
            )

        assert self.client is not None
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vec,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        ).points

        hits: List[Dict[str, Any]] = []
        for pt in results:
            score = pt.score if pt.score is not None else 0.0
            if score < min_score:
                continue
            hits.append({
                "chunk_id": pt.payload.get("rule_id", str(pt.id)) if pt.payload else str(pt.id),
                "score": score,
                "payload": dict(pt.payload) if pt.payload else {},
            })

        log.info(
            f"PolicyRuleStore.search: query='{query_text[:60]}…' "
            f"→ {len(hits)} hits (top_k={top_k})"
        )
        return hits

    def count(self) -> int:
        """Return number of points in the collection."""
        assert self.client is not None
        info = self.client.get_collection(self.collection_name)
        return info.points_count or 0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_concepts(rule_text: str, rule_type: str) -> List[str]:
    """
    Simple keyword extraction for concept tagging.
    Helps with filtering and explainability.
    """
    concepts: List[str] = []
    text_lower = rule_text.lower()

    concept_keywords = {
        "retention": ["retain", "retention", "delete", "archive", "expire", "days"],
        "access": ["access", "permission", "role", "authoriz", "restrict"],
        "encryption": ["encrypt", "hash", "mask", "obfuscate", "cipher"],
        "pii": ["pii", "personal", "email", "ssn", "name", "address", "phone"],
        "consent": ["consent", "opt-in", "opt-out", "agreement", "permission"],
        "audit": ["audit", "log", "trace", "record", "monitor"],
        "financial": ["amount", "transaction", "currency", "payment", "balance"],
        "aml": ["laundering", "suspicious", "kyc", "sanction", "compliance"],
    }

    for concept, keywords in concept_keywords.items():
        if any(kw in text_lower for kw in keywords):
            concepts.append(concept)

    if rule_type:
        concepts.append(rule_type.replace("data_", ""))

    return list(set(concepts))
