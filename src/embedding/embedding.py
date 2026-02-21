import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from fastembed import TextEmbedding
from src.docs_processing.docs_processor import DocumentChunk
from src.utils.logger import setup_logger
from src.utils.document_cache import CacheManager

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
    def __init__(
        self, 
        model_name: str = 'BAAI/bge-small-en-v1.5',
        cache_manager: Optional[CacheManager] = None,
        use_cache: bool = True
    ):
        self.model_name = model_name
        self.model = None
        self.embedding_dim = 0
        self.cache_manager = cache_manager
        self.use_cache = use_cache and cache_manager is not None
        self._initialize_model()
        
        if self.use_cache:
            log.info("EmbeddingGenerator: Cache ENABLED")
        else:
            log.info("EmbeddingGenerator: Cache DISABLED")
        
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
        try:
            log.info(f"Generating embeddings for {len(chunks)} chunks")
            
            # Check cache for existing embeddings
            cached_embeddings = {}
            chunks_to_embed = []
            chunk_indices_to_embed = []
            
            if self.use_cache and self.cache_manager:
                contents = [chunk.content for chunk in chunks]
                cached_embeddings = self.cache_manager.get_embeddings_batch(
                    contents=contents,
                    model_name=self.model_name
                )
                
                # Identify which chunks need embedding
                for idx, chunk in enumerate(chunks):
                    if idx not in cached_embeddings:
                        chunks_to_embed.append(chunk)
                        chunk_indices_to_embed.append(idx)
                
                if cached_embeddings:
                    log.info(f"📦 Found {len(cached_embeddings)}/{len(chunks)} cached embeddings")
            else:
                chunks_to_embed = chunks
                chunk_indices_to_embed = list(range(len(chunks)))
            
            # Generate embeddings for uncached chunks
            new_embeddings = {}
            if chunks_to_embed:
                log.info(f"Generating {len(chunks_to_embed)} new embeddings")
                if self.model is None:
                    log.error("Embedding model is not initialized")
                    raise
                texts = [chunk.content for chunk in chunks_to_embed]
                embeddings_list = list(self.model.embed(texts))
                
                # Store new embeddings
                for idx, chunk, embedding in zip(chunk_indices_to_embed, chunks_to_embed, embeddings_list):
                    embedding_array = np.array(embedding, dtype=np.float32)
                    new_embeddings[idx] = embedding_array
                    
                    # Cache the new embedding
                    if self.use_cache and self.cache_manager:
                        self.cache_manager.set_embedding(
                            content=chunk.content,
                            embedding=embedding_array,
                            model_name=self.model_name
                        )
            
            # Combine cached and new embeddings
            all_embeddings = {**cached_embeddings, **new_embeddings}
            
            # Create EmbeddedChunk objects in original order
            embedded_chunks = []
            for idx, chunk in enumerate(chunks):
                embedded_chunk = EmbeddedChunk(
                    chunk=chunk,
                    embedding=all_embeddings[idx],
                    embedding_model=self.model_name
                )
                embedded_chunks.append(embedded_chunk)
                
            log.info(f"Successfully generated embeddings for {len(embedded_chunks)} chunks "
                    f"({len(cached_embeddings)} cached, {len(new_embeddings)} new)")
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
        
        # Try cache first
        if self.use_cache and self.cache_manager:
            cached_embedding = self.cache_manager.get_embedding(
                content=query,
                model_name=self.model_name
            )
            if cached_embedding is not None:
                log.info("Query embedding loaded from cache")
                return cached_embedding
        
        log.info(f"Generating embedding for query: '{query[:50]}...'")
        
        try:
            if self.model is None:
                log.error("Embedding model is not initialized")
                raise
            embedding = list(self.model.embed([query]))[0]
            embedding_array = np.array(embedding, dtype=np.float32)
            
            # Cache the query embedding
            if self.use_cache and self.cache_manager:
                self.cache_manager.set_embedding(
                    content=query,
                    embedding=embedding_array,
                    model_name=self.model_name
                )
            
            log.info("Successfully generated query embedding")
            return embedding_array
        
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