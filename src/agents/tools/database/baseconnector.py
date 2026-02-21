from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from sqlmodel import Session, create_engine
from src.utils.logger import setup_logger
from sentence_transformers import SentenceTransformer
import numpy as np

log = setup_logger(__name__)

class BaseDatabaseConnector(ABC):
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.engine = None
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.session: Optional[Session] = None
        self.categories = {
            'email': 'email address contact mail electronic mail',
            'phone': 'phone number telephone mobile cell contact number',
            'ssn': 'social security number SSN tax identification',
            'credit_card': 'credit card number payment card debit card',
            'name': 'first name last name full name person name',
            'address': 'street address home address postal address location',
            'password': 'password credential secret key authentication',
            'health': 'medical record health data diagnosis patient',
            'financial': 'salary income revenue bank account balance'
        }
        self.category_embeddings = {
            cat: self.model.encode(desc)
            for cat, desc in self.categories.items()
        }
        
    def connect(self):
        """Create a database engine and session"""
        try:
            self.engine = create_engine(
                self.connection_string,
                echo=False,
                connect_args={"timeout": 30}
            )
            self.session = Session(self.engine)
            log.info(f"Connected to database: {self.connection_string}")
        except Exception as e:
            log.error(f"Failed to connect to database: {e}")
            raise
        return self.session
    
    @abstractmethod
    def discover_schema(self) -> Dict[str, Dict[str, Any]]:
        """Discover and return the database schema"""
        pass
    
    def identify_sensitive_columns(self, schema: Dict) -> List[Dict[str, Any]]:
        """Identify potentially sensitive columns based on naming conventions"""
        sensitive_columns = []
        
        for table, info in schema.items():
            for col in info['columns']:
                col_name = col['column_name'].lower()
                col_embedding = self.model.encode(col_name.replace('_', ' '))
                
                best_match = None
                best_score = 0.0
                
                for category, cat_embedding in self.category_embeddings.items():
                    similarity = np.dot(col_embedding, cat_embedding) / (
                        np.linalg.norm(col_embedding) * np.linalg.norm(cat_embedding)
                        )
                    if similarity > best_score:
                        best_score = similarity
                        best_match = category
                        
                if best_score > 0.6:
                    sensitive_columns.append({
                        'table': table,
                        'column': col['column_name'],
                        'data_type': col['data_type'],
                        'category': best_match
                        })
                        
        return sensitive_columns
    
    def close(self):
        """Close the database connection"""
        if self.session:
            self.session.close()
        if self.engine:
            self.engine.dispose()