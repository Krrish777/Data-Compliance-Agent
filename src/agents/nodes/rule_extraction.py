"""
Rule extraction node — the core LLM node in the compliance pipeline.

Reads PDF chunks (from the ``document_path`` in state) and extracts
structured ``ComplianceRuleModel`` objects using a Groq LLM with
``with_structured_output``.

Integrates every module we built:
- **prompts**      → ``rule_extraction_prompt``
- **middleware**    → ``retry_with_backoff``, ``validate_chunk_input``,
                      ``validate_extraction_output``, ``log_node_execution``
- **memory**       → ``ExtractionMemory`` (cache + corrections)
- **streaming**    → ``ProgressCallback``
- **runtime**      → ``get_rate_limiter``
- **tools**        → ``read_pdf_chunks`` (PDF → chunks)
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from langchain_groq import ChatGroq

from src.agents.memory.store import ExtractionMemory, get_store
from src.agents.middleware.guardrails import (
    validate_chunk_input,
    validate_extraction_output,
)
from src.agents.middleware.logging_mw import log_node_execution
from src.agents.middleware.retry import retry_with_backoff
from src.agents.prompts.rule_extraction import rule_extraction_prompt
from src.agents.runtime.config import get_rate_limiter
from src.agents.streaming.callbacks import ProgressCallback
from src.agents.tools.pdf_reader import read_pdf_chunks
from src.models.compilance_rules import ComplianceRuleModel, RuleExtractionOutput
from src.utils.logger import setup_logger

log = setup_logger(__name__)


# ── Internal helper: call the LLM for one chunk ─────────────────────────────
@retry_with_backoff(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
def _extract_from_chunk(
    chain: Any,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
) -> RuleExtractionOutput:
    """
    Invoke the plain LLM chain for a single chunk (with retry).

    Uses raw JSON parsing instead of with_structured_output so that
    Groq's tool/function-call token limit is never hit.
    """
    import json
    import re

    response = chain.invoke(
        {
            "chunk_text": chunk_text,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
        }
    )
    content: str = response.content if hasattr(response, "content") else str(response)

    # Strip markdown fences the model may still add
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())

    # Find the outermost JSON object (tolerates leading/trailing prose)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError(f"LLM response contained no JSON object: {content[:200]}")

    data = json.loads(match.group(0))
    return RuleExtractionOutput.model_validate(data)


# ── The LangGraph node ──────────────────────────────────────────────────────
@log_node_execution
def rule_extraction_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: extract compliance rules from a policy PDF.

    Reads from state
    ----------------
    - document_path : absolute path to the policy PDF

    Writes to state
    ---------------
    - raw_rules     : List[ComplianceRuleModel]  (Annotated + operator.add)
    - current_stage : 'extraction_complete' | 'extraction_failed'
    - errors        : appends on failure

    Pipeline per chunk
    ------------------
    1. **Input guardrail** — skip empty / too-short / PII-laden chunks.
    2. **LLM call** — prompt → structured output (with retry on 400/429/500).
    3. **Output guardrail** — drop rules with bad rule_type or empty text.
    4. **Dedup** — skip rules whose ``rule_id`` was already seen.
    5. **Memory** — cache results so re-running the same PDF is instant.
    """
    document_path: str = state.get("document_path", "")
    if not document_path:
        log.error("rule_extraction_node: no document_path in state")
        return {
            "raw_rules": [],
            "current_stage": "extraction_failed",
            "errors": ["rule_extraction: missing document_path"],
        }

    # ── 0. Check long-term memory cache ─────────────────────────────────
    store = get_store()
    memory = ExtractionMemory(store)
    cached = memory.load_extraction(document_path)
    if cached:
        log.info(
            f"rule_extraction_node: cache hit — "
            f"{cached['rule_count']} rules from previous run"
        )
        # Reconstruct Pydantic models from cached dicts
        rules = [ComplianceRuleModel(**r) for r in cached["rules"]]
        return {
            "raw_rules": rules,
            "current_stage": "extraction_complete",
        }

    # ── 1. Read PDF chunks via the tool ─────────────────────────────────
    log.info(f"rule_extraction_node: reading PDF from '{document_path}'")
    try:
        chunks = read_pdf_chunks.invoke({"pdf_path": document_path})
    except Exception as e:
        log.error(f"rule_extraction_node: PDF read failed — {e}")
        return {
            "raw_rules": [],
            "current_stage": "extraction_failed",
            "errors": [f"rule_extraction: PDF read error — {e}"],
        }

    if not chunks:
        log.warning("rule_extraction_node: PDF produced 0 chunks")
        return {
            "raw_rules": [],
            "current_stage": "extraction_failed",
            "errors": ["rule_extraction: no chunks extracted from PDF"],
        }

    total_chunks = len(chunks)
    log.info(f"rule_extraction_node: {total_chunks} chunks to process")

    # ── 2. Build the LLM chain ──────────────────────────────────────────
    #   - Plain ChatGroq — NO with_structured_output (avoids Groq's
    #     tool/function-call token limit that causes 400 tool_use_failed)
    #   - We ask the model to return raw JSON and parse it ourselves
    rate_limiter = get_rate_limiter()
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        rate_limiter=rate_limiter,
        timeout=30,
        max_retries=0,  # handled by @retry_with_backoff on the caller
    )
    chain = rule_extraction_prompt | llm

    # ── 3. Process each chunk ───────────────────────────────────────────
    all_rules: List[ComplianceRuleModel] = []
    seen_ids: Set[str] = set()
    progress = ProgressCallback(total=total_chunks)

    for idx, chunk in enumerate(chunks):
        chunk_text = chunk.get("content", "")
        chunk_index = idx + 1

        # Input guardrail
        clean_text = validate_chunk_input(chunk_text)
        if clean_text is None:
            progress.tick(f"Chunk {chunk_index}/{total_chunks} — skipped (guardrail)")
            continue

        # LLM call (wrapped in retry_with_backoff)
        try:
            output: RuleExtractionOutput = _extract_from_chunk(
                chain, clean_text, chunk_index, total_chunks
            )
        except Exception as e:
            log.warning(
                f"rule_extraction_node: chunk {chunk_index} failed "
                f"after retries — {e}"
            )
            progress.tick(f"Chunk {chunk_index}/{total_chunks} — FAILED")
            continue

        # Output guardrail
        output = validate_extraction_output(output)

        # Dedup
        for rule in output.extracted_rules:
            if rule.rule_id not in seen_ids:
                seen_ids.add(rule.rule_id)
                all_rules.append(rule)

        progress.tick(
            f"Chunk {chunk_index}/{total_chunks} — "
            f"{len(output.extracted_rules)} rules"
        )

    # ── 4. Save to long-term memory ─────────────────────────────────────
    rules_as_dicts = [r.model_dump() for r in all_rules]
    memory.save_extraction(document_path, rules_as_dicts)

    log.info(
        f"rule_extraction_node: extracted {len(all_rules)} unique rules "
        f"from {total_chunks} chunks"
    )

    return {
        "raw_rules": all_rules,
        "current_stage": "extraction_complete",
    }
