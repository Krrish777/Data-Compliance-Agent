"""
Rule structuring: convert natural language or extracted rules to StructuredRule format.

Supports:
- ComplianceRuleModel with logic -> StructuredRule
- Dict with structured fields -> StructuredRule
- LLM structuring (optional, when logic is missing)
"""
from typing import Any, Dict, List, Optional

from src.models.compilance_rules import ComplianceRuleModel, RuleLogic
from src.models.structured_rule import StructuredRule
from src.utils.logger import setup_logger

log = setup_logger(__name__)

RULE_TYPE_MAP = {
    "data_retention": "retention",
    "data_access": "access",
    "data_quality": "quality",
    "data_security": "security",
    "data_privacy": "privacy",
}


def rule_from_dict(d: Dict[str, Any]) -> StructuredRule:
    """Create StructuredRule from dict (e.g. from state or API)."""
    return StructuredRule(
        rule_id=str(d.get("rule_id", "")),
        rule_text=str(d.get("rule_text", "")),
        source=str(d.get("source", d.get("source_reference", ""))),
        rule_type=RULE_TYPE_MAP.get(
            str(d.get("rule_type", "")).lower(), d.get("rule_type", "quality")
        ),
        target_column=str(d.get("target_column", d.get("field", ""))),
        operator=str(d.get("operator", "=")),
        value=d.get("value") if d.get("value") else None,
        data_type=str(d.get("data_type", "string")),
        applies_to_tables=d.get("applies_to_tables"),
        requires_pii=bool(d.get("requires_pii", False)),
        confidence=float(d.get("confidence", 1.0)),
        structured_by=str(d.get("structured_by", "manual")),
    )


def rule_from_compliance_model(rule: ComplianceRuleModel) -> Optional[StructuredRule]:
    """Convert ComplianceRuleModel to StructuredRule when logic is present."""
    if not rule.logic or not rule.logic.field:
        return None
    logic = rule.logic
    return StructuredRule(
        rule_id=rule.rule_id,
        rule_text=rule.rule_text,
        source=rule.source_reference or "",
        rule_type=RULE_TYPE_MAP.get(rule.rule_type, rule.rule_type),
        target_column=logic.field,
        operator=logic.operator or "=",
        value=logic.value if logic.value else None,
        data_type=_infer_data_type(logic),
        confidence=rule.confidence,
        structured_by="extraction",
    )


def _infer_data_type(logic: RuleLogic) -> str:
    """Infer data type from logic value."""
    v = (logic.value or "").upper()
    if "NOW()" in v or "INTERVAL" in v or "datetime(" in v or "DAY" in v:
        return "datetime"
    if logic.operator and "LIKE" in logic.operator.upper():
        return "string"
    try:
        float(str(logic.value or "0"))
        return "number"
    except ValueError:
        return "string"


def structure_rules(
    rules: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]] = None,
) -> List[StructuredRule]:
    """
    Structure multiple rules. Accepts dicts or ComplianceRuleModel-like dicts.

    When schema is provided, validates target_column exists (logs warning if not).
    """
    structured = []
    for r in rules:
        if isinstance(r, dict):
            sr = rule_from_dict(r)
        elif isinstance(r, ComplianceRuleModel):
            sr = rule_from_compliance_model(r)
            if sr is None:
                log.warning(f"Rule '{r.rule_id}' has no logic, skipping")
                continue
        else:
            log.warning(f"Unknown rule type: {type(r)}, skipping")
            continue

        if schema and sr.target_column:
            has_col = any(
                c.get("column_name") == sr.target_column
                for t in schema.values()
                for c in t.get("columns", [])
            )
            if not has_col:
                log.debug(
                    f"Rule '{sr.rule_id}' target_column '{sr.target_column}' "
                    "not found in schema (may be table-specific)"
                )
        structured.append(sr)
    return structured
