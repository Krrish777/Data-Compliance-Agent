"""
This module defines the data models for capturing the testable logic of a compliance rule.
"""
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field, field_validator

class RuleLogic(BaseModel):
    """
    Represents the structured, testable logic of a compliance rule,
    designed to be translatable into a database query or validation check.
    """
    field: str = Field(default="",description="The database column or data field the rule applies to (e.g., 'account_closed_date', 'email').")
    operator: str = Field(default="",description="The comparison operator for the check (e.g., '<', '>', '=', 'IS NOT NULL', 'MATCHES_REGEX').")
    value: str = Field(default="",description="The value to compare against (e.g., 'NOW() - 90 DAYS', '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$').")

    @field_validator("field", "operator", "value", mode="before")
    @classmethod
    def coerce_to_str(cls, v):
        """LLMs sometimes return None or numeric values -- coerce to str."""
        if v is None:
            return ""
        return str(v)

class ComplianceRuleModel(BaseModel):
    """Pydantic model for a single extracted compliance rule."""
    rule_id: str
    rule_type: Literal["data_retention", "data_access", "data_quality", "data_security", "data_privacy"]
    rule_text: str
    condition: Optional[str] = None
    action: Optional[str] = None
    scope: Optional[str] = None
    penalty: Optional[str] = None
    timeframe: Optional[str] = None
    # timeframe_days removed — Groq rejects "" for integer fields at the API
    # level before Pydantic can coerce it. Parse from `timeframe` if needed.
    confidence: float
    source_reference: Optional[str] = None
    logic: Optional[RuleLogic] = None

    @field_validator(
        'penalty', 'timeframe', 'source_reference',
        'scope', 'condition', 'action',
        mode='before',
    )
    @classmethod
    def convert_unknown_to_none(cls, v):
        """Coerce placeholder strings the LLM sends to None."""
        if v in ('unknown', 'null', 'none', 'n/a', ''):
            return None
        return v

class KeyDefinitionModel(BaseModel):
    """Pydantic model for key definitions"""
    term: str = Field(description="The term being defined")
    definition: str = Field(description="The definition of the term")

class RuleExtractionOutput(BaseModel):
    """Complete structured output from rule extraction"""
    document_type: str = Field(description="Type: requirement, definition, example, or informational")
    extracted_rules: List[ComplianceRuleModel] = Field(default_factory=list, description="List of extracted compliance rules")
    entities: Dict[str, List[str]] = Field(default_factory=dict, description="Extracted entities by type")
    key_definitions: List[KeyDefinitionModel] = Field(default_factory=list, description="Key terms and definitions")

    @field_validator("entities", mode="before")
    @classmethod
    def coerce_entities(cls, v):
        """LLMs sometimes return [] or Dict[str, str] for entities."""
        if not v or isinstance(v, list):
            return {}
        if isinstance(v, dict):
            # Flatten any str values to single-item lists
            return {
                k: ([vv] if isinstance(vv, str) else list(vv))
                for k, vv in v.items()
            }
        return {}

    @field_validator("key_definitions", mode="before")
    @classmethod
    def coerce_key_definitions(cls, v):
        """LLMs sometimes return a dict instead of a list."""
        if isinstance(v, dict):
            return []
        return v or []

    @field_validator("document_type", mode="before")
    @classmethod
    def coerce_document_type(cls, v):
        if not v or not isinstance(v, str):
            return "informational"
        return v
