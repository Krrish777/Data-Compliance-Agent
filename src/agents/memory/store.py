"""
Long-term memory: Cross-thread knowledge store.

While the *checkpointer* holds short-term state for a single graph run,
the *store* holds knowledge that persists across sessions:
- Previously extracted rules (avoid re-extracting from the same PDF).
- Known rule patterns (so confidence improves over time).
- User corrections from human_review (learn from feedback).

LangGraph's ``InMemoryStore`` is used for prototyping.
In production, swap for a database-backed store.

Usage
-----
    from src.agents.memory import get_store, ExtractionMemory

    store = get_store()
    mem   = ExtractionMemory(store)

    # Save extraction results
    mem.save_extraction("policy_v2.pdf", rules)

    # Load previous results
    cached = mem.load_extraction("policy_v2.pdf")
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langgraph.store.memory import InMemoryStore

# ── Module-level singleton ────────────────────────────────────────────────────
_STORE: Optional[InMemoryStore] = None


def get_store() -> InMemoryStore:
    """Return a module-level singleton InMemoryStore."""
    global _STORE
    if _STORE is None:
        _STORE = InMemoryStore()
    return _STORE


# ── Extraction Memory helper ─────────────────────────────────────────────────
@dataclass
class ExtractionMemory:
    """
    Convenience wrapper around the raw store for rule-extraction data.

    Namespaces
    ----------
    ("extractions",)       — keyed by document hash
    ("corrections",)       — keyed by rule_id (human feedback)
    ("patterns",)          — keyed by rule_type (known patterns)
    """

    store: InMemoryStore
    _ns_extractions: tuple = field(default=("extractions",), repr=False)
    _ns_corrections: tuple = field(default=("corrections",), repr=False)
    _ns_patterns: tuple = field(default=("patterns",), repr=False)

    # ── Document-level cache ─────────────────────────────────────────────
    @staticmethod
    def _doc_key(doc_path: str) -> str:
        """Hash the document path as a stable key."""
        return hashlib.sha256(doc_path.encode()).hexdigest()[:16]

    def save_extraction(
        self,
        doc_path: str,
        rules: List[Dict[str, Any]],
    ) -> None:
        """Persist extracted rules for a document."""
        key = self._doc_key(doc_path)
        self.store.put(
            self._ns_extractions,
            key,
            {
                "doc_path": doc_path,
                "rules": rules,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "rule_count": len(rules),
            },
        )

    def load_extraction(self, doc_path: str) -> Optional[Dict[str, Any]]:
        """Load previously extracted rules for a document, if any."""
        key = self._doc_key(doc_path)
        result = self.store.get(self._ns_extractions, key)
        return result.value if result else None

    # ── Human correction tracking ────────────────────────────────────────
    def save_correction(
        self,
        rule_id: str,
        original: Dict[str, Any],
        corrected: Dict[str, Any],
    ) -> None:
        """Record a human correction for future learning."""
        self.store.put(
            self._ns_corrections,
            rule_id,
            {
                "original": original,
                "corrected": corrected,
                "corrected_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def get_corrections(self) -> List[Dict[str, Any]]:
        """Retrieve all recorded corrections."""
        items = self.store.search(self._ns_corrections)
        return [item.value for item in items]

    # ── Pattern tracking ─────────────────────────────────────────────────
    def save_pattern(self, rule_type: str, pattern: Dict[str, Any]) -> None:
        """Store a known rule pattern for a rule_type."""
        self.store.put(self._ns_patterns, rule_type, pattern)

    def get_pattern(self, rule_type: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored pattern for a rule_type."""
        result = self.store.get(self._ns_patterns, rule_type)
        return result.value if result else None
