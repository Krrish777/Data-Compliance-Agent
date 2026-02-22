"""
Interceptor Graph — real-time query compliance enforcement pipeline.

Assembles the interceptor nodes into a LangGraph StateGraph:

    START → cache_check
              ├─ HIT  → return_cached → END
              └─ MISS → context_builder → intent_classifier
                          ├─ VAGUE → return_clarification → END
                          └─ CLEAR → policy_mapper
                                      ├─ UNCERTAIN → escalate_human → END
                                      └─ CONFIDENT → verdict_reasoner → auditor
                                                       ├─ PASS → executor → END
                                                       ├─ FAIL (retry) → verdict_reasoner
                                                       └─ FAIL (exhausted) → escalate_human → END

Routing is done via ``Command`` objects inside nodes, so only minimal
edges are declared here.
"""
from __future__ import annotations

from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from src.agents.interceptor_state import InterceptorState
from src.agents.interceptor_nodes.cache_check import cache_check_node
from src.agents.interceptor_nodes.context_builder import context_builder_node
from src.agents.interceptor_nodes.intent_classifier import intent_classifier_node
from src.agents.interceptor_nodes.policy_mapper import policy_mapper_node
from src.agents.interceptor_nodes.verdict_reasoner import verdict_reasoner_node
from src.agents.interceptor_nodes.auditor import auditor_node
from src.agents.interceptor_nodes.executor import executor_node
from src.agents.interceptor_nodes.terminals import (
    return_cached_node,
    return_clarification_node,
    escalate_human_node,
)
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def build_interceptor_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> Any:
    """
    Build and compile the interceptor compliance pipeline.

    Parameters
    ----------
    checkpointer : BaseCheckpointSaver, optional
        Persistence backend for human-in-the-loop support.

    Returns
    -------
    CompiledGraph
        Ready to ``.invoke()`` or ``.stream()``.
    """
    workflow = StateGraph(InterceptorState)

    # ── Add nodes ────────────────────────────────────────────────────────
    workflow.add_node("cache_check", cache_check_node)
    workflow.add_node("context_builder", context_builder_node)
    workflow.add_node("intent_classifier", intent_classifier_node)

    workflow.add_node(
        "policy_mapper",
        policy_mapper_node,
        retry=RetryPolicy(
            max_attempts=3,
            initial_interval=1.0,
            backoff_factor=2.0,
        ),
    )  # type: ignore[call-overload]

    workflow.add_node("verdict_reasoner", verdict_reasoner_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("executor", executor_node)

    # Terminal nodes
    workflow.add_node("return_cached", return_cached_node)
    workflow.add_node("return_clarification", return_clarification_node)
    workflow.add_node("escalate_human", escalate_human_node)

    # ── Edges ────────────────────────────────────────────────────────────
    # Entry point
    workflow.add_edge(START, "cache_check")

    # cache_check routes via Command → return_cached | context_builder
    # context_builder is deterministic, always goes to intent_classifier
    workflow.add_edge("context_builder", "intent_classifier")

    # intent_classifier routes via Command → policy_mapper | return_clarification
    # policy_mapper routes via Command → verdict_reasoner | escalate_human
    # verdict_reasoner always goes to auditor
    workflow.add_edge("verdict_reasoner", "auditor")

    # auditor routes via Command → executor | verdict_reasoner | escalate_human

    # Terminal edges
    workflow.add_edge("executor", END)
    workflow.add_edge("return_cached", END)
    workflow.add_edge("return_clarification", END)
    workflow.add_edge("escalate_human", END)

    # ── Compile ──────────────────────────────────────────────────────────
    graph = workflow.compile(checkpointer=checkpointer)
    log.info("build_interceptor_graph: interceptor pipeline compiled successfully")
    return graph
