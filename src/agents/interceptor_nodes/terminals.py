"""
Terminal nodes for the interceptor pipeline.

These are leaf nodes that end the graph execution:
  - return_cached      — return a cached decision (cache hit)
  - return_clarification — request more info from the user (vague query)
  - escalate_human     — pause for human compliance officer review
"""
from __future__ import annotations

from typing import Any, Dict

from src.agents.interceptor_state import InterceptorState
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def _log_audit(state: Dict[str, Any], extra: Dict[str, Any]) -> None:
    """Write an immutable audit log entry from terminal nodes."""
    try:
        from src.agents.interceptor_nodes.audit_logger import get_audit_logger
        logger = get_audit_logger()
        logger.log_decision({**dict(state), **extra})
    except Exception as e:
        log.warning(f"terminal: audit log write failed: {e}")


def return_cached_node(state: InterceptorState) -> Dict[str, Any]:
    """Terminal: return a cached decision without running the pipeline."""
    cached = state.get("cached_decision") or {}

    log.info(
        f"return_cached: layer={state.get('cache_layer')} "
        f"decision={cached.get('final_decision', '?')}"
    )

    result = {
        "final_decision": cached.get("final_decision", "BLOCK"),
        "block_reason": cached.get("block_reason"),
        "guidance": cached.get("guidance"),
        "query_results": cached.get("query_results"),
        "current_stage": "returned_cached",
        "total_cost_usd": 0.0,
    }
    _log_audit(state, result)
    return result


def return_clarification_node(state: InterceptorState) -> Dict[str, Any]:
    """Terminal: the query is too vague — ask the user for clarification."""
    intent = state.get("intent_result") or {}
    missing = intent.get("missing_dimensions", [])
    message = intent.get("clarification_message", "Please provide more details.")

    log.info(f"return_clarification: missing={missing}")

    result = {
        "final_decision": "CLARIFICATION_REQUIRED",
        "block_reason": f"Query is too vague to evaluate. Missing: {', '.join(missing)}",
        "guidance": message,
        "query_results": None,
        "current_stage": "clarification_returned",
        "total_cost_usd": state.get("total_cost_usd", 0.0),
    }
    _log_audit(state, result)
    return result


def escalate_human_node(state: InterceptorState) -> Dict[str, Any]:
    """
    Terminal: escalate to a human compliance officer.

    Uses ``interrupt()`` to pause execution.  The graph can be resumed
    once the human provides a decision.

    Resume payload::

        {
            "decision": "APPROVE" | "BLOCK",
            "reasoning": "human explanation",
            "overrides": {}
        }
    """
    from langgraph.types import interrupt

    context = state.get("context_bundle") or {}
    verdict = state.get("verdict") or {}
    audit = state.get("audit_result") or {}
    mapping = state.get("policy_mapping") or {}

    review_payload = {
        "message": "This query requires human compliance review.",
        "query": context.get("query", state.get("query", "")),
        "user_id": state.get("user_id", ""),
        "user_role": state.get("user_role", ""),
        "stated_purpose": context.get("stated_purpose"),
        "preliminary_verdict": verdict,
        "audit_failures": audit.get("failure_reasons", []),
        "policy_confidence": mapping.get("overall_confidence", 0.0),
        "relevant_policies": [
            {
                "chunk_id": p.get("chunk_id"),
                "rule_text": p.get("full_text", ""),
                "framework": p.get("framework", ""),
            }
            for p in mapping.get("relevant_policies", [])
        ],
    }

    log.info("escalate_human: pausing for human review via interrupt()")

    # This will suspend the graph until resumed
    human_decision = interrupt(review_payload)

    # ── Process human decision after resume ───────────────────────────────
    h_decision = human_decision.get("decision", "BLOCK") if isinstance(human_decision, dict) else "BLOCK"
    h_reasoning = human_decision.get("reasoning", "Human review") if isinstance(human_decision, dict) else "Human review"

    log.info(f"escalate_human: resumed with decision={h_decision}")

    return {
        "final_decision": h_decision,
        "block_reason": h_reasoning if h_decision == "BLOCK" else None,
        "guidance": human_decision.get("guidance") if isinstance(human_decision, dict) else None,
        "query_results": None,
        "current_stage": "human_reviewed",
        "total_cost_usd": state.get("total_cost_usd", 0.0),
    }
