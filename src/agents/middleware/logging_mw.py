"""
Logging middleware — structured, timing-aware logging for graph nodes.

Wraps any node function to emit:
- ``START`` log with node name and input keys
- ``END``   log with node name, duration (ms), and output keys

Usage
-----
    from src.agents.middleware.logging_mw import log_node_execution

    @log_node_execution
    def my_node(state: ComplianceScannerState) -> dict:
        ...

Or applied to an existing function::

    wrapped = log_node_execution(my_node)
"""
from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from src.utils.logger import setup_logger

log = setup_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def log_node_execution(fn: F) -> F:
    """
    Decorator that logs the start, end, and duration of a LangGraph node.

    Works with both sync and async callables.
    """

    @functools.wraps(fn)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        node_name = fn.__name__
        # Try to identify state keys from the first positional arg
        input_keys = _extract_keys(args[0] if args else kwargs)
        log.info(f"[NODE START] {node_name} | input_keys={input_keys}")

        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            output_keys = _extract_keys(result)
            log.info(
                f"[NODE END]   {node_name} | "
                f"duration={elapsed_ms:.1f}ms | "
                f"output_keys={output_keys}"
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log.error(
                f"[NODE ERROR] {node_name} | "
                f"duration={elapsed_ms:.1f}ms | "
                f"error={exc!r}"
            )
            raise

    @functools.wraps(fn)
    async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
        node_name = fn.__name__
        input_keys = _extract_keys(args[0] if args else kwargs)
        log.info(f"[NODE START] {node_name} | input_keys={input_keys}")

        t0 = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            output_keys = _extract_keys(result)
            log.info(
                f"[NODE END]   {node_name} | "
                f"duration={elapsed_ms:.1f}ms | "
                f"output_keys={output_keys}"
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log.error(
                f"[NODE ERROR] {node_name} | "
                f"duration={elapsed_ms:.1f}ms | "
                f"error={exc!r}"
            )
            raise

    import asyncio

    if asyncio.iscoroutinefunction(fn):
        return _async_wrapper  # type: ignore[return-value]
    return _sync_wrapper  # type: ignore[return-value]


def _extract_keys(obj: Any) -> list[str]:
    """Best-effort extraction of dict keys from a node input/output."""
    if isinstance(obj, dict):
        return sorted(obj.keys())
    return []
