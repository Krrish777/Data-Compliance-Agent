"""Unit tests for keyset query builder."""
import pytest

from src.agents.tools.database.query_builder import build_keyset_query, extract_last_pk
from src.models.structured_rule import StructuredRule


def test_build_keyset_query_first_page():
    """Test keyset query for first page (no cursor)."""
    rule = StructuredRule(
        rule_id="test",
        rule_text="Test",
        source="Test",
        rule_type="retention",
        target_column="deleted_at",
        operator="<",
        value="datetime('now', '-90 days')",
        data_type="datetime",
        confidence=1.0,
    )
    query, params = build_keyset_query(
        rule=rule,
        table_name="users",
        pk_column="id",
        last_pk_value=None,
        batch_size=100,
        db_type="sqlite",
    )
    assert "WHERE" in query
    assert "deleted_at" in query
    assert "ORDER BY \"id\" ASC" in query
    assert "LIMIT 100" in query
    assert params == {}


def test_build_keyset_query_with_cursor():
    """Test keyset query with pagination cursor."""
    rule = StructuredRule(
        rule_id="test",
        rule_text="Test",
        source="Test",
        rule_type="retention",
        target_column="deleted_at",
        operator="<",
        value="datetime('now', '-90 days')",
        data_type="datetime",
        confidence=1.0,
    )
    query, params = build_keyset_query(
        rule=rule,
        table_name="users",
        pk_column="id",
        last_pk_value="100",
        batch_size=100,
        db_type="sqlite",
    )
    assert '"id" > :last_pk' in query
    assert params == {"last_pk": "100"}


def test_extract_last_pk():
    """Test extracting last PK from results."""
    results = [{"id": 1, "email": "a"}, {"id": 2, "email": "b"}]
    assert extract_last_pk(results, "id") == "2"
    assert extract_last_pk([], "id") is None
