"""
Golden test for rule_extraction_node.

Pins the shape of extracted rules against the generated AML policy PDF so any
prompt drift, model change, or parser regression is visible in CI.

Skipped if GROQ_API_KEY is unset (live LLM call required).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_PDF = ROOT / "data" / "AML_Compliance_Policy.pdf"


pytestmark = [
    pytest.mark.skipif(
        not os.getenv("GROQ_API_KEY"),
        reason="GROQ_API_KEY not set — skipping live LLM golden test",
    ),
    pytest.mark.slow,
]


@pytest.fixture(scope="module")
def policy_pdf_path() -> str:
    """Generate the AML policy PDF if it's missing, return its absolute path."""
    if not POLICY_PDF.exists():
        from scripts.generate_policy_pdf import build_pdf
        build_pdf(str(POLICY_PDF))
    return str(POLICY_PDF)


def test_rule_extraction_produces_valid_compliance_rules(policy_pdf_path: str):
    """The LLM must produce at least one well-formed ComplianceRuleModel."""
    from src.agents.nodes.rule_extraction import rule_extraction_node
    from src.models.compilance_rules import ComplianceRuleModel

    state = {"document_path": policy_pdf_path}
    result = rule_extraction_node(state)

    assert result["current_stage"] == "extraction_complete", (
        f"expected extraction_complete, got {result.get('current_stage')}: "
        f"errors={result.get('errors')}"
    )
    raw_rules = result.get("raw_rules", [])
    assert len(raw_rules) >= 1, (
        f"expected ≥1 extracted rule, got {len(raw_rules)}"
    )

    # Every rule must be a valid ComplianceRuleModel with non-empty id + text.
    for rule in raw_rules:
        assert isinstance(rule, ComplianceRuleModel), (
            f"rule is not ComplianceRuleModel: {type(rule)}"
        )
        assert rule.rule_id, "rule_id must be non-empty"
        assert rule.rule_text.strip(), "rule_text must be non-empty"
        assert 0.0 <= rule.confidence <= 1.0, (
            f"confidence {rule.confidence} out of [0, 1]"
        )
        assert rule.rule_type in {
            "data_retention", "data_access", "data_quality",
            "data_security", "data_privacy",
        }


def test_rule_extraction_cache_round_trip(policy_pdf_path: str):
    """Second extraction on the same PDF must hit the cache (near-zero latency)."""
    import time

    from src.agents.nodes.rule_extraction import rule_extraction_node

    # First call populates cache (may be slow).
    rule_extraction_node({"document_path": policy_pdf_path})

    t0 = time.perf_counter()
    result = rule_extraction_node({"document_path": policy_pdf_path})
    elapsed = time.perf_counter() - t0

    assert result["current_stage"] == "extraction_complete"
    # Cache hits should return in well under a second.
    assert elapsed < 2.0, (
        f"cached extraction took {elapsed:.2f}s — cache may be broken"
    )
