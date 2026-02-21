"""
PDF reader tool — wraps DocumentProcessor as a LangChain @tool.

Why a tool and not just a function?
-----------------------------------
- Schema auto-documentation: LLMs can see the tool's name, description,
  and parameter schema without any extra prompting.
- Consistent return type: Always returns a list of dicts, easy to serialize.
- Testable in isolation: ``read_pdf_chunks.invoke({"pdf_path": "..."})``

Usage
-----
    from src.agents.tools import read_pdf_chunks

    # As a plain function call inside a node:
    chunks = read_pdf_chunks.invoke({"pdf_path": "/data/policy.pdf"})

    # Bound to an LLM (optional — lets the model decide when to read):
    llm_with_tools = llm.bind_tools([read_pdf_chunks])
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from pathlib import Path

from langchain_core.tools import tool

from src.docs_processing.docs_processor import DocumentProcessor
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ── Optional CacheManager (needs redis + numpy — may not be available) ───────
_cache_manager = None
try:
    from src.utils.document_cache import CacheManager
    _cache_manager = CacheManager(use_memory_fallback=True, memory_cache_size_mb=200)
    log.info("pdf_reader: CacheManager initialised (redis+memory)")
except Exception as _cm_err:
    log.warning(f"pdf_reader: CacheManager unavailable ({_cm_err}) — using built-in dict cache")

# ── Built-in process-level chunk cache (always works, no dependencies) ───────
# key: (absolute_path_str, chunk_size, chunk_overlap)  →  list[dict]
_CHUNK_CACHE: Dict[tuple, List[Dict[str, Any]]] = {}

# Reuse the same DocumentProcessor instance to avoid re-initializing per call
_processor: Optional[DocumentProcessor] = None


def _get_processor() -> DocumentProcessor:
    global _processor
    if _processor is None:
        _processor = DocumentProcessor(cache_manager=_cache_manager, use_cache=_cache_manager is not None)
    return _processor


@tool
def read_pdf_chunks(pdf_path: str) -> List[Dict[str, Any]]:
    """Read a PDF file and return its text split into overlapping chunks.

    Each chunk contains:
    - content: the chunk text
    - chunk_id: a unique identifier
    - page_number: the source page (if available)
    - chunk_index: position in the sequence
    - metadata: any enrichment metadata

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        A list of dictionaries, one per chunk.
    """
    processor = _get_processor()
    cache_key = (str(Path(pdf_path).resolve()), processor.chunk_size, processor.chunk_overlap)

    # 1. Check built-in process-level dict cache first
    if cache_key in _CHUNK_CACHE:
        cached = _CHUNK_CACHE[cache_key]
        log.info(f"pdf_reader: cache HIT — {len(cached)} chunks for {Path(pdf_path).name}")
        return cached

    # 2. Full processing
    log.info(f"pdf_reader: cache MISS — processing {Path(pdf_path).name}")
    doc_chunks = processor.process_pdf(pdf_path)

    result = [
        {
            "content": chunk.content,
            "chunk_id": chunk.chunk_id,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "metadata": chunk.metadata or {},
        }
        for chunk in doc_chunks
    ]

    # 3. Store in built-in cache for subsequent calls this process
    _CHUNK_CACHE[cache_key] = result
    log.info(f"pdf_reader: cached {len(result)} chunks for {Path(pdf_path).name}")
    return result
