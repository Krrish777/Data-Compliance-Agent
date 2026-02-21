"""
Rule-extraction prompt template.

This prompt powers the LLM node that reads PDF chunks and produces
structured ``ComplianceRuleModel`` objects.

Design principles
-----------------
- **Explicit literal values**: rule_type values match Pydantic's ``Literal``
  exactly (``data_retention``, ``data_access``, etc.).
- **One-shot example**: a single example anchors the JSON schema expectation
  without burning excessive tokens.
- **Chunk awareness**: the template receives ``chunk_index`` / ``total_chunks``
  so the LLM understands it's seeing a fragment, not the whole document.
- **Confidence guidance**: explicit instructions for when to use low vs. high
  confidence so the downstream router can triage.
"""
from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

# ═══════════════════════════════════════════════════════════════════════════════
#  System prompt (reusable constant)
# ═══════════════════════════════════════════════════════════════════════════════
RULE_EXTRACTION_SYSTEM_PROMPT = """\
You are an expert compliance analyst. Your job is to read a chunk of a
regulatory or policy document and extract every testable compliance rule
you can find.

For EACH rule you extract, provide a JSON object with these fields:

- **rule_id**: A unique slug like "RET-001", "ACC-002", "QUAL-003", etc.
  Use prefixes: RET (retention), ACC (access), QUAL (quality),
  SEC (security), PRIV (privacy).
- **rule_type**: EXACTLY one of:
  `data_retention`, `data_access`, `data_quality`, `data_security`, `data_privacy`
- **rule_text**: The verbatim sentence(s) from the document that state the rule.
- **condition**: When or under what circumstances the rule applies
  (null if universal).
- **action**: What must be done to comply.
- **scope**: What data / systems / roles this applies to (null if universal).
- **penalty**: Consequences of non-compliance (null if not stated).
- **timeframe**: Human-readable deadline or retention period (null if none).
- **confidence**: A float 0.0–1.0.
  - 0.9–1.0 = the text explicitly states a testable rule.
  - 0.7–0.89 = strongly implied but not word-for-word.
  - 0.5–0.69 = possible rule, needs human review.
  - Below 0.5 = do NOT extract, skip it.
- **source_reference**: Section number, article, or page reference from the
  document (null if not apparent).
- **logic**: An object with {{field, operator, value}} that represents the
  rule as a database check, or null if the rule isn't directly testable
  against a single column.

Also classify the chunk's **document_type** as one of:
  `requirement`, `definition`, `example`, `informational`

Extract **key_definitions** for any important terms defined in the chunk.

If the chunk contains no extractable rules, return an empty
`extracted_rules` list — do NOT hallucinate rules.

Important: you are seeing chunk {chunk_index} of {total_chunks}.
Some rules may span multiple chunks. Extract what you can from THIS chunk
and note in the rule_text if it appears to be a fragment.

RETURN ONLY a single valid JSON object — no markdown fences, no explanation,
no text before or after. The object must have exactly these top-level keys:
  document_type, entities, extracted_rules, key_definitions
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  ChatPromptTemplate (ready to pipe into structured LLM)
# ═══════════════════════════════════════════════════════════════════════════════
rule_extraction_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", RULE_EXTRACTION_SYSTEM_PROMPT),
        (
            "human",
            "Here is chunk {chunk_index} of {total_chunks} from the compliance "
            "document:\n\n---\n{chunk_text}\n---\n\n"
            "Respond with ONLY the JSON object. No markdown. No explanation.",
        ),
    ]
)
