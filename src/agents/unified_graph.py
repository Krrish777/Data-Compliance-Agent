"""
Unified Dual-Mode Compliance Agent.

Routes between two operational modes:

  1. **Scanner Mode** (reactive/batch) — scans a database against policy
     rules extracted from PDF documents.  Uses the existing scanner graph.

  2. **Interceptor Mode** (proactive/real-time) — intercepts individual
     SQL queries and makes APPROVE/BLOCK decisions before execution.

Usage
-----
    from src.agents.unified_graph import build_unified_graph
    from src.agents.memory.checkpointer import get_checkpointer

    with get_checkpointer("memory") as cp:
        graph = build_unified_graph(checkpointer=cp)

        # Scanner mode
        result = graph.invoke({
            "mode": "scanner",
            "document_path": "path/to/policy.pdf",
            "db_type": "sqlite",
            "db_config": {"db_path": "company.db"},
        })

        # Interceptor mode
        result = graph.invoke({
            "mode": "interceptor",
            "query": "SELECT email FROM customers",
            "user_id": "analyst_01",
            "user_role": "analyst",
            "stated_purpose": "customer outreach list",
            "db_type": "sqlite",
            "db_config": {"db_path": "company.db"},
        })
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from src.agents.graph import build_graph as build_scanner_graph
from src.agents.interceptor_graph import build_interceptor_graph
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def build_unified_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> "UnifiedComplianceAgent":
    """
    Build the unified dual-mode compliance agent.

    Parameters
    ----------
    checkpointer : BaseCheckpointSaver, optional
        Shared persistence backend.

    Returns
    -------
    UnifiedComplianceAgent
        Wrapper that routes .invoke() / .stream() to the correct sub-graph.
    """
    scanner = build_scanner_graph(checkpointer=checkpointer)
    interceptor = build_interceptor_graph(checkpointer=checkpointer)

    agent = UnifiedComplianceAgent(
        scanner=scanner,
        interceptor=interceptor,
    )
    log.info("build_unified_graph: dual-mode agent ready")
    return agent


class UnifiedComplianceAgent:
    """
    Facade that dispatches to scanner or interceptor sub-graph
    based on the ``mode`` key in the input.
    """

    def __init__(self, scanner: Any, interceptor: Any):
        self.scanner = scanner
        self.interceptor = interceptor

    def invoke(
        self,
        input_state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mode = input_state.pop("mode", "scanner")

        if mode == "interceptor":
            log.info("UnifiedComplianceAgent: routing to INTERCEPTOR mode")
            return self.interceptor.invoke(input_state, config=config)
        else:
            log.info("UnifiedComplianceAgent: routing to SCANNER mode")
            return self.scanner.invoke(input_state, config=config)

    async def ainvoke(
        self,
        input_state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mode = input_state.pop("mode", "scanner")

        if mode == "interceptor":
            log.info("UnifiedComplianceAgent: async routing to INTERCEPTOR mode")
            return await self.interceptor.ainvoke(input_state, config=config)
        else:
            log.info("UnifiedComplianceAgent: async routing to SCANNER mode")
            return await self.scanner.ainvoke(input_state, config=config)

    def stream(
        self,
        input_state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        mode = input_state.pop("mode", "scanner")

        if mode == "interceptor":
            log.info("UnifiedComplianceAgent: streaming INTERCEPTOR mode")
            return self.interceptor.stream(input_state, config=config, **kwargs)
        else:
            log.info("UnifiedComplianceAgent: streaming SCANNER mode")
            return self.scanner.stream(input_state, config=config, **kwargs)

    def get_graph(self, mode: str = "scanner"):
        """Return the underlying compiled graph for a mode (for visualization)."""
        if mode == "interceptor":
            return self.interceptor
        return self.scanner
