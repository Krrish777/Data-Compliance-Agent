"""
Round-trip retrieval test for the policy-rule Qdrant store.

Reproduces the "Qdrant initialized but data not fetching" bug by verifying:
  1. Ingest (upsert) and query (search) hit the SAME on-disk collection
     even when the working directory changes between calls (cwd-independence
     of the resolved db_path).
  2. Opening PolicyRuleStore a second time in the same process (as the
     interceptor graph does per node invocation) does not silently read
     from an empty collection.
  3. Non-empty search results are returned for a semantically-relevant query.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def _tmp_qdrant_dir(tmp_path, monkeypatch):
    """Use a throw-away qdrant dir so the test never touches the real store."""
    # Override the default DB path the store resolves to.
    from src.vector_database import policy_store as ps_mod

    db_path = tmp_path / "qdrant_test_db"
    monkeypatch.setattr(ps_mod, "DEFAULT_DB_PATH", str(db_path))
    # Clear any cached singletons from prior tests.
    monkeypatch.setattr(ps_mod, "_STORE_SINGLETONS", {}, raising=False)
    yield db_path


def _make_rules():
    from src.models.structured_rule import StructuredRule

    return [
        StructuredRule(
            rule_id="aml_high_value",
            rule_text=(
                "Transactions exceeding 10,000 in value must be flagged for "
                "AML review. High-value transactions require enhanced due "
                "diligence."
            ),
            source="aml_policy",
            rule_type="data_security",
            target_column="Amount_Received",
            operator=">",
            value="10000",
            data_type="number",
            confidence=0.9,
        ),
        StructuredRule(
            rule_id="pii_account_access",
            rule_text=(
                "Account identifiers are PII and require stated business "
                "purpose for access. Access must be logged."
            ),
            source="aml_policy",
            rule_type="data_privacy",
            target_column="Sender_account",
            operator="IS NOT NULL",
            value=None,
            data_type="string",
            confidence=0.9,
        ),
    ]


def test_ingest_then_search_returns_non_empty(_tmp_qdrant_dir):
    """Basic round-trip: upsert rules, search, assert hits."""
    from src.vector_database.policy_store import get_policy_store

    store = get_policy_store()
    n = store.ingest_structured_rules(_make_rules(), framework="AML")
    assert n == 2, "expected 2 rules upserted"

    assert store.count() == 2, "collection count should reflect upsert"

    hits = store.search_policies(
        query_text="high value transaction AML review threshold",
        top_k=5,
    )
    assert hits, "search returned no hits — retrieval bug reproduced"
    assert any(h["payload"].get("rule_id") == "aml_high_value" for h in hits)


def test_search_cwd_independent(_tmp_qdrant_dir, tmp_path, monkeypatch):
    """
    Regression: the store must resolve db_path to an absolute path so that
    ingesting from one cwd and querying from another hits the same collection.
    """
    from src.vector_database.policy_store import get_policy_store

    # Ingest from the project's normal cwd.
    store = get_policy_store()
    store.ingest_structured_rules(_make_rules(), framework="AML")

    # Simulate a subprocess / uvicorn launched from a different directory.
    other_cwd = tmp_path / "somewhere_else"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    # Re-resolve the same singleton — must still find the data.
    store2 = get_policy_store()
    assert store2.count() >= 2, (
        "store lost its data after cwd change — db_path was relative"
    )

    hits = store2.search_policies(query_text="account PII privacy", top_k=5)
    assert hits, "search from different cwd returned empty — path bug"


def test_singleton_reused_across_calls(_tmp_qdrant_dir):
    """
    The interceptor graph calls get_policy_store() on every policy_mapper_node
    invocation; it must return the same instance to avoid Qdrant local-mode
    file-lock contention.
    """
    from src.vector_database.policy_store import get_policy_store

    a = get_policy_store()
    b = get_policy_store()
    assert a is b, "get_policy_store must memoise a single client per process"
