"""
Callback handlers for streaming, usage tracking, and progress reporting.

These integrate with LangChain's callback system and LangGraph's streaming.

Key classes
-----------
- ``UsageTracker``      — Accumulates token counts across all LLM calls.
- ``ProgressCallback``  — Emits per-chunk progress events.
- ``stream_graph_updates`` — Helper to consume a LangGraph stream and print
  node-level updates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.utils.logger import setup_logger

log = setup_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Usage tracker
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class _UsageRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0


class UsageTracker(BaseCallbackHandler):
    """
    Accumulates token usage across all LLM calls in a graph run.

    Hook it into any ``invoke`` / ``stream`` via the ``callbacks`` config::

        tracker = UsageTracker()
        graph.invoke(state, config={"callbacks": [tracker]})
        print(tracker.summary())
    """

    def __init__(self) -> None:
        super().__init__()
        self._records: List[_UsageRecord] = []

    # ── LangChain callback hooks ─────────────────────────────────────────
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Called after each LLM invocation completes."""
        for gen_list in response.generations:
            for gen in gen_list:
                info = gen.generation_info or {}
                usage = info.get("usage", info.get("token_usage", {}))
                if usage:
                    self._records.append(
                        _UsageRecord(
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                            call_count=1,
                        )
                    )

        # Also check response-level llm_output
        if response.llm_output:
            usage = response.llm_output.get(
                "token_usage", response.llm_output.get("usage", {})
            )
            if usage and not self._records:
                self._records.append(
                    _UsageRecord(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        call_count=1,
                    )
                )

    # ── Summary ──────────────────────────────────────────────────────────
    def summary(self) -> Dict[str, int]:
        """Aggregate all recorded usage into a single dict."""
        total = _UsageRecord()
        for r in self._records:
            total.prompt_tokens += r.prompt_tokens
            total.completion_tokens += r.completion_tokens
            total.total_tokens += r.total_tokens
            total.call_count += r.call_count
        return {
            "prompt_tokens": total.prompt_tokens,
            "completion_tokens": total.completion_tokens,
            "total_tokens": total.total_tokens,
            "llm_calls": total.call_count,
        }

    def reset(self) -> None:
        self._records.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  Progress callback (chunk-level)
# ═══════════════════════════════════════════════════════════════════════════════
class ProgressCallback:
    """
    Simple progress tracker for chunk processing.

    Usage::

        progress = ProgressCallback(total=len(chunks))
        for chunk in chunks:
            process(chunk)
            progress.tick(f"Processed chunk {chunk.chunk_index}")
    """

    def __init__(
        self,
        total: int,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.total = total
        self.current = 0
        self._on_progress = on_progress or self._default_progress

    def tick(self, message: str = "") -> None:
        self.current += 1
        self._on_progress(self.current, self.total, message)

    @staticmethod
    def _default_progress(current: int, total: int, message: str) -> None:
        pct = (current / total * 100) if total else 0
        log.info(f"[Progress {current}/{total} ({pct:.0f}%)] {message}")

    def reset(self) -> None:
        self.current = 0


# ═══════════════════════════════════════════════════════════════════════════════
#  stream_graph_updates — consume LangGraph stream
# ═══════════════════════════════════════════════════════════════════════════════
def stream_graph_updates(
    graph: Any,
    inputs: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    *,
    stream_mode: str = "updates",
    print_fn: Callable[..., None] = print,
) -> Dict[str, Any]:
    """
    Run a LangGraph graph in streaming mode and print node updates.

    Parameters
    ----------
    graph : CompiledGraph
        A compiled LangGraph graph.
    inputs : dict
        Initial state / input.
    config : dict, optional
        LangGraph config (thread_id, callbacks, etc.).
    stream_mode : str
        ``"updates"`` for node-level diffs, ``"values"`` for full state.
    print_fn : callable
        Function used to print updates (default: ``print``).

    Returns
    -------
    dict
        The final state after the stream is exhausted.
    """
    config = config or {}
    final_state: Dict[str, Any] = {}

    for event in graph.stream(inputs, config=config, stream_mode=stream_mode):
        if stream_mode == "updates":
            for node_name, node_output in event.items():
                print_fn(f"\n--- Node: {node_name} ---")
                if isinstance(node_output, dict):
                    for k, v in node_output.items():
                        summary = _summarize_value(v)
                        print_fn(f"  {k}: {summary}")
                final_state.update(node_output)
        else:
            # "values" mode — event is the full state snapshot
            if isinstance(event, dict):
                final_state = event
                print_fn(f"\n--- State snapshot (keys: {list(event.keys())}) ---")

    return final_state


def _summarize_value(v: Any, max_len: int = 120) -> str:
    """Truncate long values for display."""
    s = repr(v)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
