"""
Short-term memory: Checkpointers for LangGraph.

A checkpointer saves the state of each graph step so the graph can:
1. Resume after an interrupt (e.g. human_review node).
2. Replay / rewind execution for debugging.
3. Survive process restarts (when using a DB-backed checkpointer).

IMPORTANT — PostgresSaver.from_conn_string() returns a **context manager**.
You MUST use it with ``with`` (sync) or ``async with`` (async) so the
underlying connection pool is properly opened and closed.

Usage
-----
    from src.agents.memory import get_checkpointer

    # ── In-memory (notebook / tests) ────────────────────────────────
    with get_checkpointer("memory") as cp:
        graph = workflow.compile(checkpointer=cp)
        graph.invoke(state, config={"configurable": {"thread_id": "1"}})

    # ── SQLite (local dev) ──────────────────────────────────────────
    with get_checkpointer("sqlite", db_path="checkpoints.db") as cp:
        graph = workflow.compile(checkpointer=cp)
        graph.invoke(state, config={"configurable": {"thread_id": "1"}})

    # ── PostgreSQL (production) ─────────────────────────────────────
    with get_checkpointer("postgres", conn_string="postgresql://...") as cp:
        graph = workflow.compile(checkpointer=cp)
        graph.invoke(state, config={"configurable": {"thread_id": "1"}})

Every graph.compile(checkpointer=cp) call wires it in.
Every graph.invoke(..., config={"configurable": {"thread_id": "abc"}})
call activates persistence for that thread.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator, Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


@contextmanager
def get_checkpointer(
    backend: Literal["memory", "sqlite", "postgres"] = "memory",
    *,
    db_path: Optional[str] = None,
    conn_string: Optional[str] = None,
) -> Generator[BaseCheckpointSaver, None, None]:
    """
    Context-manager factory for LangGraph checkpointers.

    Wraps every backend in a ``with`` block so resources (DB connections,
    connection pools) are always cleaned up — even on error.

    Parameters
    ----------
    backend : {"memory", "sqlite", "postgres"}
        Which persistence backend to use.
    db_path : str, optional
        Path to the SQLite file (only for ``backend="sqlite"``).
    conn_string : str, optional
        PostgreSQL connection string (only for ``backend="postgres"``).

    Yields
    ------
    BaseCheckpointSaver
        A ready-to-use checkpointer instance.

    Examples
    --------
    >>> with get_checkpointer("memory") as cp:
    ...     graph = workflow.compile(checkpointer=cp)

    >>> with get_checkpointer("sqlite", db_path="cp.db") as cp:
    ...     graph = workflow.compile(checkpointer=cp)

    >>> with get_checkpointer("postgres", conn_string="postgresql://...") as cp:
    ...     graph = workflow.compile(checkpointer=cp)
    """
    if backend == "memory":
        # InMemorySaver has no resources to clean up
        yield InMemorySaver()
        return

    if backend == "sqlite":
        if not db_path:
            raise ValueError("db_path is required for sqlite checkpointer")
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            yield saver
        finally:
            conn.close()
        return

    if backend == "postgres":
        if not conn_string:
            raise ValueError("conn_string is required for postgres checkpointer")
        from langgraph.checkpoint.postgres import PostgresSaver

        # PostgresSaver.from_conn_string() is itself a context manager
        # that manages the psycopg connection pool lifecycle.
        with PostgresSaver.from_conn_string(conn_string) as saver:
            # .setup() creates the required checkpoint tables if they
            # don't already exist — safe to call every time.
            saver.setup()
            yield saver
        return

    raise ValueError(f"Unknown checkpointer backend: {backend!r}")
