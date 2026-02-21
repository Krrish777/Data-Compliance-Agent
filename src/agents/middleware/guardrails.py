"""
Guardrails — input and output validation for LLM calls.

Two levels of protection:
1. **Input guardrail**: Validate/sanitize what goes INTO the LLM.
   - Reject empty chunks, truncate oversized text, strip PII.
2. **Output guardrail**: Validate what comes OUT of the LLM.
   - Schema conformance, confidence range checks, blocked content.

Usage
-----
    from src.agents.middleware.guardrails import (
        InputGuardrail, OutputGuardrail,
        validate_chunk_input, validate_extraction_output,
    )

    # Quick function-level checks:
    clean_text = validate_chunk_input(raw_chunk_text)
    validated  = validate_extraction_output(llm_result)

    # Class-based for composable pipelines:
    ig = InputGuardrail(max_chars=8000)
    og = OutputGuardrail(allowed_rule_types={...})
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Set

from src.models.compilance_rules import ComplianceRuleModel, RuleExtractionOutput
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# ── Valid values (single source of truth) ─────────────────────────────────────
VALID_RULE_TYPES = frozenset({
    "data_retention",
    "data_access",
    "data_quality",
    "data_security",
    "data_privacy",
})

VALID_DOCUMENT_TYPES = frozenset({
    "requirement",
    "definition",
    "example",
    "informational",
})

# ── Simple PII patterns to strip before sending to LLM ───────────────────────
_PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),       # US SSN
    (re.compile(r"\b\d{16}\b"), "[CC_REDACTED]"),                     # Credit card
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
     "[EMAIL_REDACTED]"),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  INPUT GUARDRAILS
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class InputGuardrail:
    """
    Validates and sanitizes text before it enters the LLM.

    Parameters
    ----------
    max_chars : int
        Maximum characters per chunk. Longer text is truncated.
    min_chars : int
        Minimum characters. Shorter chunks are rejected (return None).
    strip_pii : bool
        Whether to redact obvious PII patterns.
    """

    max_chars: int = 8000
    min_chars: int = 50
    strip_pii: bool = True

    def __call__(self, text: str) -> Optional[str]:
        """Return cleaned text or None if the chunk should be skipped."""
        if not text or not text.strip():
            log.debug("InputGuardrail: empty chunk skipped")
            return None

        text = text.strip()

        if len(text) < self.min_chars:
            log.debug(f"InputGuardrail: chunk too short ({len(text)} chars)")
            return None

        if len(text) > self.max_chars:
            log.warning(
                f"InputGuardrail: truncating chunk from {len(text)} "
                f"to {self.max_chars} chars"
            )
            text = text[: self.max_chars]

        if self.strip_pii:
            for pattern, replacement in _PII_PATTERNS:
                text = pattern.sub(replacement, text)

        return text


def validate_chunk_input(text: str, max_chars: int = 8000) -> Optional[str]:
    """Convenience function — default InputGuardrail."""
    return InputGuardrail(max_chars=max_chars)(text)


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTPUT GUARDRAILS
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class OutputGuardrail:
    """
    Validates LLM extraction output before it enters the state.

    Checks
    ------
    - ``rule_type`` is in the allowed set.
    - ``confidence`` is in [0.0, 1.0].
    - ``rule_text`` is not empty.
    - ``document_type`` is in the allowed set.
    """

    allowed_rule_types: Set[str] = field(default_factory=lambda: set(VALID_RULE_TYPES))
    allowed_doc_types: Set[str] = field(default_factory=lambda: set(VALID_DOCUMENT_TYPES))
    min_confidence: float = 0.0
    max_confidence: float = 1.0

    def validate_rule(self, rule: ComplianceRuleModel) -> Optional[ComplianceRuleModel]:
        """Return the rule if valid, None if it should be dropped."""
        # Rule type check
        if rule.rule_type not in self.allowed_rule_types:
            log.warning(
                f"OutputGuardrail: dropping rule {rule.rule_id} — "
                f"invalid rule_type: {rule.rule_type!r}"
            )
            return None

        # Confidence range
        if not (self.min_confidence <= rule.confidence <= self.max_confidence):
            log.warning(
                f"OutputGuardrail: clamping confidence for {rule.rule_id} "
                f"from {rule.confidence} to [0, 1]"
            )
            rule.confidence = max(0.0, min(1.0, rule.confidence))

        # Rule text non-empty
        if not rule.rule_text or not rule.rule_text.strip():
            log.warning(
                f"OutputGuardrail: dropping rule {rule.rule_id} — empty rule_text"
            )
            return None

        return rule

    def validate_extraction(
        self,
        output: RuleExtractionOutput,
    ) -> RuleExtractionOutput:
        """Validate and filter the entire extraction result."""
        valid_rules = []
        for rule in output.extracted_rules:
            validated = self.validate_rule(rule)
            if validated is not None:
                valid_rules.append(validated)

        dropped = len(output.extracted_rules) - len(valid_rules)
        if dropped:
            log.info(
                f"OutputGuardrail: kept {len(valid_rules)}, "
                f"dropped {dropped} invalid rules"
            )

        output.extracted_rules = valid_rules
        return output


def validate_extraction_output(
    output: RuleExtractionOutput,
) -> RuleExtractionOutput:
    """Convenience function — default OutputGuardrail."""
    return OutputGuardrail().validate_extraction(output)
