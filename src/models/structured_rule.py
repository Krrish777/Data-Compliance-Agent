"""
Structured rule representation for compliance scanning.

Converts natural language rules into a format that can be deterministically
translated to SQL for database scanning.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StructuredRule:
    """
    A compliance rule converted from natural language to structured format.

    This representation is designed to be easily converted to SQL.
    """

    # Identification
    rule_id: str
    rule_text: str
    source: str
    rule_type: str  # retention, access, quality, security, privacy

    # SQL components
    target_column: str
    operator: str  # <, >, =, !=, IS NULL, IS NOT NULL, LIKE, NOT LIKE, ~
    value: Optional[str] = None  # Can be SQL expression e.g. "NOW() - INTERVAL '90 days'"
    data_type: str = "string"  # datetime, string, number, boolean

    # Contextual information
    applies_to_tables: Optional[List[str]] = None
    requires_pii: bool = False
    confidence: float = 1.0

    # Complexity classification — controls which executor runs this rule.
    #   simple       → standard keyset SQL path
    #   between      → range check: value="lo,hi" evaluated in Python
    #   regex        → re.search(value, row[column])
    #   cross_field  → row[column] op row[second_column]
    #   date_math    → datetime arithmetic (NOW() / intervals)
    rule_complexity: str = "simple"

    # Used only when rule_complexity == "cross_field".
    # Holds the name of the right-hand column for comparison.
    second_column: Optional[str] = None

    # Metadata
    structured_at: Optional[str] = None
    structured_by: str = "llm"  # llm, manual, hybrid, llm_corrected
