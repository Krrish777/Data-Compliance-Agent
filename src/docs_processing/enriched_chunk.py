"""
Enriched document chunk data models for compliance rule extraction.
This module extends the basic DocumentChunk with rule extraction metadata.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from src.docs_processing.docs_processor import DocumentChunk
from src.docs_processing.rule_logic import RuleLogic

@dataclass
class ComplianceRule:
    """Represents a single extracted compliance rule"""
    rule_id: str
    rule_type: str  # data_retention, data_access, data_quality, data_security, data_privacy
    rule_text: str
    condition: Optional[str]
    action: Optional[str]
    scope: Optional[str]
    penalty: Optional[str] = None
    timeframe: Optional[str] = None
    timeframe_days: Optional[int] = None
    confidence: float = 0.0
    source_reference: Optional[str] = None
    logic: Optional[RuleLogic] = None  # The machine-testable logic

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'rule_id': self.rule_id,
            'rule_type': self.rule_type,
            'rule_text': self.rule_text,
            'condition': self.condition,
            'action': self.action,
            'scope': self.scope,
            'penalty': self.penalty,
            'timeframe': self.timeframe,
            'timeframe_days': self.timeframe_days,
            'confidence': self.confidence,
            'source_reference': self.source_reference,
            'logic': self.logic.model_dump() if self.logic else None
        }

@dataclass
class EnrichedDocumentChunk(DocumentChunk):
    """
    Extended DocumentChunk with rule extraction metadata.
    Inherits all fields from DocumentChunk and adds rule extraction results.
    """
    
    # Rule extraction results
    extracted_rules: List[ComplianceRule] = field(default_factory=list)
    document_type: str = "informational"  # requirement, definition, example, informational
    
    # Extracted entities
    entities: Dict[str, List[str]] = field(default_factory=dict)
    # Example: {"data_types": ["PII", "email"], "timeframes": ["90 days"], "roles": ["admin"]}
    
    # Key definitions found in this chunk
    key_definitions: List[Dict[str, str]] = field(default_factory=list)
    # Example: [{"term": "personal data", "definition": "..."}]
    
    # Metadata about the extraction process
    extraction_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_rule(self, rule: ComplianceRule):
        """Add an extracted rule to this chunk"""
        self.extracted_rules.append(rule)
    
    def has_rules(self) -> bool:
        """Check if this chunk contains any extracted rules"""
        return len(self.extracted_rules) > 0
    
    def get_high_confidence_rules(self, threshold: float = 0.8) -> List[ComplianceRule]:
        """Get only high confidence rules"""
        return [rule for rule in self.extracted_rules if rule.confidence >= threshold]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        base_dict = {
            'content': self.content,
            'source_file': self.source_file,
            'page_number': self.page_number,
            'chunk_index': self.chunk_index,
            'chunk_id': self.chunk_id,
            'metadata': self.metadata,
            'document_type': self.document_type,
            'extracted_rules': [rule.to_dict() for rule in self.extracted_rules],
            'entities': self.entities,
            'key_definitions': self.key_definitions,
            'extraction_metadata': self.extraction_metadata
        }
        return base_dict
    
    def get_embedding_text(self) -> str:
        """
        Get enriched text for embedding generation.
        Combines chunk content with extracted rule information for richer embeddings.
        """
        parts = [self.content]
        
        # Add document type context
        if self.document_type != "informational":
            parts.append(f"[Document Type: {self.document_type}]")
        
        # Add extracted rules summaries
        if self.extracted_rules:
            rule_summaries = []
            for rule in self.extracted_rules:
                rule_summaries.append(
                    f"[Rule: {rule.rule_type} - {rule.action} when {rule.condition}]"
                )
            parts.extend(rule_summaries)
        
        # Add key entities
        if self.entities:
            entity_text = []
            for entity_type, values in self.entities.items():
                if values:
                    entity_text.append(f"[{entity_type}: {', '.join(values)}]")
            parts.extend(entity_text)
        
        return " ".join(parts)
