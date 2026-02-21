"""
Prompts module — centralized prompt templates for LLM nodes.

Every prompt template lives here so they can be:
- Version-controlled and reviewed independently of node logic.
- Swapped or A/B-tested without touching any node code.
- Reused across the notebook prototype and the production graph.

Usage
-----
    from src.agents.prompts import rule_extraction_prompt

    chain = rule_extraction_prompt | structured_llm
    result = chain.invoke({"chunk_text": "...", "chunk_index": 1, "total_chunks": 10})
"""
from src.agents.prompts.rule_extraction import (
    RULE_EXTRACTION_SYSTEM_PROMPT,
    rule_extraction_prompt,
)

__all__ = [
    "RULE_EXTRACTION_SYSTEM_PROMPT",
    "rule_extraction_prompt",
]
