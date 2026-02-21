"""
Runtime configuration helpers.

Centralises the creation of ``RunnableConfig`` dicts so every graph
invocation carries consistent thread IDs, callbacks, tags, and
rate-limiter tokens.

Why a module?
-------------
- Avoids scattering ``{"configurable": {"thread_id": ...}}`` dicts
  across notebooks, CLI scripts, and tests.
- Single place to attach callbacks (UsageTracker, ProgressCallback).
- Single place to swap the rate limiter (Groq free-tier vs. paid).

Usage
-----
    from src.agents.runtime import make_config, get_rate_limiter

    config = make_config(
        thread_id="scan-001",
        tags=["production", "policy-v2"],
    )
    graph.invoke(state, config=config)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.rate_limiters import InMemoryRateLimiter


# ── Module-level singleton rate limiter ───────────────────────────────────────
_RATE_LIMITER: Optional[InMemoryRateLimiter] = None


def get_rate_limiter(
    requests_per_second: float = 0.1,
    check_every_n_seconds: float = 0.1,
    max_bucket_size: int = 10,
) -> InMemoryRateLimiter:
    """
    Return a module-level singleton ``InMemoryRateLimiter``.

    The default ``requests_per_second=0.1`` suits the Groq free tier
    (~6 rpm). Bump it for paid plans.

    Parameters
    ----------
    requests_per_second : float
        Sustained rate cap.
    check_every_n_seconds : float
        Polling interval for the token bucket.
    max_bucket_size : int
        Burst allowance.
    """
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        _RATE_LIMITER = InMemoryRateLimiter(
            requests_per_second=requests_per_second,
            check_every_n_seconds=check_every_n_seconds,
            max_bucket_size=max_bucket_size,
        )
    return _RATE_LIMITER


def make_config(
    thread_id: str = "default",
    *,
    callbacks: Optional[Sequence[BaseCallbackHandler]] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    recursion_limit: int = 50,
) -> Dict[str, Any]:
    """
    Build a ``RunnableConfig`` dict for ``graph.invoke()`` / ``graph.stream()``.

    Parameters
    ----------
    thread_id : str
        Unique identifier for this conversation / scan thread.
        Required when a checkpointer is attached.
    callbacks : list[BaseCallbackHandler], optional
        LangChain callback handlers (e.g. ``UsageTracker``).
    tags : list[str], optional
        Free-form tags for filtering in LangSmith or logs.
    metadata : dict, optional
        Arbitrary key-value metadata attached to every trace.
    recursion_limit : int
        Max node transitions before the graph raises. Default 50.

    Returns
    -------
    dict
        Ready-to-use ``RunnableConfig``.

    Examples
    --------
    >>> config = make_config("scan-001", tags=["dev"])
    >>> graph.invoke(state, config=config)
    """
    config: Dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": recursion_limit,
    }

    if callbacks:
        config["callbacks"] = list(callbacks)
    if tags:
        config["tags"] = tags
    if metadata:
        config["metadata"] = metadata

    return config
