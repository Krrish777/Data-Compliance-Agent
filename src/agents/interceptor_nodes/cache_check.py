"""
Cache Check Node — first node in the interceptor pipeline.

Checks the 3-layer decision cache.  On hit → route to return_cached.
On miss → route to context_builder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from langgraph.types import Command

from src.agents.interceptor_nodes.cache import get_decision_cache
from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def cache_check_node(
    state: InterceptorState,
) -> Command[Literal["return_cached", "context_builder"]]:
    """
    Check the 3-layer decision cache before running the full pipeline.

    Returns Command routing to ``return_cached`` on hit or
    ``context_builder`` on miss.
    """
    query = state.get("query", "")
    user_role = state.get("user_role", "analyst")

    cache = get_decision_cache()

    # Try to generate a query embedding for semantic layer
    query_embedding = None
    try:
        from fastembed import TextEmbedding
        import numpy as np
        _encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
        query_embedding = np.array(
            list(_encoder.embed([query]))[0], dtype=np.float32
        )
    except Exception:
        log.debug("cache_check: could not generate query embedding for semantic cache")

    decision, layer = cache.lookup(query, user_role, query_embedding)

    if decision is not None:
        log.info(f"cache_check_node: HIT on layer={layer}")
        return Command(
            update={
                "cache_hit": True,
                "cache_layer": layer,
                "cached_decision": decision,
                "current_stage": "cache_hit",
                "processing_start_time": datetime.now(timezone.utc).isoformat(),
            },
            goto="return_cached",
        )

    log.info("cache_check_node: MISS — proceeding to context_builder")
    return Command(
        update={
            "cache_hit": False,
            "cache_layer": None,
            "cached_decision": None,
            "current_stage": "cache_check_miss",
            "processing_start_time": datetime.now(timezone.utc).isoformat(),
        },
        goto="context_builder",
    )
