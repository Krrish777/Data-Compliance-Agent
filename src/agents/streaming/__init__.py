"""
Streaming & callbacks module.

Provides callback handlers and helpers for:
- **Token-level streaming** (``stream_mode="messages"`` in LangGraph).
- **Usage / cost tracking** (token counts per node).
- **Progress callbacks** (report chunk N/M to the caller).

Usage
-----
    from src.agents.streaming import UsageTracker, ProgressCallback

    tracker = UsageTracker()
    graph.invoke(state, config={"callbacks": [tracker]})
    print(tracker.summary())
"""
from src.agents.streaming.callbacks import (
    UsageTracker,
    ProgressCallback,
    stream_graph_updates,
)

__all__ = [
    "UsageTracker",
    "ProgressCallback",
    "stream_graph_updates",
]
