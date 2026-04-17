"""
Policy Mapper Node (Stage 2) — RAG retrieval + reranking.

Searches the Qdrant vector DB for policy rules relevant to the
intercepted query, reranks them, and assesses confidence.

Routes:
  - High confidence → verdict_reasoner
  - Low confidence  → escalate_human
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from langgraph.types import Command

from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)

CONFIDENCE_THRESHOLD = 0.40  # Qdrant cosine — lower threshold than doc's 0.7 (different scale)
TOP_K_RETRIEVE = 20
TOP_K_FINAL = 5


def policy_mapper_node(
    state: InterceptorState,
) -> Command[Literal["verdict_reasoner", "escalate_human"]]:
    """
    Stage 2: Retrieve relevant policy chunks via RAG.

    Reads from state:
        context_bundle, intent_result

    Writes to state:
        policy_mapping  (serialised PolicyMappingResult dict)
    """
    context = state.get("context_bundle") or {}
    cost = state.get("total_cost_usd", 0.0) or 0.0

    query = context.get("query", "")
    purpose = context.get("stated_purpose", "") or ""
    schema = context.get("schema_snapshot", {})

    # Build a rich search query from context
    pii_cats: List[str] = []
    for col in schema.get("queried_columns", []):
        if col.get("is_pii"):
            pii_cats.extend(col.get("pii_categories", []))
    pii_cats = list(set(pii_cats))

    search_text = f"{query} {purpose}"
    if pii_cats:
        search_text += f" PII categories: {', '.join(pii_cats)}"

    # ── Retrieve from Qdrant ────────────────────────────────────────────
    # Use the process-wide singleton so we don't fight Qdrant's local-mode
    # file lock on every node invocation. Do NOT close() here — the store
    # is shared across calls for the life of the process.
    try:
        from src.vector_database.policy_store import get_policy_store

        store = get_policy_store()
        raw_hits = store.search_policies(
            query_text=search_text,
            top_k=TOP_K_RETRIEVE,
        )
    except Exception as e:
        log.error(f"policy_mapper: vector search failed: {e}")
        raw_hits = []

    if not raw_hits:
        log.warning("policy_mapper: no policy hits — UNCERTAIN")
        result = _uncertain_result()
        cost += 0.015
        return Command(
            update={
                "policy_mapping": result,
                "current_stage": "policy_mapped",
                "total_cost_usd": cost,
            },
            goto="escalate_human",
        )

    # ── Rerank: lightweight scoring boost based on rule_type & PII match ─
    reranked = _rerank(raw_hits, context, pii_cats)

    # Take top-K
    top_policies = reranked[:TOP_K_FINAL]

    # ── Score confidence ────────────────────────────────────────────────
    best_score = top_policies[0]["score"] if top_policies else 0.0
    overall_confidence = best_score

    cost += 0.015  # embedding + search cost

    # ── Build policy chunks ─────────────────────────────────────────────
    policy_chunks = []
    confidence_scores: Dict[str, float] = {}
    for hit in top_policies:
        payload = hit.get("payload", {})
        chunk_id = hit.get("chunk_id", "")
        policy_chunks.append({
            "chunk_id": chunk_id,
            "framework": payload.get("framework", "AML"),
            "article_number": payload.get("rule_id", ""),
            "article_title": payload.get("rule_type", ""),
            "full_text": payload.get("rule_text", ""),
            "concepts": payload.get("concepts", []),
            "version": "1.0",
            "effective_date": None,
            "score": hit["score"],
        })
        confidence_scores[chunk_id] = hit["score"]

    if overall_confidence < CONFIDENCE_THRESHOLD:
        log.info(
            f"policy_mapper: UNCERTAIN — best_score={best_score:.3f} "
            f"< threshold={CONFIDENCE_THRESHOLD}"
        )
        result = {
            "status": "UNCERTAIN",
            "relevant_policies": policy_chunks,
            "confidence_scores": confidence_scores,
            "overall_confidence": overall_confidence,
        }
        return Command(
            update={
                "policy_mapping": result,
                "current_stage": "policy_mapped",
                "total_cost_usd": cost,
            },
            goto="escalate_human",
        )

    log.info(
        f"policy_mapper: CONFIDENT — {len(policy_chunks)} policies, "
        f"best_score={best_score:.3f}"
    )
    result = {
        "status": "CONFIDENT",
        "relevant_policies": policy_chunks,
        "confidence_scores": confidence_scores,
        "overall_confidence": overall_confidence,
    }
    return Command(
        update={
            "policy_mapping": result,
            "current_stage": "policy_mapped",
            "total_cost_usd": cost,
        },
        goto="verdict_reasoner",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uncertain_result() -> Dict[str, Any]:
    return {
        "status": "UNCERTAIN",
        "relevant_policies": [],
        "confidence_scores": {},
        "overall_confidence": 0.0,
    }


def _rerank(
    hits: List[Dict[str, Any]],
    context: Dict[str, Any],
    pii_categories: List[str],
) -> List[Dict[str, Any]]:
    """
    Lightweight reranking using heuristic boosts.

    Boosts scores for:
      - PII-related rules when query touches PII
      - Rules matching queried column names
      - Rules matching stated purpose keywords
    """
    schema = context.get("schema_snapshot", {})
    queried_cols = {
        c.get("column_name", "").lower()
        for c in schema.get("queried_columns", [])
    }
    purpose_words = set(
        (context.get("stated_purpose") or "").lower().split()
    )

    boosted: List[Dict[str, Any]] = []
    for hit in hits:
        score = hit.get("score", 0.0)
        payload = hit.get("payload", {})
        target_col = payload.get("target_column", "").lower()
        rule_text = payload.get("rule_text", "").lower()
        concepts = payload.get("concepts", [])

        boost = 0.0

        # Boost if rule targets a queried column
        if target_col in queried_cols:
            boost += 0.10

        # Boost if PII-related and query has PII
        if pii_categories and any(c in concepts for c in ["pii", "privacy", "encryption"]):
            boost += 0.08

        # Boost if rule text mentions purpose keywords
        if purpose_words and any(w in rule_text for w in purpose_words if len(w) > 3):
            boost += 0.05

        boosted.append({**hit, "score": score + boost})

    boosted.sort(key=lambda x: x["score"], reverse=True)
    return boosted
