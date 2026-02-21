"""
Middleware module for the Data Compliance Agent.

Middleware wraps node execution to add cross-cutting concerns:
- **RetryMiddleware**: Retries failed LLM calls with exponential backoff.
- **GuardrailMiddleware**: Validates inputs/outputs against schemas.
- **LoggingMiddleware**: Structured logging for observability.

These are implemented as simple decorators/wrappers since we're building
LangGraph nodes (not using create_agent). They wrap the LLM chain call
inside each node.
"""
from src.agents.middleware.retry import retry_with_backoff
from src.agents.middleware.guardrails import (
    validate_extraction_output,
    validate_chunk_input,
    InputGuardrail,
    OutputGuardrail,
)
from src.agents.middleware.logging_mw import log_node_execution

__all__ = [
    "retry_with_backoff",
    "validate_extraction_output",
    "validate_chunk_input",
    "InputGuardrail",
    "OutputGuardrail",
    "log_node_execution",
]
