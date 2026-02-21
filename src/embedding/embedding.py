import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass
from fastembed import TextEmbedding
from src.docs_processing.docs_processor import DocumentChunk
from src.utils.logger import setup_logger

log = setup_logger(__name__)

@dataclass
class EmbeddedChunk:
    """Document chunk with its embedding vector"""
    
    chunk: DocumentChunk
    embedding: np.ndarray
    embedding_model: str
    
    def to_vector_db_format(self) -> Dict[str, Any]:
        return {
            'id': self.chunk.chunk_id,
            'embedding': self.embedding.tolist(),
            'content': self.chunk.content,
            'source_file': self.chunk.source_file,
            'source_type': 'pdf',  # Assuming PDF for now
            'page_number': self.chunk.page_number,
            'chunk_index': self.chunk.chunk_index,
            'start_char': self.chunk.start_chunks,
            'end_char': self.chunk.end_chunks,
            'metadata': self.chunk.metadata,
            'embedding_model': self.embedding_model,
        }
        
class EmbeddingGenerator:
    def __init__(self, model_name: str = 'BAAI/bge-small-en-v1.5'):
        self.model_name = model_name
        self.model = None
        self.embedding_dim = 0
        self._initialize_model()
        
    def _initialize_model(self):
        try:
            log.info(f"Loading embedding model: {self.model_name}")
            self.model = TextEmbedding(self.model_name)
            
            sample_embedding = list(self.model.embed(["test"]))[0]
            self.embedding_dim = len(sample_embedding)
            
            log.info(f"Model loaded successfully. Embedding dimension: {self.embedding_dim}")
        except Exception as e:
            log.error(f"Failed to load embedding model: {e}")
            raise
    
    def generate_embedding(self, chunks: List[DocumentChunk]) -> List[EmbeddedChunk]:
        if not chunks:
            log.warning("No document chunks provided for embedding generation.")
            return []
        
        if self.model is None:
            log.error("Embedding model is not initialized")
            raise
        
        log.info(f"Generating embeddings for {len(chunks)} document chunks")
        
        try:
            texts = [chunk.content for chunk in chunks]
            embeddings = list(self.model.embed(texts))
            
            embedded_chunks = []
            for chunk, embedding in zip(chunks, embeddings):
                embedded_chunk = EmbeddedChunk(
                    chunk=chunk,
                    embedding=np.array(embedding, dtype=np.float32),
                    embedding_model=self.model_name
                )
                embedded_chunks.append(embedded_chunk)
                
            log.info(f"Successfully generated embeddings for {len(embedded_chunks)} chunks")
            return embedded_chunks
        
        except Exception as e:
            log.error(f"Error during embedding generation: {e}")
            raise
        
    def generate_query_embedding(self, query: str) -> np.ndarray:
        if not query:
            log.warning("Empty query provided for embedding generation.")
            if self.embedding_dim is None:
                log.error("Embedding dimension is not initialized")
                raise
            return np.zeros(self.embedding_dim, dtype=np.float32)
        
        log.info(f"Generating embedding for query: '{query}'")
        
        try:
            if self.model is None:
                log.error("Embedding model is not initialized")
                raise
            embedding = list(self.model.embed([query]))[0]
            log.info("Successfully generated query embedding")
            return np.array(embedding, dtype=np.float32)
        
        except Exception as e:
            log.error(f"Error during query embedding generation: {e}")
            raise
    
    def get_embedding_dimension(self) -> int:
        return self.embedding_dim
    
    def batch_generate_embeddings(
        self,
        chunks: List[List[DocumentChunk]],
        batch_size: int = 32
    ) -> List[List[EmbeddedChunk]]:
        
        all_embedded_chunks = []
        for i, chunk_batch in enumerate(chunks):
            log.info(f"Processing batch {i+1}/{len(chunks)} with {len(chunk_batch)} chunks")
            
            embedded_chunks = []
            
            for j in range(0, len(chunk_batch), batch_size):
                sub_batch = chunk_batch[j:j+batch_size]
                embedded_sub_batch = self.generate_embedding(sub_batch)
                embedded_chunks.extend(embedded_sub_batch)
                
            all_embedded_chunks.append(embedded_chunks)
        log.info("Completed embedding generation for all batches")
        return all_embedded_chunks