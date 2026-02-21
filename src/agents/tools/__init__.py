"""
Agent tools — LangChain @tool-decorated functions.

Each tool is a standalone, testable unit of work that can be:
1. Called directly by a node (``tool.invoke(...)``).
2. Bound to an LLM (``llm.bind_tools([tool])``).
3. Introspected by the model for schema / docs.

Existing database tools live in ``tools/database/``.
"""
from src.agents.tools.pdf_reader import read_pdf_chunks

__all__ = ["read_pdf_chunks"]
