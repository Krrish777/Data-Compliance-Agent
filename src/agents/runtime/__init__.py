"""
Runtime configuration module.

Provides ``RunnableConfig`` factories so every graph invocation carries
consistent metadata: thread_id, callbacks, tags, rate limiter, etc.

Usage
-----
    from src.agents.runtime import make_config, get_rate_limiter

    config = make_config(thread_id="scan-001", tags=["production"])
    graph.invoke(state, config=config)
"""
from src.agents.runtime.config import (
    make_config,
    get_rate_limiter,
)

__all__ = [
    "make_config",
    "get_rate_limiter",
]
